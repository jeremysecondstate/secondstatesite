import datetime as dt
import os
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook


PARTNERS = ("Alex", "Jeremy", "Oliver")
PARTNER_LOOKUP = {name.lower(): name for name in PARTNERS}


def _clean(value):
    return str(value or "").strip()


def _norm(value):
    return _clean(value).lower().replace("\n", " ").replace("  ", " ")


def _money(value):
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = _clean(value).replace("$", "").replace(",", "").replace("(", "-").replace(")", "")
    if not text or text.lower() in {"amount", "amount ($)", "low", "high", "total"}:
        return Decimal("0")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money_float(value):
    return float(value.quantize(Decimal("0.01")))


def _money_display(value):
    return f"${_money_float(value):,.2f}"


def _date_bucket(value):
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m")
    if isinstance(value, dt.date):
        return value.strftime("%Y-%m")
    text = _clean(value)
    if not text:
        return "Unknown"
    try:
        return dt.datetime.fromisoformat(text).strftime("%Y-%m")
    except ValueError:
        return text[:7] if len(text) >= 7 else text


def _find_contribution_header(ws):
    for row_index, row in enumerate(ws.iter_rows(values_only=True), start=1):
        normalized = [_norm(cell) for cell in row]
        if "partner" in normalized and "type" in normalized and any("amount" in cell for cell in normalized):
            return row_index, normalized
    return None, []


def _column_map(headers):
    mapping = {}
    for idx, header in enumerate(headers):
        if header == "date":
            mapping["date"] = idx
        elif header == "partner":
            mapping["partner"] = idx
        elif header == "type":
            mapping["type"] = idx
        elif "amount" in header:
            mapping["amount"] = idx
        elif header == "notes":
            mapping["notes"] = idx
    return mapping


def _parse_contributions(ws):
    header_row, headers = _find_contribution_header(ws)
    if not header_row:
        return []
    columns = _column_map(headers)
    rows = []
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        partner_raw = _clean(row[columns.get("partner", -1)] if columns.get("partner") is not None else "")
        type_raw = _clean(row[columns.get("type", -1)] if columns.get("type") is not None else "")
        if _norm(partner_raw) == "partner" or _norm(type_raw) == "type":
            continue
        partner = PARTNER_LOOKUP.get(partner_raw.lower())
        if not partner:
            continue
        amount = _money(row[columns["amount"]])
        if amount == 0 and not type_raw:
            continue
        rows.append(
            {
                "date": row[columns.get("date")] if columns.get("date") is not None else None,
                "month": _date_bucket(row[columns.get("date")] if columns.get("date") is not None else None),
                "partner": partner,
                "type": type_raw or "Uncategorized",
                "amount": amount,
                "notes": _clean(row[columns.get("notes")] if columns.get("notes") is not None else ""),
            }
        )
    return rows


def _parse_liquidation_summary(ws):
    for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        normalized = [_norm(cell) for cell in row]
        for col_idx, cell in enumerate(normalized):
            if cell == "partner" and any("deal capital" in item for item in normalized[col_idx : col_idx + 5]):
                header_map = {}
                for offset, header in enumerate(normalized[col_idx : col_idx + 5]):
                    absolute = col_idx + offset
                    if header == "partner":
                        header_map["partner"] = absolute
                    elif "deal capital" in header:
                        header_map["deal_capital"] = absolute
                    elif "profit" in header or "retained" in header:
                        header_map["retained_earnings"] = absolute
                    elif "liquidation" in header or "payout" in header:
                        header_map["liquidation_payout"] = absolute
                summary = {}
                for data_row in ws.iter_rows(min_row=row_idx + 1, max_row=row_idx + 12, values_only=True):
                    partner = PARTNER_LOOKUP.get(_clean(data_row[header_map.get("partner", -1)]).lower())
                    if not partner:
                        continue
                    summary[partner] = {
                        "deal_capital": _money(data_row[header_map.get("deal_capital")]),
                        "retained_earnings": _money(data_row[header_map.get("retained_earnings")]),
                        "liquidation_payout": _money(data_row[header_map.get("liquidation_payout")]),
                    }
                if summary:
                    return summary
    return {}


