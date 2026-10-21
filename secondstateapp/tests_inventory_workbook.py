"""Small synthetic XLSX packages verify inventory insertion without private data."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import zipfile
from xml.etree import ElementTree as ET

from scripts import inventory_xlsx_package as package


SHEET = "Inventory for Fall 2026"
MAIN = package.NS["s"]
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
X14 = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"


def text_cell(address, value, style=None):
    cell = ET.Element(package.TAG + "c", {"r": address, "t": "inlineStr"})
    if style is not None:
        cell.set("s", str(style))
    ET.SubElement(ET.SubElement(cell, package.TAG + "is"), package.TAG + "t").text = value
    return ET.tostring(cell, encoding="unicode")


def number_cell(address, value, style=None, formula=None):
    cell = ET.Element(package.TAG + "c", {"r": address})
    if style is not None:
        cell.set("s", str(style))
    if formula is not None:
        ET.SubElement(cell, package.TAG + "f").text = formula
    ET.SubElement(cell, package.TAG + "v").text = str(value)
    return ET.tostring(cell, encoding="unicode")


def worksheet(rows, dimension="A1:AC10", ignorable=False):
    extra = f' xmlns:mc="{MC}" xmlns:x14ac="{X14}" mc:Ignorable="x14ac"' if ignorable else ""
    return (f'<worksheet xmlns="{MAIN}"{extra}><dimension ref="{dimension}"/><sheetData>'
            + "".join(f'<row r="{row}" ht="48" customHeight="1"' +
                      (' x14ac:dyDescent="0.25"' if ignorable else '') + f'>{cells}</row>'
                      for row, cells in rows)
            + '</sheetData><mergeCells count="1"><mergeCell ref="A10:C10"/></mergeCells></worksheet>').encode()


def write_package(path, target, reference=None, shared_strings=None):
    names = [SHEET, "References", "Untouched"]
    book = (f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
            + "".join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(names, 1))
            + '</sheets><calcPr calcId="123"/></workbook>').encode()
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, 4))
            + '</Relationships>').encode()
    members = {
        "xl/workbook.xml": book, "xl/_rels/workbook.xml.rels": rels,
        "xl/worksheets/sheet1.xml": target,
        "xl/worksheets/_rels/sheet1.xml.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/></Relationships>',
        "xl/worksheets/sheet2.xml": reference or worksheet([(1, number_cell("A1", 30, formula="SUM(A5:A6)"))]),
        "xl/worksheets/sheet3.xml": worksheet([(1, text_cell("A1", "An unrelated sheet and its formatting", 2))]),
        "xl/styles.xml": b'<styles xmlns="synthetic-fixture">preserve-exactly</styles>',
        "xl/media/image1.png": b'original-image-bytes',
        "xl/drawings/drawing1.xml": b'<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"/>',
        "customXml/item1.xml": b'<custom>original metadata</custom>',
    }
    if shared_strings is not None:
        members["xl/sharedStrings.xml"] = shared_strings
    with zipfile.ZipFile(path, "w") as z:
        for name, value in members.items():
            z.writestr(name, value)
    return members


class InventoryPackageTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.xlsx"
        self.authored = self.root / "authored.xlsx"
        self.output = self.root / "output.xlsx"
        self.lot = {"lot_url": "https://example.com/auction/lot/example?au=1000&lot=7", "auction_house": "Example Auctions",
                    "sale_date": "2026-10-20", "lot_number": "7", "artist": "Example Artist", "title": "Example Print"}

    def source_rows(self, notes="Existing notes", totals=True):
        rows = [
            (4, text_cell("A4", "#") + text_cell("AC4", "DETAILS/LISTING INFO")),
            (5, number_cell("A5", 1) + text_cell("C5", "Original catalog entry", 2) + number_cell("J5", 10, 3) + text_cell("M5", notes)),
            (6, number_cell("A6", 2) + text_cell("C6", "Template entry", 2) + number_cell("J6", 20, 3)),
        ]
        if totals:
            rows.append((8, number_cell("J8", 30, 4, "SUM(J5:J6)")))
        rows.append((10, text_cell("A10", "Footer preserved", 2)))
        return rows

    def authored_rows(self):
        rows = self.source_rows()[:3]
        rows += [
            (7, number_cell("A7", 3, 99) + '<c xmlns="' + MAIN + '" r="C7" t="s" s="99"><v>0</v></c>' + number_cell("J7", 7, 99)),
            (9, number_cell("J9", 37, 99, "SUM(J5:J7)")),
            (11, text_cell("A11", "Footer preserved", 99)),
        ]
        return rows

    def test_totals_expand_to_include_new_inventory_rows(self):
        write_package(self.source, worksheet(self.source_rows()), reference=worksheet([
            (1, number_cell("A1", 30, formula=f"SUM('{SHEET}'!J5:J6)")),
        ]))
        plan = package.inspect(self.source, SHEET, [self.lot])
        self.assertEqual((plan["insert_at"], plan["count"]), (7, 1))
        formulas = {(f["sheet"], f["address"]): f["formula"] for f in plan["formulas"]}
        self.assertEqual(formulas[(SHEET, "J9")], "=SUM(J5:J7)")
        self.assertEqual(formulas[("References", "A1")], f"=SUM('{SHEET}'!J5:J7)")

    def test_lot_seven_is_not_a_duplicate_of_lot_seventy(self):
        notes = "Source: https://example.com/auction/lot/example?au=1000&lot=70\nInventory key: Example Auctions | 2026-10-20 | 70"
        write_package(self.source, worksheet(self.source_rows(notes)))
        plan = package.inspect(self.source, SHEET, [self.lot])
        self.assertEqual(plan["count"], 1)
        self.assertEqual(plan["skipped"], [])

    def test_exact_existing_identity_is_skipped_and_repeated_input_rejected(self):
        notes = "Source: " + self.lot["lot_url"] + "\nInventory key: Example Auctions | 2026-10-20 | 7"
        write_package(self.source, worksheet(self.source_rows(notes)))
        plan = package.inspect(self.source, SHEET, [self.lot])
        self.assertEqual(plan["count"], 0)
        self.assertEqual(plan["skipped"], [{"lot_url": self.lot["lot_url"], "row": 5}])
        with self.assertRaisesRegex(ValueError, "Duplicate lot identities"):
            package.inspect(self.source, SHEET, [self.lot, self.lot])

    def test_preserves_original_cells_styles_and_unrelated_package_members(self):
        members = write_package(self.source, worksheet(self.source_rows()))
        shared = f'<sst xmlns="{MAIN}"><si><t>New researched entry</t></si></sst>'.encode()
        write_package(self.authored, worksheet(self.authored_rows(), dimension="A1:AC11"), shared_strings=shared)
        plan = package.inspect(self.source, SHEET, [self.lot])
        package.preserve(self.source, self.authored, plan, self.output)
        with zipfile.ZipFile(self.output) as z:
            for member in ("xl/worksheets/sheet2.xml", "xl/worksheets/sheet3.xml", "xl/styles.xml", "xl/media/image1.png", "customXml/item1.xml"):
                self.assertEqual(z.read(member), members[member], member)
            root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
            cells = {c.get("r"): c for c in root.iter(package.TAG + "c")}
            self.assertEqual(package.cell_value(cells["C5"], []), "Original catalog entry")
            self.assertEqual(cells["C5"].get("s"), "2")
            self.assertEqual(package.cell_value(cells["C7"], []), "New researched entry")
            self.assertEqual(cells["C7"].get("s"), "2")
            self.assertEqual(cells["J7"].get("s"), "3")
            self.assertEqual(cells["J9"].get("s"), "4")
            self.assertEqual(cells["J9"].find(package.TAG + "f").text, "SUM(J5:J7)")
            self.assertEqual(package.cell_value(cells["J9"], []), 37)
            self.assertEqual(package.cell_value(cells["A11"], []), "Footer preserved")
            self.assertEqual(root.find("s:mergeCells/s:mergeCell", package.NS).get("ref"), "A11:C11")
            self.assertEqual(root.find(package.TAG + "dimension").get("ref"), "A1:AC11")

    def test_changed_source_is_never_overwritten_from_stale_plan(self):
        write_package(self.source, worksheet(self.source_rows()))
        plan = package.inspect(self.source, SHEET, [self.lot])
        with zipfile.ZipFile(self.source, "a") as z:
            z.writestr("new-concurrent-edit.txt", "Somebody else's edit")
        with self.assertRaisesRegex(ValueError, "changed during preparation"):
            package.preserve(self.source, self.authored, plan, self.output)
        self.assertFalse(self.output.exists())

    def test_unsupported_structural_references_stop_before_any_write(self):
        table_target = worksheet(self.source_rows()).replace(b'</worksheet>', b'<tableParts count="1"/></worksheet>')
        write_package(self.source, table_target)
        with self.assertRaisesRegex(ValueError, "tableParts"):
            package.inspect(self.source, SHEET, [self.lot])
        write_package(self.source, worksheet(self.source_rows()))
        with zipfile.ZipFile(self.source, "a") as z:
            z.writestr("xl/calcChain.xml", f'<calcChain xmlns="{MAIN}"><c r="J8" i="1"/></calcChain>')
        with self.assertRaisesRegex(ValueError, "calculation chain"):
            package.inspect(self.source, SHEET, [self.lot])
        self.assertFalse(self.output.exists())

    def test_ignorable_namespace_prefixes_remain_declared_in_rewritten_xml(self):
        write_package(self.source, worksheet(self.source_rows(), ignorable=True))
        shared = f'<sst xmlns="{MAIN}"><si><t>New researched entry</t></si></sst>'.encode()
        write_package(self.authored, worksheet(self.authored_rows()), shared_strings=shared)
        plan = package.inspect(self.source, SHEET, [self.lot])
        package.preserve(self.source, self.authored, plan, self.output)
        with zipfile.ZipFile(self.output) as z:
            payload = z.read("xl/worksheets/sheet1.xml")
        from io import BytesIO
        declarations = dict(value for event, value in ET.iterparse(BytesIO(payload), events=("start-ns",)))
        root = ET.fromstring(payload)
        for prefix in root.get("{" + MC + "}Ignorable", "").split():
            self.assertIn(prefix, declarations)

    def test_formula_translation_preserves_functions_strings_and_other_sheet_references(self):
        formula = 'LOG10(J7)+SUM(J5:J6)+\'Other\'!J8+"J8"'
        shifted = package.shift_formula(formula, SHEET, SHEET, 7, 1)
        self.assertEqual(shifted, 'LOG10(J8)+SUM(J5:J7)+\'Other\'!J8+"J8"')

    def test_shared_formula_translation_does_not_change_sheet_labels(self):
        translated = package.translated_shared("SUM('Q1'!A5)+LOG10($B5)", "J8", "K8")
        self.assertEqual(translated, "SUM('Q1'!B5)+LOG10($B5)")

    def test_native_shared_formula_group_and_cached_results_survive_insertion(self):
        rows = self.source_rows(totals=False)[:-1]
        group = ('<c xmlns="' + MAIN + '" r="J8" s="4"><f t="shared" si="0" ref="J8:K8">SUM(J5:J6)</f><v>30</v></c>'
                 '<c xmlns="' + MAIN + '" r="K8" s="4"><f t="shared" si="0"/><v>9</v></c>')
        rows.extend([(8, group), (10, text_cell("A10", "Footer preserved", 2))])
        write_package(self.source, worksheet(rows))
        authored_rows = self.authored_rows()
        authored_rows[4] = (9, number_cell("J9", 37, 99, "SUM(J5:J7)") + number_cell("K9", 12, 99, "SUM(K5:K7)"))
        shared = f'<sst xmlns="{MAIN}"><si><t>New researched entry</t></si></sst>'.encode()
        write_package(self.authored, worksheet(authored_rows), shared_strings=shared)
        plan = package.inspect(self.source, SHEET, [self.lot])
        package.preserve(self.source, self.authored, plan, self.output)
        with zipfile.ZipFile(self.output) as z:
            root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        cells = {c.get("r"): c for c in root.iter(package.TAG + "c")}
        base = cells["J9"].find(package.TAG + "f")
        follower = cells["K9"].find(package.TAG + "f")
        self.assertEqual(base.attrib, {"t": "shared", "si": "0", "ref": "J9:K9"})
        self.assertEqual(base.text, "SUM(J5:J7)")
        self.assertEqual(follower.attrib, {"t": "shared", "si": "0"})
        self.assertIsNone(follower.text)
        self.assertEqual(package.cell_value(cells["K9"], []), 12)
