from __future__ import annotations

import base64
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate
from html import escape
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

from .models import AuctionWatchLot


GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
REQUIRED_SENDER = "jeremy@secondstate.art"
RECIPIENT_SPECS = (
    ("jeremy", "Jeremy", "AUCTION_EMAIL_RECIPIENT_JEREMY", "jeremy@secondstate.art"),
    ("oliver", "Oliver", "AUCTION_EMAIL_RECIPIENT_OLIVER", "oliver@secondstate.art"),
    ("alex", "Alex", "AUCTION_EMAIL_RECIPIENT_ALEX", "alex@secondstate.art"),
)


class AuctionEmailConfigurationError(ValueError):
    pass


class AuctionEmailDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuctionEmailRecipient:
    key: str
    name: str
    address: str


@dataclass(frozen=True, slots=True)
class ComposedAuctionEmail:
    subject: str
    text_body: str
    html_body: str
    lot_snapshots: dict[int, dict]
    groups: list[dict]
    lot_count: int
    auction_count: int
    date_range: str


def _setting_text(name: str) -> str:
    return str(getattr(settings, name, "") or "").strip()


def _is_secondstate_address(value: str) -> bool:
    try:
        validate_email(value)
    except ValidationError:
        return False
    _local, separator, domain = value.rpartition("@")
    return bool(separator and domain.casefold() == "secondstate.art")


def recipient_choices() -> list[dict]:
    choices = []
    for key, name, setting_name, expected_address in RECIPIENT_SPECS:
        configured_address = _setting_text(setting_name)
        choices.append(
            {
                "key": key,
                "name": name,
                "address": configured_address or expected_address,
                "configured": bool(configured_address and _is_secondstate_address(configured_address)),
            }
        )
    return choices


def configuration_warnings() -> list[str]:
    warnings = []
    if not bool(getattr(settings, "AUCTION_EMAIL_SENDING_ENABLED", False)):
        warnings.append("Gmail delivery is disabled.")

    sender = _setting_text("AUCTION_EMAIL_SENDER")
    if sender.casefold() != REQUIRED_SENDER or not _is_secondstate_address(sender):
        warnings.append(f"AUCTION_EMAIL_SENDER must be {REQUIRED_SENDER}.")

    for _key, name, setting_name, _expected_address in RECIPIENT_SPECS:
        address = _setting_text(setting_name)
        if not address:
            warnings.append(f"{name}'s recipient address is not configured.")
        elif not _is_secondstate_address(address):
            warnings.append(f"{name}'s recipient address must use @secondstate.art.")

    for setting_name, label in (
        ("GOOGLE_GMAIL_CLIENT_ID", "Google OAuth client ID"),
        ("GOOGLE_GMAIL_CLIENT_SECRET", "Google OAuth client secret"),
        ("GOOGLE_GMAIL_REFRESH_TOKEN", "Google OAuth refresh token"),
    ):
        if not _setting_text(setting_name):
            warnings.append(f"{label} is not configured.")
    return warnings


def resolve_recipient_keys(keys: Iterable[str]) -> list[AuctionEmailRecipient]:
    submitted = [str(key or "").strip().casefold() for key in keys]
    if not submitted:
        raise AuctionEmailConfigurationError("Choose at least one recipient.")
    allowed = {key for key, _name, _setting_name, _expected_address in RECIPIENT_SPECS}
    if any(not key or key not in allowed for key in submitted):
        raise AuctionEmailConfigurationError("Choose recipients only from Jeremy, Oliver, and Alex.")

    selected = set(submitted)
    recipients = []
    for key, name, setting_name, _expected_address in RECIPIENT_SPECS:
        if key not in selected:
            continue
        address = _setting_text(setting_name)
        if not address:
            raise AuctionEmailConfigurationError(f"{name}'s recipient address is not configured.")
        if not _is_secondstate_address(address):
            raise AuctionEmailConfigurationError(f"{name}'s recipient address must use @secondstate.art.")
        recipients.append(AuctionEmailRecipient(key=key, name=name, address=address))
    return recipients


