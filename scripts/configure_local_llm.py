#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT / ".env"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"


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


def read_env_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_env_line(line)
        if parsed is not None:
            key, value = parsed
            values[key] = value
    return values


def render_env_file(path: Path, updates: dict[str, str]) -> str:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    rendered: list[str] = []
    for line in lines:
        parsed = parse_env_line(line)
        if parsed is None:
            rendered.append(line)
            continue
        key, _ = parsed
        if key in updates:
            rendered.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            rendered.append(line)
    for key, value in updates.items():
        if key not in seen:
            rendered.append(f"{key}={value}")
    return "\n".join(rendered).rstrip() + "\n"


def write_env_file(path: Path, updates: dict[str, str]) -> None:
    path.write_text(render_env_file(path, updates), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure local DeepSeek LLM settings without printing secrets.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Path to local .env file")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI-compatible LLM base URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="LLM model name")
    args = parser.parse_args()

    env_file = Path(args.env_file)
    existing = read_env_map(env_file)
    api_key = getpass.getpass("LLM_API_KEY (input hidden; leave empty to keep existing value): ").strip()
    updates = {
        "LLM_BASE_URL": args.base_url,
        "LLM_MODEL": args.model,
    }
    if api_key:
        updates["LLM_API_KEY"] = api_key
    elif "LLM_API_KEY" not in existing:
        updates["LLM_API_KEY"] = ""

    write_env_file(env_file, updates)
    result = {
        "env_file": str(env_file),
        "llm_base_url": args.base_url,
        "llm_model": args.model,
        "llm_api_key_set": bool(api_key or existing.get("LLM_API_KEY")),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
