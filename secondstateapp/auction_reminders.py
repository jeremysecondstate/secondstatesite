from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import AuctionReminderDelivery, AuctionWatchLot


E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
ACCOUNT_SID_PATTERN = re.compile(r"^AC[0-9a-fA-F]{32}$")
API_KEY_SID_PATTERN = re.compile(r"^SK[0-9a-fA-F]{32}$")
MESSAGING_SERVICE_SID_PATTERN = re.compile(r"^MG[0-9a-fA-F]{32}$")
REMINDER_DAYS = (3, 2, 1)
MAX_MESSAGE_LENGTH = 1500


class ReminderConfigurationError(RuntimeError):
    pass


class TwilioSendError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TwilioSendResult:
    message_sid: str
    status: str


@dataclass(frozen=True, slots=True)
class ReminderDigest:
    target_date: date
    days_before: int
    lot_count: int
    sale_count: int
    body: str
    sale_hashes: tuple[str, ...]
    lots: tuple[AuctionWatchLot, ...] = field(repr=False)


@dataclass(slots=True)
class ReminderRunResult:
    digests: list[ReminderDigest] = field(default_factory=list)
    sent: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class TwilioSmsSender:
    def __init__(
        self,
        *,
        account_sid: str,
        api_key_sid: str,
        api_key_secret: str,
        from_number: str = "",
        messaging_service_sid: str = "",
        session=requests,
        timeout: tuple[int, int] = (10, 30),
    ) -> None:
        if not account_sid or not api_key_sid or not api_key_secret:
            raise ReminderConfigurationError(
                "TWILIO_ACCOUNT_SID, TWILIO_API_KEY_SID, and TWILIO_API_KEY_SECRET are required."
            )
        if not ACCOUNT_SID_PATTERN.fullmatch(account_sid):
            raise ReminderConfigurationError("TWILIO_ACCOUNT_SID must be a valid AC-prefixed Twilio Account SID.")
        if not API_KEY_SID_PATTERN.fullmatch(api_key_sid):
            raise ReminderConfigurationError("TWILIO_API_KEY_SID must be a valid SK-prefixed Twilio API Key SID.")
        if not from_number and not messaging_service_sid:
            raise ReminderConfigurationError(
                "Set TWILIO_FROM_NUMBER or TWILIO_MESSAGING_SERVICE_SID before enabling SMS."
            )
        if from_number and not E164_PATTERN.fullmatch(from_number):
            raise ReminderConfigurationError("TWILIO_FROM_NUMBER must use E.164 format, such as +12065550123.")
        if messaging_service_sid and not MESSAGING_SERVICE_SID_PATTERN.fullmatch(messaging_service_sid):
            raise ReminderConfigurationError(
                "TWILIO_MESSAGING_SERVICE_SID must be empty or a valid MG-prefixed Messaging Service SID."
            )
        self.account_sid = account_sid
        self.api_key_sid = api_key_sid
        self.api_key_secret = api_key_secret
        self.from_number = from_number
        self.messaging_service_sid = messaging_service_sid
        self.session = session
        self.timeout = timeout

    @classmethod
    def from_settings(cls, *, session=requests) -> "TwilioSmsSender":
        return cls(
            account_sid=settings.TWILIO_ACCOUNT_SID.strip(),
            api_key_sid=settings.TWILIO_API_KEY_SID.strip(),
            api_key_secret=settings.TWILIO_API_KEY_SECRET.strip(),
            from_number=settings.TWILIO_FROM_NUMBER.strip(),
            messaging_service_sid=settings.TWILIO_MESSAGING_SERVICE_SID.strip(),
            session=session,
        )

    def send(self, recipient: str, body: str) -> TwilioSendResult:
        form = {"To": recipient, "Body": body}
        if self.messaging_service_sid:
            form["MessagingServiceSid"] = self.messaging_service_sid
        else:
            form["From"] = self.from_number
        try:
            response = self.session.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json",
                auth=(self.api_key_sid, self.api_key_secret),
                data=form,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise TwilioSendError("The Twilio API could not be reached.") from exc

        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = {}
        if response.status_code >= 400:
            detail = str(payload.get("message") or "").strip()[:300] if isinstance(payload, dict) else ""
            raise TwilioSendError(detail or f"Twilio returned HTTP {response.status_code}.")
        message_sid = str(payload.get("sid") or "") if isinstance(payload, dict) else ""
        if not message_sid:
            raise TwilioSendError("Twilio accepted the request but did not return a message SID.")
        return TwilioSendResult(message_sid=message_sid, status=str(payload.get("status") or "queued"))


def parse_recipients(raw: str) -> list[str]:
    recipients = []
    for value in (raw or "").split(","):
        number = value.strip()
        if not number:
            continue
        if not E164_PATTERN.fullmatch(number):
            raise ReminderConfigurationError(
                f"Reminder recipient ending in {number[-4:]!r} is not a valid E.164 phone number."
            )
        if number not in recipients:
            recipients.append(number)
    if not recipients:
        raise ReminderConfigurationError("AUCTION_REMINDER_TO_NUMBERS must contain at least one opted-in phone number.")
    return recipients