def validate_sending_configuration(keys: Iterable[str]) -> list[AuctionEmailRecipient]:
    if not bool(getattr(settings, "AUCTION_EMAIL_SENDING_ENABLED", False)):
        raise AuctionEmailConfigurationError("Gmail delivery is disabled.")

    sender = _setting_text("AUCTION_EMAIL_SENDER")
    if sender.casefold() != REQUIRED_SENDER or not _is_secondstate_address(sender):
        raise AuctionEmailConfigurationError(f"AUCTION_EMAIL_SENDER must be {REQUIRED_SENDER}.")

    for setting_name, label in (
        ("GOOGLE_GMAIL_CLIENT_ID", "Google OAuth client ID"),
        ("GOOGLE_GMAIL_CLIENT_SECRET", "Google OAuth client secret"),
        ("GOOGLE_GMAIL_REFRESH_TOKEN", "Google OAuth refresh token"),
    ):
        if not _setting_text(setting_name):
            raise AuctionEmailConfigurationError(f"{label} is not configured.")
    return resolve_recipient_keys(keys)


def _money(value: Decimal | int | float | None) -> str:
    if value is None:
        return ""
    value = Decimal(str(value))
    if value == value.to_integral_value():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _estimate_label(lot: AuctionWatchLot) -> str:
    if lot.estimate_low is None and lot.estimate_high is None:
        return ""
    currency = (lot.currency or "").upper()
    prefix = {"USD": "$", "GBP": "£", "EUR": "€"}.get(currency, f"{currency} " if currency else "")
    if lot.estimate_low is not None and lot.estimate_high is not None:
        amount = f"{_money(lot.estimate_low)}–{_money(lot.estimate_high)}"
    else:
        amount = _money(lot.estimate_low if lot.estimate_low is not None else lot.estimate_high)
    return f"{prefix}{amount} estimate"


def _day(value: date) -> str:
    return str(value.day)


def _subject_date_range(dates: Sequence[date]) -> str:
    if not dates:
        return "Dates pending"
    first, last = dates[0], dates[-1]
    if first == last:
        return f"{first.strftime('%b')} {_day(first)}"
    if first.year == last.year and first.month == last.month:
        return f"{first.strftime('%b')} {_day(first)}–{_day(last)}"
    if first.year == last.year:
        return f"{first.strftime('%b')} {_day(first)}–{last.strftime('%b')} {_day(last)}"
    return (
        f"{first.strftime('%b')} {_day(first)}, {first.year}–"
        f"{last.strftime('%b')} {_day(last)}, {last.year}"
    )


def _artist_label(lot: AuctionWatchLot) -> str:
    return lot.artist_watchlist_name or lot.artist or "Unknown artist"


def _lot_sort_key(lot: AuctionWatchLot) -> tuple:
    timestamp = lot.event_at.timestamp() if lot.event_at else float("inf")
    return (
        timestamp,
        (lot.auction_house or lot.source or "Auction").casefold(),
        _artist_label(lot).casefold(),
        (lot.lot_number or lot.source_lot_id or str(lot.pk)).casefold(),
        lot.pk,
    )


def _sale_time_labels(lot: AuctionWatchLot, zone: ZoneInfo) -> tuple[date | None, str, str]:
    if not lot.event_at:
        return None, "Date pending", "Time TBA"
    local = timezone.localtime(lot.event_at, zone)
    date_label = f"{local.strftime('%A, %B')} {local.day}, {local.year}"
    if lot.is_all_day:
        return local.date(), date_label, "Time TBA"
    time_label = f"{local.strftime('%I').lstrip('0')}:{local.strftime('%M %p %Z')}"
    return local.date(), date_label, time_label


def _snapshot_lot(lot: AuctionWatchLot, zone: ZoneInfo) -> dict:
    sale_date, sale_date_label, sale_time_label = _sale_time_labels(lot, zone)
    return {
        "lot_id": lot.pk,
        "source": lot.source,
        "source_lot_id": lot.source_lot_id,
        "artist": _artist_label(lot),
        "title": lot.title or "Untitled lot",
        "auction_house": lot.auction_house or lot.source or "Auction",
        "sale_title": lot.sale_title,
        "sale_date": sale_date.isoformat() if sale_date else "",
        "sale_date_label": sale_date_label,
        "sale_time_label": sale_time_label,
        "lot_number": lot.lot_number or lot.source_lot_id,
        "estimate": _estimate_label(lot),
        "artprice_url": lot.artprice_url,
        "lot_url": lot.lot_url or lot.sale_url,
        "sale_url": lot.sale_url,
    }


