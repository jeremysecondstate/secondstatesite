"""Private seasonal proposal workspace and recipient-facing US Letter catalogs."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from functools import lru_cache
from io import BytesIO
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Min
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from PIL import Image as PILImage, ImageOps
import requests

from .calendar_images import is_saved_calendar_image_url
from .calendar_views import _calendar_image_url
from .models import HouseProposalEntry


def _season_key(season, year):
    return f"{season}-{year}"


def _season_label(key):
    season, year = key.split("-")
    return f"{season.title()} {year}"


def _chronology(key):
    season, year = key.split("-")
    return int(year), season == "fall"


def _planning_season():
    today = timezone.localdate(timezone=ZoneInfo(settings.CALENDAR_TIME_ZONE))
    if today.month >= 10:
        return _season_key("spring", today.year + 1)
    return _season_key("spring" if today.month < 5 else "fall", today.year)


def _catalog_url(season, house, work=None, *, pdf=False):
    name = "calendar_consignment_proposal_pdf" if pdf else "calendar_consignment_proposals"
    query = {"season": season, "house": house}
    if work:
        query["work"] = work
    return reverse(name) + "?" + urlencode(query)


def _money(amount):
    return f"${amount:,.0f}" if amount == int(amount) else f"${amount:,.2f}"


def _range(low, high):
    return f"{_money(low)}–{_money(high)}"


def _valid_estimate(entry):
    return (entry.estimate_currency == "USD" and entry.estimate_low is not None
            and entry.estimate_high is not None and 0 < entry.estimate_low <= entry.estimate_high)


def _photo_url(entry):
    image = entry.image_url or (entry.lot.image_url if entry.work_key == "lot" else "")
    return _calendar_image_url(image)


def _packet_context(request, *, for_export=False):
    query = HouseProposalEntry.objects.all()
    houses_by_season = defaultdict(dict)
    for row in query.values("season", "year", "house_key").annotate(name=Min("house")).order_by("name"):
        houses_by_season[_season_key(row["season"], row["year"])][row["house_key"]] = row["name"]
    planning = _planning_season()
    seasons = set(houses_by_season) | {planning}
    scheduled = sorted(houses_by_season, key=_chronology)
    default = next((key for key in scheduled if _chronology(key) >= _chronology(planning)),
                   scheduled[-1] if scheduled else planning)
    selected_season = request.GET.get("season") or default
    if selected_season not in seasons:
        raise Http404("Unknown proposal season.")
    houses = houses_by_season[selected_season]
    selected_house = request.GET.get("house") or next(iter(houses), "")
    if selected_house and selected_house not in houses:
        raise Http404("Unknown proposal house for this season.")
    if for_export and (not request.GET.get("season") or not request.GET.get("house")):
        raise Http404("Choose a house and season.")
    season_name, year_text = selected_season.split("-")
    entries = list(query.filter(season=season_name, year=int(year_text), house_key=selected_house)
                   .select_related("lot")) if selected_house else []
    if for_export and not entries:
        raise Http404("This selection has no works.")
    current_work = request.GET.get("work")
    index = next((i for i, item in enumerate(entries) if str(item.pk) == current_work), 0)
    low = high = Decimal(0)
    incomplete = []
    all_estimated = True
    for entry in entries:
        entry.photo_url = _photo_url(entry)
        entry.page_url = _catalog_url(selected_season, selected_house, entry.pk)
        entry.estimate = ""
        if _valid_estimate(entry):
            low += entry.estimate_low
            high += entry.estimate_high
            entry.estimate = _range(entry.estimate_low, entry.estimate_high)
        else:
            all_estimated = False
        missing = [field for field, value in (
            ("artist", entry.artist), ("title", entry.title), ("catalog text", entry.description),
            ("saved object photograph" if entry.image_url else "photograph", entry.photo_url),
            ("USD estimate", entry.estimate),
        ) if not value]
        if missing:
            incomplete.append(f"{entry.title or 'Untitled work'} — {', '.join(missing)}")
    return {
        "seasons": [(key, _season_label(key)) for key in sorted(seasons, key=_chronology, reverse=True)],
        "houses": houses.items(), "season": selected_season, "season_label": _season_label(selected_season),
        "house": selected_house, "house_name": houses.get(selected_house), "spring": season_name == "spring",
        "entries": entries, "entry": entries[index] if entries else None, "position": index + 1,
        "previous": entries[index - 1] if index else None,
        "following": entries[index + 1] if index + 1 < len(entries) else None,
        "total": _range(low, high) if entries and all_estimated else "",
        "pending": sum(not item.lot.won_by_us for item in entries), "incomplete": incomplete,
        "pdf_url": _catalog_url(selected_season, selected_house, pdf=True) if entries else "",
    }


@never_cache
@staff_member_required
@require_safe
def proposal_workspace(request):
    return render(request, "calendar/consignment_proposals.html", _packet_context(request))


class ProposalPhotoError(ValueError):
    pass


def _photo_bytes(url):
    """Read a hash-addressed image or a bounded HTTPS image on a known auction host."""
    limit = 8 * 1024 * 1024
    if is_saved_calendar_image_url(url):
        directory = Path(settings.MEDIA_ROOT).resolve() / "calendar-lots"
        path = directory / url.rsplit("/", 1)[1]
        if path.resolve() != path or path.stat().st_size > limit:
            raise ProposalPhotoError("The saved photograph is unavailable.")
        return path.read_bytes()
    parts = urlsplit(url)
    if (not _calendar_image_url(url) or parts.scheme != "https" or parts.port not in (None, 443)
            or parts.username is not None or parts.password is not None):
        raise ProposalPhotoError("The photograph needs a saved image.")
    with requests.get(url, timeout=(3, 6), allow_redirects=False, stream=True,
                      headers={"Accept": "image/*"}) as response:
        if response.status_code != 200:
            raise ProposalPhotoError("The source photograph is unavailable.")
        data = bytearray()
        for block in response.iter_content(64 * 1024):
            data.extend(block)
            if len(data) > limit:
                raise ProposalPhotoError("The source photograph is too large.")
        return bytes(data)


def _photo(entry):
    from reportlab.platypus import Image

    try:
        with PILImage.open(BytesIO(_photo_bytes(entry.photo_url))) as original:
            if (original.format not in {"JPEG", "PNG", "WEBP"} or original.width * original.height > 20_000_000
                    or min(original.size) < 9 or getattr(original, "is_animated", False)):
                raise ProposalPhotoError("Unsupported photograph.")
            oriented = ImageOps.exif_transpose(original)
            oriented.thumbnail((1400, 1400))
            pixels = oriented.convert("RGBA")
            clean = PILImage.new("RGB", pixels.size, "white")
            clean.paste(pixels, mask=pixels.getchannel("A"))
            image_file = BytesIO()
            clean.save(image_file, format="JPEG", quality=90)
            image_file.seek(0)
            scale = min(355 / clean.width, 222 / clean.height)
            return Image(image_file, width=clean.width * scale, height=clean.height * scale, hAlign="LEFT")
    except (ValueError, OSError, PILImage.DecompressionBombError, requests.RequestException) as exc:
        raise ProposalPhotoError(
            f"The photograph for “{entry.title}” could not be included. Save its object photograph with the proposal and retry."
        ) from exc


@lru_cache(maxsize=1)
def _catalog_typefaces():
    """Embed serif faces on both supported host platforms to retain accents and fractions."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    options = [
        (Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", ("times", "timesbd", "timesi", "timesbi")),
        (Path("/usr/share/fonts/truetype/liberation2"), tuple("LiberationSerif-" + face for face in
                                                             ("Regular", "Bold", "Italic", "BoldItalic"))),
        (Path("/usr/share/fonts/truetype/liberation"), tuple("LiberationSerif-" + face for face in
                                                            ("Regular", "Bold", "Italic", "BoldItalic"))),
        (Path("/usr/share/fonts/truetype/dejavu"), ("DejaVuSerif", "DejaVuSerif-Bold", "DejaVuSerif-Italic",
                                                  "DejaVuSerif-BoldItalic")),
    ]
    names = ("ProposalSerif", "ProposalSerifBold", "ProposalSerifItalic", "ProposalSerifBoldItalic")
    for directory, filenames in options:
        paths = [directory / f"{filename}.ttf" for filename in filenames]
        if all(path.is_file() for path in paths):
            for name, path in zip(names, paths):
                pdfmetrics.registerFont(TTFont(name, str(path)))
            pdfmetrics.registerFontFamily(names[0], normal=names[0], bold=names[1], italic=names[2], boldItalic=names[3])
            return names[:3]
    return "Times-Roman", "Times-Bold", "Times-Italic"


