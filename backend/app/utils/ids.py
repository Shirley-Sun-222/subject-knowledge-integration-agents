from __future__ import annotations

import re
import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def slugify(value: str, max_length: int = 48) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value).strip("-")
    return cleaned[:max_length] or uuid.uuid4().hex[:8]

