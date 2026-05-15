#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]+")


def parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped.removeprefix("export ").strip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def load_env_file(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)


def mask_secret(message: str, secret: str = "") -> str:
    sanitized = message
    if secret:
        replacement = "sk-[redacted]" if secret.startswith("sk-") else "[redacted]"
        sanitized = sanitized.replace(secret, replacement)
    return SECRET_PATTERN.sub("sk-[redacted]", sanitized)


def result_error(result: Any, secret: str) -> str | None:
    if not isinstance(result, dict):
        return "LLM result is not a dictionary"
    if result.get("data") is None:
        return mask_secret(str(result.get("error", "empty response")), secret)
    return None


def main() -> int:
    load_env_file()
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from backend.app.config import settings
    from backend.app.services.llm import llm_client

    report: dict[str, Any] = {
        "base_url": settings.llm_base_url,
        "model": settings.llm_model,
        "api_key_configured": bool(settings.llm_api_key),
        "checks": {},
    }
    if not llm_client.is_configured():
        report["ok"] = False
        report["error"] = "LLM_BASE_URL and LLM_API_KEY must be configured in environment variables or .env"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    text_result = llm_client.complete_text(
        "你是学科知识整合系统的连通性检查器。回答必须简短。",
        "用一句话说明知识图谱是什么。",
    )
    text_error = result_error(text_result, settings.llm_api_key)
    report["checks"]["complete_text"] = {
        "ok": text_error is None,
        "elapsed_ms": int(text_result.get("elapsed_ms", 0)),
        "token_estimate": int(text_result.get("token_estimate", 0)),
        "response_chars": len(str(text_result.get("data") or "")),
        "error": text_error,
    }

    json_result = llm_client.complete_json(
        "你是 JSON API。必须只输出 JSON 对象，不要输出 Markdown。",
        '输出一个 JSON 对象，字段 ok 为 true，topic 为 "knowledge_graph"。',
    )
    json_error = result_error(json_result, settings.llm_api_key)
    json_data = json_result.get("data") if isinstance(json_result, dict) else None
    if json_error is None and not (isinstance(json_data, dict) and json_data.get("ok") is True):
        json_error = "JSON response did not contain ok=true"
    report["checks"]["complete_json"] = {
        "ok": json_error is None,
        "elapsed_ms": int(json_result.get("elapsed_ms", 0)),
        "token_estimate": int(json_result.get("token_estimate", 0)),
        "keys": sorted(json_data.keys()) if isinstance(json_data, dict) else [],
        "error": json_error,
    }

    report["ok"] = all(check["ok"] for check in report["checks"].values())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
