"""Preserve an XLSX package around cells authored by inventory_workbook.mjs.

Only standard-library OOXML packaging is used here. Cell content and calculation
are authored by Artifact Tool. Unrelated ZIP members are copied byte-for-byte.
"""
import argparse
import copy
import hashlib
import json
import os
import posixpath
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import zipfile
from xml.etree import ElementTree as ET

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
TAG = "{" + NS["s"] + "}"
REF = re.compile(r"(?<![A-Za-z0-9_])(?P<col>\$?[A-Z]{1,3})(?P<row>\$?\d+)(?![A-Za-z0-9_]|\s*\()")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sheets(z):
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.attrib["Id"]: r.attrib["Target"].lstrip("/") for r in rels}
    book = ET.fromstring(z.read("xl/workbook.xml"))
    result = {}
    for s in book.find(TAG + "sheets"):
        target = targets[s.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
        result[s.attrib["name"]] = target if target.startswith("xl/") else "xl/" + target
    return result


def strings(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    return ["".join(x.itertext()) for x in ET.fromstring(z.read("xl/sharedStrings.xml"))]


def serialize(root, original):
    # Keep namespace prefixes/declarations, including those used by compatibility
    # attribute values rather than element names.
    text = original.decode("utf-8")
    opening = re.search(r'<(?![?!])[^>]+>', text)
    if opening is None:
        raise ValueError('XML has no root opening tag.')
    declarations = re.findall(r'xmlns(?::([\w]+))?="([^"]+)"', opening.group(0))
    for prefix, uri in declarations:
        ET.register_namespace(prefix, uri)
    rendered = ET.tostring(root, encoding="unicode")
    first_end = rendered.index('>')
    start = rendered[:first_end]
    missing = ''.join(f' xmlns{":"+prefix if prefix else ""}="{uri}"' for prefix, uri in declarations if f'xmlns{":"+prefix if prefix else ""}=' not in start)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + start + missing + rendered[first_end:]).encode('utf-8')


def cell_value(c, ss):
    v = c.find(TAG + "v")
    if c.get("t") == "s":
        return ss[int(v.text)] if v is not None else None
    if c.get("t") == "inlineStr":
        return "".join(c.find(TAG + "is").itertext())
    if v is None:
        return None
    if c.get("t") in ("str", "e"):
        return v.text
    try:
        return float(v.text)
    except (ValueError, TypeError):
        return v.text


def shift_refs(value, at, count):
    def sub(m):
        row = m.group("row")
        n = int(row.lstrip("$"))
        return m.group("col") + ("$" if row.startswith("$") else "") + str(n + count if n >= at else n)
    return REF.sub(sub, value)


def shift_formula(formula, sheet_name, target_name, at, count):
    # Strings in formulas are preserved. INDIRECT references are not rewritten.
    chunks = re.split(r'("(?:[^"]|"")*")', formula)
    quoted_target = "'" + target_name.replace("'", "''") + "'!"
    def inventory_refs(value):
        value = shift_refs(value, at, count)
        # Extend an inventory range whose endpoint was exactly the final item,
        # including workbooks without blank staging rows beneath the inventory.
        return re.sub(rf"(\$?[A-Z]{{1,3}}\$?5:\$?[A-Z]{{1,3}}\$?){at-1}(?!\d)", lambda m: m.group(1) + str(at - 1 + count), value)
    for i in range(0, len(chunks), 2):
        if sheet_name == target_name:
            # Protect explicit references to other sheets while shifting local refs.
            pattern = r"((?:'[^']*(?:''[^']*)*'|[A-Za-z_][\w.]*)!)(\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)"
            protected = []
            def protect(m):
                val = m.group(0)
                if m.group(1) == quoted_target:
                    val = m.group(1) + inventory_refs(m.group(2))
                protected.append(val)
                return f"__SHEETREF_{len(protected)-1}__"
            local = re.sub(pattern, protect, chunks[i])
            local = inventory_refs(local)
            for j, val in enumerate(protected):
                local = local.replace(f"__SHEETREF_{j}__", val)
            chunks[i] = local
        else:
            chunks[i] = re.sub(re.escape(quoted_target) + r"(\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)", lambda m: quoted_target + inventory_refs(m.group(1)), chunks[i])
    return "".join(chunks)


def translated_shared(formula, origin, destination):
    def position(ref):
        col, row = re.fullmatch(r"([A-Z]+)(\d+)", ref).groups()
        n = 0
        for char in col:
            n = n * 26 + ord(char) - 64
        return n, int(row)
    oc, orow = position(origin)
    dc, drow = position(destination)
    def sub(m):
        col, row = m.group("col"), m.group("row")
        if not col.startswith("$"):
            n = 0
            for char in col:
                n = n * 26 + ord(char) - 64
            n += dc - oc
            col = ""
            while n:
                n, remain = divmod(n - 1, 26)
                col = chr(remain + 65) + col
        if not row.startswith("$"):
            row = str(int(row) + drow - orow)
        return col + row
    chunks = re.split(r'("(?:[^"]|"")*")', formula)
    for i in range(0, len(chunks), 2):
        # A sheet called Q1 is a label, not a cell reference.
        labels = []
        def label(m):
            labels.append(m.group(0))
            return f"[LABEL_{len(labels)-1}]"
        part = re.sub(r"(?:'(?:[^']|'')*'|[A-Za-z_][\w.]*)!", label, chunks[i])
        part = REF.sub(sub, part)
        for j, value in enumerate(labels):
            part = part.replace(f"[LABEL_{j}]", value)
        chunks[i] = part
    return "".join(chunks)


def inspect(source, sheet, records):
    raw = Path(source).read_bytes()
    with zipfile.ZipFile(source) as z:
        names, ss = sheets(z), strings(z)
        root = ET.fromstring(z.read(names[sheet]))
        rows = root.find(TAG + "sheetData")
        cells = {c.get("r"): c for row in rows for c in row}
        if cell_value(cells.get("A4"), ss) != "#" or cell_value(cells.get("AC4"), ss) != "DETAILS/LISTING INFO":
            raise ValueError("Workbook inventory headers differ from the supported layout.")
        last = 4
        ids = []
        while isinstance(cell_value(cells.get(f"A{last+1}", ET.Element('c')), ss), (int, float)):
            last += 1
            ids.append(cell_value(cells[f"A{last}"], ss))
        if last == 4:
            raise ValueError("No inventory template row found.")
        entries = []
        skipped = []
        seen_urls = set()
        seen_keys = set()
        def canonical(url):
            parsed = urlsplit(url)
            return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/'), urlencode(sorted(parse_qsl(parsed.query))), ''))
        for item in records:
            url = canonical(item["lot_url"])
            # The stable marker binds house, exact date and lot as an additional key.
            key = f"Inventory key: {item['auction_house']} | {item['sale_date']} | {item['lot_number']}"
            matching = []
            for r in range(5, last + 1):
                texts = [str(cell_value(cells.get(f"{col}{r}", ET.Element('c')), ss) or "") for col in ("M", "AC")]
                if any(key in [line.strip() for line in t.splitlines()] or url in [canonical(found) for found in re.findall(r'https?://[^\s<>]+', t)] for t in texts):
                    matching.append(r)
            if url in seen_urls or key in seen_keys:
                raise ValueError("Duplicate lot identities in input.")
            seen_urls.add(url)
            seen_keys.add(key)
            if len(matching) > 1:
                raise ValueError("Existing workbook contains duplicate inventory keys.")
            if matching:
                skipped.append({"lot_url": item["lot_url"], "row": matching[0]})
            else:
                entries.append(item)
        at, count = last + 1, len(entries)
        if count:
            for unsupported in ('tableParts','conditionalFormatting','dataValidations'):
                if root.find(TAG + unsupported) is not None:
                    raise ValueError(f'Inventory {unsupported} needs explicit row-insertion support; no workbook was changed.')
            if 'xl/calcChain.xml' in z.namelist():
                raise ValueError('This workbook has a calculation chain requiring explicit insertion support.')
            book = ET.fromstring(z.read('xl/workbook.xml'))
            for name in book.findall('s:definedNames/s:definedName', NS):
                value = name.text or ''
                if sheet in value and shift_formula(value, '', sheet, at, count) != value:
                    raise ValueError('An affected named range or print area requires explicit insertion support.')
            rel_member = posixpath.join(posixpath.dirname(names[sheet]), '_rels', posixpath.basename(names[sheet])+'.rels')
            if rel_member in z.namelist():
                for relation in ET.fromstring(z.read(rel_member)):
                    if relation.get('Type','').endswith('/drawing'):
                        drawing_member = posixpath.normpath(posixpath.join(posixpath.dirname(names[sheet]),relation.get('Target')))
                        drawing = ET.fromstring(z.read(drawing_member))
                        if any(int(element.text) >= at - 1 for element in drawing.iter() if element.tag.endswith('}row') and element.text):
                            raise ValueError('A drawing anchored at or below the insertion point needs explicit insertion support.')
        formulas = []
        for name, member in names.items():
            sroot = ET.fromstring(z.read(member))
            shared = {f.get("si"): (cell.get("r"), f.text) for cell in sroot.iter(TAG + "c") for f in [cell.find(TAG + "f")] if f is not None and f.get("t") == "shared" and f.text}
            for cell in sroot.iter(TAG + "c"):
                f = cell.find(TAG + "f")
                if f is None:
                    continue
                formula = f.text
                if f.get("t") == "shared" and not formula:
                    origin, base = shared[f.get("si")]
                    formula = translated_shared(base, origin, cell.get("r"))
                if not formula:
                    continue
                changed = shift_formula(formula, name, sheet, at, count)
                address = shift_refs(cell.get("r"), at, count) if name == sheet else cell.get("r")
                if changed != formula or address != cell.get("r"):
                    if f.get("t") not in (None, "shared"):
                        raise ValueError("An affected shared/array formula needs manual handling.")
                    formulas.append({"sheet": name, "address": address, "formula": "=" + changed})
        merges = [m.get("ref") for m in root.findall("s:mergeCells/s:mergeCell", NS)]
        for m in merges:
            nums = [int(x) for x in re.findall(r"\d+", m)]
            if min(nums) < at <= max(nums):
                raise ValueError("A merged range crosses the insertion point.")
        return {"sha256": sha(raw), "sheet": sheet, "insert_at": at, "count": count,
                "last_row": max(int(r.get("r")) for r in rows), "last_inventory_number": max(ids),
                "merges": merges, "formulas": formulas, "lots": entries, "skipped": skipped,
                "row_heights": {r.get("r"): r.get("ht") for r in rows if r.get("ht")}}


def inline_cell(cell, ss):
    cell = copy.deepcopy(cell)
    if cell.get("t") == "s":
        value = cell_value(cell, ss)
        cell.remove(cell.find(TAG + "v"))
        cell.set("t", "inlineStr")
        istr = ET.SubElement(cell, TAG + "is")
        text = ET.SubElement(istr, TAG + "t")
        text.text = value
    return cell


def preserve(source, authored, plan, output):
    if sha(Path(source).read_bytes()) != plan["sha256"]:
        raise ValueError("Workbook changed during preparation; rerun against the current file.")
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(authored) as new:
        old_names, new_names, new_ss = sheets(src), sheets(new), strings(new)
        edited = {}
        target = plan["sheet"]
        at, count = plan["insert_at"], plan["count"]
        root = ET.fromstring(src.read(old_names[target]))
        data = root.find(TAG + "sheetData")
        template = next(r for r in data if int(r.get("r")) == at - 1)
        template_styles = {re.sub(r"\d+", "", c.get("r")): c.get("s") for c in template}
        # Structural metadata follows the inserted rows without touching columns,
        # fonts, styles, validations, print setup or any unrelated archive member.
        for element in root.iter():
            for attr in ("ref", "sqref"):
                if attr in element.attrib:
                    element.set(attr, shift_refs(element.get(attr), at, count))
        for row in data:
            r = int(row.get("r"))
            if r >= at:
                row.set("r", str(r + count))
                for cell in row:
                    cell.set("r", shift_refs(cell.get("r"), at, count))
        new_root = ET.fromstring(new.read(new_names[target]))
        new_data = new_root.find(TAG + "sheetData")
        for row in new_data:
            r = int(row.get("r"))
            if at <= r < at + count:
                inserted = copy.deepcopy(row)
                for idx, cell in enumerate(list(inserted)):
                    converted = inline_cell(cell, new_ss)
                    col = re.sub(r"\d+", "", converted.get("r"))
                    style = template_styles.get(col)
                    if style is None:
                        converted.attrib.pop("s", None)
                    else:
                        converted.set("s", style)
                    inserted.remove(cell)
                    inserted.insert(idx, converted)
                data.append(inserted)
        data[:] = sorted(data, key=lambda r: int(r.get("r")))
        edited[target] = root
        affected_sheets = {f["sheet"] for f in plan["formulas"]}
        for name in affected_sheets:
            if name not in edited:
                edited[name] = ET.fromstring(src.read(old_names[name]))
            authored_root = ET.fromstring(new.read(new_names[name]))
            authored_cells = {c.get("r"): c for c in authored_root.iter(TAG + "c")}
            original_cells = {c.get("r"): c for c in edited[name].iter(TAG + "c")}
            for f in (f for f in plan["formulas"] if f["sheet"] == name):
                dest, cell = original_cells[f["address"]], authored_cells[f["address"]]
                original_formula = dest.find(TAG + "f")
                for old in list(dest):
                    if old.tag in (TAG + "v", TAG + "is"):
                        dest.remove(old)
                if original_formula is not None and original_formula.text:
                    original_formula.text = f["formula"].lstrip("=")
                for child in cell:
                    if child.tag == TAG + "v":
                        dest.append(copy.deepcopy(child))
                if cell.get("t"):
                    dest.set("t", cell.get("t"))
                else:
                    dest.attrib.pop("t", None)
        replacements = {old_names[name]: serialize(root, src.read(old_names[name])) for name, root in edited.items()}
        relationship_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        document_relationship_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        rel_member = str(Path(old_names[target]).parent / '_rels' / (Path(old_names[target]).name + '.rels')).replace('\\','/')
        if rel_member not in src.namelist():
            raise ValueError('Supported workbook requires an existing inventory relationship part.')
        rel_root = ET.fromstring(src.read(rel_member))
        next_id = max([int(re.sub(r'\D','',r.get('Id'))) for r in rel_root] or [0]) + 1
        links = edited[target].find(TAG + 'hyperlinks')
        if links is None:
            links = ET.Element(TAG + 'hyperlinks')
            # Hyperlinks precede printing/drawing elements in SpreadsheetML.
            later = {'printOptions','pageMargins','pageSetup','headerFooter','rowBreaks','colBreaks','customProperties','cellWatches','ignoredErrors','smartTags','drawing','legacyDrawing','legacyDrawingHF','picture','oleObjects','controls','webPublishItems','tableParts','extLst'}
            position = next((i for i,e in enumerate(edited[target]) if e.tag.split('}')[-1] in later),len(edited[target]))
            edited[target].insert(position,links)
        for i, lot in enumerate(plan['lots']):
            for col, url in [('B',lot.get('image_url')),('O',lot['lot_url'])]:
                if not url:
                    continue
                if not url.startswith('https://'):
                    raise ValueError('Hyperlink URL must be HTTPS.')
                identifier = f'rId{next_id}'
                next_id += 1
                ET.SubElement(rel_root,'{'+relationship_ns+'}Relationship',{'Id':identifier,'Type':document_relationship_ns+'/hyperlink','Target':url,'TargetMode':'External'})
                ET.SubElement(links,TAG+'hyperlink',{'ref':f'{col}{at+i}','{'+document_relationship_ns+'}id':identifier})
        replacements[old_names[target]]=serialize(edited[target],src.read(old_names[target]))
        replacements[rel_member]=serialize(rel_root,src.read(rel_member))
        # Recalculation on Excel open updates dependents whose unchanged formulas
        # have cached results in the original package.
        book = ET.fromstring(src.read("xl/workbook.xml"))
        calc = book.find(TAG + "calcPr")
        if calc is None:
            calc = ET.SubElement(book, TAG + "calcPr")
        calc.set("fullCalcOnLoad", "1")
        calc.set("forceFullCalc", "1")
        replacements["xl/workbook.xml"] = serialize(book, src.read("xl/workbook.xml"))
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as out:
            for item in src.infolist():
                out.writestr(copy.copy(item), replacements.get(item.filename, src.read(item.filename)))
        with zipfile.ZipFile(output) as check:
            if set(check.namelist()) != set(src.namelist()):
                raise AssertionError("XLSX package members changed.")
            if any(check.read(n) != src.read(n) for n in src.namelist() if n not in replacements):
                raise AssertionError("Unrelated XLSX content changed.")
        return {"changed_members": sorted(replacements), "sha256": sha(Path(output).read_bytes())}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("inspect", "preserve"))
    p.add_argument("--source", required=True)
    p.add_argument("--records")
    p.add_argument("--sheet", default="Inventory for Fall 2026")
    p.add_argument("--plan", required=True)
    p.add_argument("--authored")
    p.add_argument("--output")
    args = p.parse_args()
    if args.mode == "inspect":
        records = json.loads(Path(args.records).read_text(encoding="utf-8-sig"))
        result = inspect(args.source, records.get("sheet", args.sheet), records["lots"])
        Path(args.plan).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"count": result["count"], "insert_at": result["insert_at"], "skipped": result["skipped"]}))
    else:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        print(json.dumps(preserve(args.source, args.authored, plan, args.output)))


if __name__ == "__main__":
    main()
