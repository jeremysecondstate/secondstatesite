"""Read one bounded PDF from stdin and emit safe extraction JSON; no OCR."""

from io import BytesIO
import json
import logging
import sys


MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PAGES = 20
MAX_TEXT = 24000


def extract(content):
    from pypdf import PdfReader

    if not content or len(content) > MAX_PDF_BYTES or not content.startswith(b"%PDF-"):
        return {"error": "Upload a valid PDF no larger than 5 MiB."}
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            return {"error": "Encrypted PDFs are not supported. Upload an unencrypted copy or paste its text."}
        page_count = len(reader.pages)
        if not page_count:
            return {"error": "The PDF contains no pages."}
        text = ""
        truncated = page_count > MAX_PAGES
        for index in range(min(page_count, MAX_PAGES)):
            excerpt = reader.pages[index].extract_text() or ""
            excerpt = excerpt.replace("\x00", "")
            remaining = MAX_TEXT - len(text)
            addition = ("\n\n" if text else "") + excerpt
            if len(addition) > remaining:
                text += addition[:remaining]
                truncated = True
                break
            text += addition
            if len(text) == MAX_TEXT and index + 1 < page_count:
                truncated = True
                break
        text = text.strip()
        if not text:
            return {"text": "", "status": "no_text", "error": (
                "No readable text was found in the first 20 pages. Original PDF retained; OCR was not performed."
                if page_count > MAX_PAGES else
                "No readable text was found. Original PDF retained; OCR was not performed."
            )}
        return {"text": text, "status": "truncated" if truncated else "ready",
                "error": "Only the first 20 pages and up to 24,000 characters were extracted." if truncated else ""}
    except Exception:
        # Parser diagnostics can contain document text or malicious control bytes.
        return {"error": "The PDF could not be read. Upload a valid PDF or paste its text."}


def main():
    logging.disable(logging.CRITICAL)
    # pypdf documents potentially large decompression during text extraction.
    # On the production Linux host, bound the isolated process's address space.
    if sys.platform != "win32":
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        except (ImportError, OSError, ValueError):
            pass
    content = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
    try:
        result = extract(content)
    except Exception:
        result = {"error": "PDF extraction is unavailable. Paste the document text instead."}
    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