def _build_pdf(context):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, leftMargin=66, rightMargin=66, topMargin=65,
                            bottomMargin=60, title=f"{context['house_name']} · {context['season_label']}",
                            author="SecondState")
    serif, bold, italic = _catalog_typefaces()
    body = ParagraphStyle("Catalog", fontName=serif, fontSize=12, leading=14.5, spaceAfter=9)
    name = ParagraphStyle("Artist", fontName=bold, fontSize=18, leading=21, spaceAfter=22)
    total = ParagraphStyle("Total", parent=body, fontName=italic, alignment=TA_CENTER)

    def plain(value):
        return "<br/>".join(escape(line) for line in value.splitlines())

    story = []
    for i, entry in enumerate(context["entries"]):
        if i:
            story.append(PageBreak())
        story += [Paragraph(plain(entry.artist), name), _photo(entry), Spacer(1, 17)]
        title = f"<b>{plain(entry.title)}</b>" + (f", {plain(entry.year_text)}" if entry.year_text else "")
        facts = [title] + [plain(value) for value in (entry.medium, entry.dimensions, entry.edition) if value]
        story.append(Paragraph("<br/>".join(facts), body))
        for label, value in (("", entry.object_notes), ("Condition", entry.condition),
                             ("Provenance", entry.provenance), ("Literature", entry.literature),
                             ("", entry.description)):
            if value:
                story.append(Paragraph((f"{label}: " if label else "") + plain(value), body))
        closing = [Paragraph(f"Estimate: {entry.estimate}", body)]
        if i == len(context["entries"]) - 1:
            closing += [HRFlowable(width="100%", thickness=.4, color=colors.lightgrey, spaceAfter=8),
                        Paragraph(f"Total: {context['total']}", total)]
        story.append(KeepTogether(closing))
    doc.build(story)
    output.seek(0)
    return output


@never_cache
@staff_member_required
@require_safe
def proposal_pdf(request):
    context = _packet_context(request, for_export=True)
    if not context["incomplete"]:
        try:
            pdf = _build_pdf(context)
        except ProposalPhotoError as exc:
            context["export_error"] = str(exc)
        else:
            suffix = "-draft" if context["pending"] else ""
            filename = f"{context['house']}-{context['season']}{suffix}.pdf"
            return FileResponse(pdf, as_attachment=True, filename=filename, content_type="application/pdf")
    return render(request, "calendar/consignment_proposals.html", context, status=422)
