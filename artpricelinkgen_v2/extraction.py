import re
import shutil
import unicodedata

from artpricelinkgen_v2.models import ExtractedListing

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import pytesseract
except ImportError:
    pytesseract = None


class ImageListingExtractor:
    @staticmethod
    def _clean_text(value: str) -> str:
        value = str(value or "")
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = value.replace("—", "-").replace("–", "-")
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def clean_artist_name(self, value: str) -> str:
        value = self._clean_text(value)
        value = re.sub(r"\([^)]*\)", "", value)
        value = re.sub(r"\b(?:after|attributed to|attr\.?|school of|manner of|circle of|follower of)\b", "", value, flags=re.I)
        value = re.sub(r"\b(?:american|british|french|german|spanish|italian|japanese|chinese|mexican|canadian)\b", "", value, flags=re.I)
        value = re.sub(r"\b(?:born|b\.)\s*\d{4}\b", "", value, flags=re.I)
        value = re.sub(r"\b\d{4}\s*-\s*\d{4}\b", "", value)
        value = re.sub(r"[^A-Za-z0-9' .,\-]+", " ", value)
        value = re.sub(r"\s*;.*$", "", value)
        value = re.sub(r"\s+/.*$", "", value)
        value = re.sub(r"\s+", " ", value).strip(" ,;:-")
        if "," in value and value.count(",") == 1:
            last, first = [p.strip() for p in value.split(",", 1)]
            if first and last:
                value = f"{first} {last}"
        return value

    def clean_title(self, value: str) -> str:
        value = self._clean_text(value)
        value = re.sub(r"\([^)]*\)", "", value)
        value = re.sub(r"\[[^\]]*\]", "", value)
        value = re.sub(r",?\s*(?:from|from the|from an?)\s+[^,;]+(?:series|suite|set|portfolio|album)?", "", value, flags=re.I)
        value = re.sub(r",?\s*(?:series|suite|set|portfolio|album)\s+[^,;]+$", "", value, flags=re.I)
        value = re.sub(r",?\s*(19|20)\d{2}$", "", value)
        value = re.sub(r"\b(?:signed|dated|numbered|framed|sheet|image size|estimate|dimensions)\b.*$", "", value, flags=re.I)
        value = re.sub(r"\s+", " ", value).strip(" ,;:-")
        return value

    def _ocr_text(self, image_path: str) -> str:
        if Image is None or pytesseract is None:
            raise RuntimeError(
                "OCR dependencies are missing. Install Pillow and pytesseract, then install the Tesseract app for your operating system."
            )
        if shutil.which("tesseract") is None:
            raise RuntimeError(
                "Tesseract OCR is not installed or is not on PATH. On Windows, install Tesseract and add it to PATH; on macOS, install it with Homebrew; on Linux, install it with your package manager."
            )
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)
        return text

    def extract_from_image(self, image_path: str) -> ExtractedListing:
        raw = self._ocr_text(image_path)
        text = self._clean_text(raw)

        lines = [self._clean_text(line) for line in raw.splitlines()]
        lines = [line for line in lines if line and len(line) > 2]

        artist = ""
        title = ""

        artist_patterns = [
            r"([A-Z][A-Za-z' .\-]+)\s*\((?:[^)]*)\)",
            r"([A-Z][A-Za-z' .\-]+)\s+\d{4}\s*-\s*\d{4}",
            r"([A-Z][A-Za-z' .\-]+)\s+(?:American|British|French|German|Spanish|Italian|Japanese|Chinese|Mexican|Canadian)",
        ]

        for line in lines[:12]:
            for pattern in artist_patterns:
                m = re.search(pattern, line, flags=re.I)
                if m:
                    artist = self.clean_artist_name(m.group(1))
                    break
            if artist:
                break

        if not artist:
            for line in lines[:12]:
                clean = self.clean_artist_name(line)
                words = clean.split()
                if 2 <= len(words) <= 4 and all(w[:1].isalpha() for w in words if w):
                    artist = clean
                    break

        title_candidates = []
        for line in lines[:20]:
            clean = self.clean_title(line)
            if not clean:
                continue
            if artist and self.clean_artist_name(clean).lower() == artist.lower():
                continue
            if re.search(r"(estimate|dimensions|sheet|image size|signed|framed|edition)", clean, flags=re.I):
                continue
            if len(clean.split()) >= 1:
                title_candidates.append(clean)

        if title_candidates:
            title = title_candidates[0]

        if not artist or not title:
            raise ValueError("Could not confidently read artist/title from the uploaded image.")

        return ExtractedListing(artist=artist, title=title, source_url=image_path, raw_heading=text[:500])