def build_dashboard(workbook_file=None, workbook_path=None):
    source_name = "SUPREME workbook"
    if workbook_file:
        source_name = getattr(workbook_file, "name", source_name)
        wb = load_workbook(workbook_file, data_only=True, read_only=True)
    else:
        workbook_path = workbook_path or os.environ.get("SUPREME_WORKBOOK_PATH")
        if not workbook_path:
            raise FileNotFoundError("Upload SUPREME.xlsx or set SUPREME_WORKBOOK_PATH on the server.")
        source_name = Path(workbook_path).name
        wb = load_workbook(workbook_path, data_only=True, read_only=True)

    sheet_name = "Contributions" if "Contributions" in wb.sheetnames else wb.sheetnames[0]
    ws = wb[sheet_name]
    rows = _parse_contributions(ws)
    liquidation_summary = _parse_liquidation_summary(ws)

    totals_by_partner = defaultdict(Decimal)
    deal_capital_by_partner = defaultdict(Decimal)
    expenses_by_partner = defaultdict(Decimal)
    totals_by_type = defaultdict(Decimal)
    monthly_totals = defaultdict(Decimal)

    for row in rows:
        amount = row["amount"]
        partner = row["partner"]
        type_label = row["type"] or "Uncategorized"
        type_lower = type_label.lower()
        totals_by_partner[partner] += amount
        totals_by_type[type_label] += amount
        monthly_totals[row["month"]] += amount
        if "deal capital" in type_lower:
            deal_capital_by_partner[partner] += amount
        elif "expense" in type_lower or "infrastructure" in type_lower:
            expenses_by_partner[partner] += amount

    partner_cards = []
    for partner in PARTNERS:
        summary = liquidation_summary.get(partner, {})
        deal_capital = summary.get("deal_capital", deal_capital_by_partner[partner])
        retained = summary.get("retained_earnings", Decimal("0"))
        payout = summary.get("liquidation_payout", deal_capital + retained)
        partner_cards.append(
            {
                "partner": partner,
                "deal_capital": _money_display(deal_capital),
                "deal_capital_value": _money_float(deal_capital),
                "retained_earnings": _money_display(retained),
                "retained_earnings_value": _money_float(retained),
                "liquidation_payout": _money_display(payout),
                "liquidation_payout_value": _money_float(payout),
                "total_contributions": _money_display(totals_by_partner[partner]),
                "expense_total": _money_display(expenses_by_partner[partner]),
            }
        )

    type_rows = [
        {"type": label, "amount": _money_display(amount), "value": _money_float(amount)}
        for label, amount in sorted(totals_by_type.items(), key=lambda item: abs(item[1]), reverse=True)
    ]
    month_rows = [
        {"month": month, "amount": _money_display(amount), "value": _money_float(amount)}
        for month, amount in sorted(monthly_totals.items())
    ]

    chart_data = {
        "partners": [card["partner"] for card in partner_cards],
        "dealCapital": [card["deal_capital_value"] for card in partner_cards],
        "retainedEarnings": [card["retained_earnings_value"] for card in partner_cards],
        "liquidationPayout": [card["liquidation_payout_value"] for card in partner_cards],
        "types": [row["type"] for row in type_rows],
        "typeAmounts": [row["value"] for row in type_rows],
        "months": [row["month"] for row in month_rows],
        "monthAmounts": [row["value"] for row in month_rows],
    }

    total_deal_capital = sum(Decimal(str(card["deal_capital_value"])) for card in partner_cards)
    total_retained = sum(Decimal(str(card["retained_earnings_value"])) for card in partner_cards)
    total_payout = sum(Decimal(str(card["liquidation_payout_value"])) for card in partner_cards)

    return {
        "source_name": source_name,
        "sheet_name": sheet_name,
        "row_count": len(rows),
        "partner_cards": partner_cards,
        "type_rows": type_rows[:12],
        "month_rows": month_rows[-18:],
        "totals": {
            "deal_capital": _money_display(total_deal_capital),
            "retained_earnings": _money_display(total_retained),
            "liquidation_payout": _money_display(total_payout),
            "transactions": len(rows),
        },
        "chart_data": chart_data,
    }