def compose_auction_email(lots: Iterable[AuctionWatchLot]) -> ComposedAuctionEmail:
    zone = ZoneInfo(settings.CALENDAR_TIME_ZONE)
    ordered_lots = sorted(list(lots), key=_lot_sort_key)
    if not ordered_lots:
        raise ValueError("The Email Tray is empty.")

    snapshots = [_snapshot_lot(lot, zone) for lot in ordered_lots]
    dated = sorted({date.fromisoformat(item["sale_date"]) for item in snapshots if item["sale_date"]})
    date_range = _subject_date_range(dated)
    lot_count = len(snapshots)
    auction_keys = {
        (
            item["sale_date"],
            item["auction_house"].casefold(),
            item["sale_title"].casefold(),
            item["sale_url"],
            item["sale_time_label"],
        )
        for item in snapshots
    }
    auction_count = len(auction_keys)
    subject = f"SecondState — {lot_count} selected auction lot{'s' if lot_count != 1 else ''} · {date_range}"

    grouped: OrderedDict[str, dict] = OrderedDict()
    for snapshot in snapshots:
        date_key = snapshot["sale_date"] or "pending"
        date_group = grouped.setdefault(
            date_key,
            {"date_label": snapshot["sale_date_label"], "houses": OrderedDict()},
        )
        house = snapshot["auction_house"]
        date_group["houses"].setdefault(house, []).append(snapshot)
    groups = [
        {
            "date_label": group["date_label"],
            "houses": [{"name": name, "lots": house_lots} for name, house_lots in group["houses"].items()],
        }
        for group in grouped.values()
    ]

    calendar_url = f"{str(settings.SECONDSTATE_PUBLIC_URL).rstrip('/')}/calendar/"
    plural_auctions = "auction" if auction_count == 1 else "auctions"
    text_lines = [
        "SECONDSTATE",
        "",
        f"{lot_count} selected auction lot{'s' if lot_count != 1 else ''}",
        f"{auction_count} {plural_auctions} · {date_range}",
        f"Auction Calendar: {calendar_url}",
    ]
    html_parts = [
        '<!doctype html><html><body style="margin:0;background:#f2efe8;color:#181818;">',
        '<div style="display:none;max-height:0;overflow:hidden;">'
        + escape(f"{lot_count} selected auction lots from {date_range}")
        + "</div>",
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="border-collapse:collapse;background:#f2efe8;"><tr><td align="center" style="padding:28px 14px;">',
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="max-width:680px;border-collapse:collapse;background:#ffffff;border:1px solid #ddd5c7;">',
        '<tr><td style="padding:28px 32px;background:#111416;color:#ffffff;border-bottom:3px solid #d9b878;">',
        '<div style="font:700 11px Arial,sans-serif;letter-spacing:2px;text-transform:uppercase;color:#d9b878;">SecondState</div>',
        '<h1 style="margin:8px 0 5px;font:500 30px Georgia,serif;">'
        + escape(f"{lot_count} selected auction lot{'s' if lot_count != 1 else ''}")
        + "</h1>",
        '<p style="margin:0;font:14px Arial,sans-serif;color:#c9c9c9;">'
        + escape(f"{auction_count} {plural_auctions} · {date_range}")
        + "</p></td></tr>",
        '<tr><td style="padding:28px 32px;">',
    ]

    for group in groups:
        text_lines.extend(["", group["date_label"].upper()])
        html_parts.append(
            '<h2 style="margin:26px 0 12px;padding-bottom:8px;border-bottom:1px solid #d9b878;'
            'font:700 12px Arial,sans-serif;letter-spacing:1.4px;text-transform:uppercase;color:#76613a;">'
            + escape(group["date_label"])
            + "</h2>"
        )
        for house in group["houses"]:
            text_lines.extend(["", house["name"]])
            html_parts.append(
                '<h3 style="margin:18px 0 9px;font:600 19px Georgia,serif;color:#181818;">'
                + escape(house["name"])
                + "</h3>"
            )
            for item in house["lots"]:
                text_lines.extend(
                    [
                        f"{item['artist']} — {item['title']}",
                        f"Sale: {item['sale_title']}" if item["sale_title"] else "",
                        f"When: {item['sale_date_label']} at {item['sale_time_label']}",
                        f"Lot: {item['lot_number']}",
                        f"Estimate: {item['estimate']}" if item["estimate"] else "",
                        f"Artprice: {item['artprice_url']}",
                        f"Auction lot: {item['lot_url']}" if item["lot_url"] else "",
                        "",
                    ]
                )
                html_parts.extend(
                    [
                        '<div style="margin:0 0 14px;padding:16px 18px;border:1px solid #e2ddd4;background:#faf9f6;">',
                        '<div style="font:700 13px Arial,sans-serif;color:#181818;">'
                        + escape(item["artist"])
                        + "</div>",
                        '<div style="margin-top:3px;font:italic 17px Georgia,serif;color:#2f2f2f;">'
                        + escape(item["title"])
                        + "</div>",
                        '<div style="margin-top:9px;font:12px/1.6 Arial,sans-serif;color:#666;">',
                    ]
                )
                details = []
                if item["sale_title"]:
                    details.append(escape(item["sale_title"]))
                details.append(escape(f"{item['sale_date_label']} at {item['sale_time_label']}"))
                details.append(escape(f"Lot {item['lot_number']}"))
                if item["estimate"]:
                    details.append(escape(item["estimate"]))
                html_parts.append("<br>".join(details) + "</div>")
                html_parts.append(
                    '<div style="margin-top:11px;font:700 12px Arial,sans-serif;">'
                    '<a style="color:#765b26;text-decoration:underline;" href="'
                    + escape(item["artprice_url"], quote=True)
                    + '">Artprice link</a>'
                )
                if item["lot_url"]:
                    html_parts.append(
                        '<span style="color:#aaa;"> &nbsp;·&nbsp; </span><a style="color:#765b26;text-decoration:underline;" href="'
                        + escape(item["lot_url"], quote=True)
                        + '">Auction lot</a>'
                    )
                html_parts.append("</div></div>")

    compact_text_lines = []
    for line in text_lines:
        if line or not compact_text_lines or compact_text_lines[-1]:
            compact_text_lines.append(line)
    html_parts.extend(
        [
            '<p style="margin:28px 0 0;font:12px Arial,sans-serif;color:#777;">'
            '<a style="color:#765b26;" href="'
            + escape(calendar_url, quote=True)
            + '">Open the SecondState Auction Calendar</a></p>',
            "</td></tr></table></td></tr></table></body></html>",
        ]
    )
    lot_snapshots = {lot.pk: snapshot for lot, snapshot in zip(ordered_lots, snapshots, strict=True)}
    return ComposedAuctionEmail(
        subject=subject,
        text_body="\n".join(compact_text_lines).strip() + "\n",
        html_body="".join(html_parts),
        lot_snapshots=lot_snapshots,
        groups=groups,
        lot_count=lot_count,
        auction_count=auction_count,
        date_range=date_range,
    )


