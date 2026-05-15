from __future__ import annotations

import io
import shutil
from pathlib import Path
from typing import Callable

from ..config import settings
from ..utils.text import normalize_space, split_chapters, strip_repeated_headers


class ParseError(RuntimeError):
    pass


ParseProgress = Callable[[str, int, int], None]


def parse_textbook(path: Path, filename: str, progress: ParseProgress | None = None) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        parsed = _parse_pdf(path, progress=progress)
    elif suffix in {".md", ".markdown", ".txt"}:
        if progress is not None:
            progress("reading_textbook", 1, 1)
        parsed = _parse_plain_text(path)
    elif suffix == ".docx":
        if progress is not None:
            progress("reading_textbook", 0, 1)
        parsed = _parse_docx(path)
        if progress is not None:
            progress("reading_textbook", 1, 1)
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


def _parse_pdf(path: Path, progress: ParseProgress | None = None) -> dict:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - optional dependency branch
        raise ParseError("PyMuPDF is required to parse PDF files") from exc

    document = fitz.open(path)
    total_pages = max(1, len(document))
    mode = _detect_pdf_mode(document, progress)
    pages: list[str] = []
    for page_index, page in enumerate(document):
        lines = page.get_text("text").splitlines()
        page_text = "\n".join(strip_repeated_headers(lines))
        should_ocr = _should_ocr_page(mode, page_text, page_index)
        if should_ocr:
            ocr_text = _ocr_pdf_page(page)
            if len(normalize_space(ocr_text)) > len(normalize_space(page_text)):
                page_text = ocr_text
        if progress is not None:
            progress("ocr_pdf_pages" if should_ocr else "reading_pdf_pages", page_index + 1, total_pages)
        pages.append(page_text)
    text = normalize_space("\n\n".join(pages))
    if len(text) < 20:
        hint = "PDF has no extractable text"
        if settings.ocr_enabled:
            hint += "; OCR did not produce usable text. Check tesseract language data and OCR_MAX_PAGES."
        else:
            hint += "; enable OCR_ENABLED=1 for scanned PDFs."
        raise ParseError(hint)
    return {"text": text, "total_pages": total_pages}


def _detect_pdf_mode(document, progress: ParseProgress | None = None) -> str:
    sample_total = min(max(1, len(document)), min(settings.ocr_max_pages, 4))
    sparse_pages = 0
    for sample_index in range(sample_total):
        page_text = normalize_space(document[sample_index].get_text("text"))
        if len(page_text) < 20:
            sparse_pages += 1
        if progress is not None:
            progress("detecting_pdf_mode", sample_index + 1, sample_total)
    if sparse_pages == 0:
        return "digital"
    if sparse_pages == sample_total:
        return "scanned"
    return "mixed"


def _should_ocr_page(mode: str, page_text: str, page_index: int) -> bool:
    if not settings.ocr_enabled or page_index >= settings.ocr_max_pages:
        return False
    normalized = normalize_space(page_text)
    if mode == "digital":
        return len(normalized) == 0
    return len(normalized) < 20


def _ocr_pdf_page(page) -> str:
    try:
        import pytesseract
        from PIL import Image
        import fitz
    except Exception:
        return ""
    _configure_tesseract_cmd(pytesseract)
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

        _configure_tesseract_cmd(pytesseract)
        available = set(pytesseract.get_languages(config=""))
    except Exception:
        return "eng"
    parts = [part for part in requested.split("+") if part]
    selected = [part for part in parts if part in available]
    if selected:
        return "+".join(selected)
    return "eng" if "eng" in available else (sorted(available)[0] if available else "eng")


def _configure_tesseract_cmd(pytesseract_module) -> None:
    command = shutil.which("tesseract")
    if command is None:
        for candidate in ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract"]:
            if Path(candidate).exists():
                command = candidate
                break
    if command:
        pytesseract_module.pytesseract.tesseract_cmd = command
