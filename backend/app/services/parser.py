from __future__ import annotations

from pathlib import Path

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

    title = path.stem
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
    for page in document:
        lines = page.get_text("text").splitlines()
        filtered = strip_repeated_headers(lines)
        pages.append("\n".join(filtered))
    return {"text": normalize_space("\n\n".join(pages)), "total_pages": max(1, len(document))}