def build_mime_message(
    *,
    subject: str,
    text_body: str,
    html_body: str,
    recipients: Sequence[str],
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = _setting_text("AUCTION_EMAIL_SENDER")
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False, usegmt=True)
    message.set_content(text_body, subtype="plain", charset="utf-8")
    message.add_alternative(html_body, subtype="html", charset="utf-8")
    return message


def send_auction_email(
    *,
    subject: str,
    text_body: str,
    html_body: str,
    recipients: Sequence[str],
) -> str:
    """Send one multipart message through Gmail and return its provider message ID."""

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise AuctionEmailDeliveryError("Google Gmail client dependencies are not installed.") from exc

    credentials = Credentials(
        token=None,
        refresh_token=_setting_text("GOOGLE_GMAIL_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=_setting_text("GOOGLE_GMAIL_CLIENT_ID"),
        client_secret=_setting_text("GOOGLE_GMAIL_CLIENT_SECRET"),
        scopes=[GMAIL_SEND_SCOPE],
    )
    message = build_mime_message(
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        recipients=recipients,
    )
    encoded = base64.urlsafe_b64encode(message.as_bytes(policy=SMTP)).decode("ascii")
    try:
        response = (
            build("gmail", "v1", credentials=credentials, cache_discovery=False)
            .users()
            .messages()
            .send(userId="me", body={"raw": encoded})
            .execute()
        )
    except Exception as exc:  # Google client exceptions vary by transport/version.
        raise AuctionEmailDeliveryError(str(exc) or "The Gmail API request failed.") from exc
    message_id = str(response.get("id") or "").strip() if isinstance(response, dict) else ""
    if not message_id:
        raise AuctionEmailDeliveryError("Gmail accepted the request without returning a message ID.")
    return message_id


def sanitize_delivery_failure(exc: BaseException) -> str:
    summary = " ".join(str(exc).split())
    for setting_name in (
        "GOOGLE_GMAIL_CLIENT_ID",
        "GOOGLE_GMAIL_CLIENT_SECRET",
        "GOOGLE_GMAIL_REFRESH_TOKEN",
    ):
        secret = _setting_text(setting_name)
        if secret:
            summary = summary.replace(secret, "[redacted]")
    summary = re.sub(r"\b(?:ya29\.|1//)[A-Za-z0-9._-]+", "[redacted]", summary)
    summary = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~-]+", "Bearer [redacted]", summary)
    if not summary:
        summary = "The Gmail API request failed."
    return summary[:500]
