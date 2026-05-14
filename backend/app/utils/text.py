from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable


CHAPTER_RE = re.compile(
    r"(?P<title>(第\s*[一二三四五六七八九十百千万0-9IVXivx]+\s*[章节篇部][^\n]{0,40}|Chapter\s+\d+[^\n]{0,50}))"
)


def normalize_space(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_repeated_headers(lines: list[str]) -> list[str]:
    counts = Counter(line.strip() for line in lines if 4 <= len(line.strip()) <= 80)
    repeated = {line for line, count in counts.items() if count >= 3}
    return [line for line in lines if line.strip() not in repeated]


def split_chapters(text: str, title: str, total_pages: int = 1) -> list[dict]:
    clean = normalize_space(text)
    matches = list(CHAPTER_RE.finditer(clean))
    if not matches:
        return [
            {
                "title": title or "虚拟章节",
                "page_start": 1,
                "page_end": max(total_pages, 1),
                "content": clean,
                "char_count": len(clean),
            }
        ]

    chapters: list[dict] = []
    page_span = max(math.ceil(max(total_pages, 1) / max(len(matches), 1)), 1)
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(clean)
        chapter_text = clean[start:end].strip()
        chapter_title = match.group("title").strip()
        page_start = min(index * page_span + 1, max(total_pages, 1))
        page_end = min((index + 1) * page_span, max(total_pages, 1))
        chapters.append(
            {
                "title": chapter_title,
                "page_start": page_start,
                "page_end": max(page_start, page_end),
                "content": chapter_text,
                "char_count": len(chapter_text),
            }
        )
    return chapters


def chunk_text(text: str, size: int = 650, overlap: int = 80) -> list[str]:
    clean = normalize_space(text)
    if not clean:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(start + size, len(clean))
        window = clean[start:end]
        if end < len(clean):
            split_at = max(window.rfind("。"), window.rfind("."), window.rfind("\n"))
            if split_at > size * 0.55:
                end = start + split_at + 1
                window = clean[start:end]
        chunks.append(window.strip())
        if end >= len(clean):
            break
        start = max(end - overlap, start + 1)
    return chunks


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", text.lower())
    chinese_pairs: list[str] = []
    for token in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            chinese_pairs.extend(token[i : i + 2] for i in range(len(token) - 1))
        else:
            chinese_pairs.append(token)
    return chinese_pairs


def top_keywords(text: str, limit: int = 8) -> list[str]:
    stop = {
        "以及",
        "进行",
        "可以",
        "通过",
        "具有",
        "相关",
        "本章",
        "内容",
        "教材",
        "知识",
    }
    counts = Counter(token for token in tokenize(text) if token not in stop and len(token) >= 2)
    return [word for word, _ in counts.most_common(limit)]


def estimate_tokens(parts: Iterable[str]) -> int:
    chars = sum(len(part) for part in parts)
    return max(1, math.ceil(chars / 2.2))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