def _utc_bounds(target_date: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    return start.astimezone(datetime_timezone.utc), end.astimezone(datetime_timezone.utc)


def _sale_identity(lot: AuctionWatchLot) -> str:
    return lot.sale_url or "|".join((lot.source, lot.auction_house, lot.sale_title, lot.event_at.isoformat()))


def _sale_hash(lot: AuctionWatchLot) -> str:
    return hashlib.sha256(_sale_identity(lot).encode("utf-8")).hexdigest()


def _artist(lot: AuctionWatchLot) -> str:
    return lot.artist_watchlist_name or lot.artist or "Unknown artist"


def _digest_for(target_date: date, days_before: int, lots: list[AuctionWatchLot]) -> ReminderDigest:
    sales: dict[str, list[AuctionWatchLot]] = {}
    for lot in lots:
        sales.setdefault(_sale_identity(lot), []).append(lot)

    day_word = "day" if days_before == 1 else "days"
    header = f"SecondState auction reminder: {days_before} {day_word} to {target_date.strftime('%a, %b %d').replace(' 0', ' ')}."
    link = f"Calendar: {settings.SECONDSTATE_PUBLIC_URL}/calendar/?month={target_date:%Y-%m}"
    lines = []
    grouped_sales = list(sales.values())
    for index, sale_lots in enumerate(grouped_sales):
        first = sale_lots[0]
        house = first.auction_house or first.source or "Auction"
        sale_title = f": {first.sale_title}" if first.sale_title else ""
        artists = sorted({_artist(lot) for lot in sale_lots}, key=str.casefold)
        artist_text = ", ".join(artists[:3])
        if len(artists) > 3:
            artist_text += f" +{len(artists) - 3} more"
        candidate = f"- {house}{sale_title} ({len(sale_lots)} lot{'s' if len(sale_lots) != 1 else ''}; {artist_text})"
        proposed = "\n".join((header, *lines, candidate, link))
        if len(proposed) > MAX_MESSAGE_LENGTH:
            remaining = len(grouped_sales) - index
            overflow = f"- +{remaining} more sale{'s' if remaining != 1 else ''} on the calendar"
            if len("\n".join((header, *lines, overflow, link))) <= MAX_MESSAGE_LENGTH:
                lines.append(overflow)
            break
        lines.append(candidate)
    body = "\n".join((header, *lines, link))
    return ReminderDigest(
        target_date=target_date,
        days_before=days_before,
        lot_count=len(lots),
        sale_count=len(sales),
        body=body,
        sale_hashes=tuple(sorted({_sale_hash(lot) for lot in lots})),
        lots=tuple(lots),
    )


def build_due_digests(today: date) -> list[ReminderDigest]:
    zone = ZoneInfo(settings.CALENDAR_TIME_ZONE)
    digests = []
    for days_before in REMINDER_DAYS:
        target_date = today + timedelta(days=days_before)
        range_start, range_end = _utc_bounds(target_date, zone)
        lots = list(
            AuctionWatchLot.objects.filter(active=True, event_at__gte=range_start, event_at__lt=range_end).order_by(
                "event_at", "auction_house", "artist", "id"
            )
        )
        if lots:
            digests.append(_digest_for(target_date, days_before, lots))
    return digests


def _recipient_hash(recipient: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), recipient.encode("utf-8"), hashlib.sha256).hexdigest()


def _masked_recipient(recipient: str) -> str:
    return f"***{recipient[-4:]}"


def run_auction_reminders(
    *,
    today: date,
    dry_run: bool = False,
    recipients: list[str] | None = None,
    sender: TwilioSmsSender | None = None,
) -> ReminderRunResult:
    result = ReminderRunResult(digests=build_due_digests(today))
    if dry_run or not result.digests:
        return result

    recipients = recipients if recipients is not None else parse_recipients(settings.AUCTION_REMINDER_TO_NUMBERS)
    if not recipients:
        raise ReminderConfigurationError("At least one opted-in reminder recipient is required.")
    for recipient in recipients:
        if not E164_PATTERN.fullmatch(recipient):
            raise ReminderConfigurationError("All reminder recipients must use E.164 format.")
    sender = sender or TwilioSmsSender.from_settings()

    for digest in result.digests:
        for recipient in recipients:
            recipient_hash = _recipient_hash(recipient)
            with transaction.atomic():
                delivery, created = AuctionReminderDelivery.objects.select_for_update().get_or_create(
                    target_date=digest.target_date,
                    days_before=digest.days_before,
                    recipient_hash=recipient_hash,
                    defaults={"recipient_display": _masked_recipient(recipient)},
                )
                if not created and delivery.status == AuctionReminderDelivery.Status.PENDING:
                    result.skipped += 1
                    continue
                covered = set(delivery.covered_sale_hashes or [])
                uncovered = set(digest.sale_hashes) - covered
                if not uncovered:
                    result.skipped += 1
                    continue
                pending_lots = [lot for lot in digest.lots if _sale_hash(lot) in uncovered]
                pending_digest = _digest_for(digest.target_date, digest.days_before, pending_lots)
                delivery.status = AuctionReminderDelivery.Status.PENDING
                delivery.recipient_display = _masked_recipient(recipient)
                delivery.error = ""
                delivery.attempted_at = timezone.now()
                delivery.save(
                    update_fields=("status", "recipient_display", "error", "attempted_at", "updated_at")
                )
            try:
                sent = sender.send(recipient, pending_digest.body)
            except Exception as exc:
                message = " ".join(str(exc).split())[:500] or "Unknown Twilio delivery error."
                AuctionReminderDelivery.objects.filter(pk=delivery.pk).update(
                    status=AuctionReminderDelivery.Status.FAILED,
                    error=message,
                    twilio_status="failed",
                    updated_at=timezone.now(),
                )
                result.failed += 1
                result.errors.append(f"{digest.target_date} {_masked_recipient(recipient)}: {message}")
                continue
            AuctionReminderDelivery.objects.filter(pk=delivery.pk).update(
                status=AuctionReminderDelivery.Status.SENT,
                twilio_message_sid=sent.message_sid,
                twilio_status=sent.status,
                sent_at=timezone.now(),
                covered_sale_hashes=sorted(covered | uncovered),
                error="",
                updated_at=timezone.now(),
            )
            result.sent += 1
    return result
