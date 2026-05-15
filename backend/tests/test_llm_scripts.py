from __future__ import annotations

import os
from pathlib import Path

from scripts.check_llm import load_env_file, mask_secret
from scripts.configure_local_llm import render_env_file


def test_load_env_file_does_not_override_existing_values(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_BASE_URL=https://api.deepseek.com\nLLM_API_KEY=local-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_API_KEY", "exported-secret")
    load_env_file(env_file)
    assert os.environ["LLM_BASE_URL"] == "https://api.deepseek.com"
    assert os.environ["LLM_API_KEY"] == "exported-secret"


def test_mask_secret_redacts_api_key_values() -> None:
    secret = "sk" + "-example-secret"
    other = "sk" + "-other"
    message = f"provider rejected {secret} and {other}"
    assert mask_secret(message, secret) == "provider rejected sk-[redacted] and sk-[redacted]"


def test_render_env_file_preserves_existing_order_and_updates_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_BASE_URL=https://api.openai.com/v1\nLLM_API_KEY=\nLLM_MODEL=gpt-4o-mini\nOCR_ENABLED=1\n",
        encoding="utf-8",
    )
    rendered = render_env_file(
        env_file,
        {
            "LLM_BASE_URL": "https://api.deepseek.com",
            "LLM_MODEL": "deepseek-v4-pro",
        },
    )
    assert "LLM_BASE_URL=https://api.deepseek.com" in rendered
    assert "LLM_MODEL=deepseek-v4-pro" in rendered
    assert "LLM_API_KEY=\n" in rendered
    assert rendered.rstrip().endswith("OCR_ENABLED=1")
