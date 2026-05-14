from __future__ import annotations

import io
from pathlib import Path

from ..config import settings
from ..utils.text import normalize_space, split_chapters, strip_repeated_headers


class ParseError(RuntimeError):
    pass


def parse_textbook(path: Path, filename: str) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        parsed = _parse_pdf(path)
    elif suffix in {".md", ".markdown", ".txt"}:
        parsed = _parse_plain_text(path)
    elif suffix == ".docx":
        parsed = _parse_docx(path)
    else:
        raise ParseError(f"Unsupported file format: {suffix}")

    title = Path(filename).stem
    chapters = split_chapters(parsed["text"], title=title, total_pages=parsed["total_pages"])
    return {
        "filename": filename,
        "title": title,
        "format": suffix.replace(".", ""),
        "total_pages": parsed["total_pages"],
        "total_chars": sum(chapter["char_count"] for chapter in chapters),
        "chapters": chapters,
    }


def _parse_plain_text(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    return {"text": normalize_space(raw), "total_pages": 1}


def _parse_docx(path: Path) -> dict:
    try:
        from docx import Document
    except Exception as exc:  # pragma: no cover - optional dependency branch
        raise ParseError("python-docx is required to parse DOCX files") from exc

    document = Document(str(path))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())
    return {"text": normalize_space(text), "total_pages": max(1, len(document.paragraphs) // 8)}


def _parse_pdf(path: Path) -> dict:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - optional dependency branch
        raise ParseError("PyMuPDF is required to parse PDF files") from exc

    document = fitz.open(path)
    pages: list[str] = []
    for page_index, page in enumerate(document):
        lines = page.get_text("text").splitlines()
        page_text = "\n".join(strip_repeated_headers(lines))
        if settings.ocr_enabled and len(normalize_space(page_text)) < 20 and page_index < settings.ocr_max_pages:
            ocr_text = _ocr_pdf_page(page)
            if len(normalize_space(ocr_text)) > len(normalize_space(page_text)):
                page_text = ocr_text
        pages.append(page_text)
    text = normalize_space("\n\n".join(pages))
    if len(text) < 20:
        hint = "PDF has no extractable text"
        if settings.ocr_enabled:
            hint += "; OCR did not produce usable text. Check tesseract language data and OCR_MAX_PAGES."
        else:
            hint += "; enable OCR_ENABLED=1 for scanned PDFs."
        raise ParseError(hint)
    return {"text": text, "total_pages": max(1, len(document))}


def _ocr_pdf_page(page) -> str:
    try:
        import pytesseract
        from PIL import Image
        import fitz
    except Exception:
        return ""
    try:
        # 2x render improves OCR accuracy without making sample uploads impractically slow.
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    except Exception:
        return ""
    lang = _available_ocr_lang(settings.ocr_lang)
    try:
        return pytesseract.image_to_string(image, lang=lang).strip()
    except Exception:
        if lang != "eng":
            try:
                return pytesseract.image_to_string(image, lang="eng").strip()
            except Exception:
                return ""
        return ""


def _available_ocr_lang(requested: str) -> str:
    try:
        import pytesseract

        available = set(pytesseract.get_languages(config=""))
    except Exception:
        return "eng"
    parts = [part for part in requested.split("+") if part]
    selected = [part for part in parts if part in available]
    if selected:
        return "+".join(selected)
    return "eng" if "eng" in available else (sorted(available)[0] if available else "eng")
