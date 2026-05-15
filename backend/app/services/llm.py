from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..config import settings
from ..runtime.store import state_store
from ..utils.text import estimate_tokens


class LlmResult(dict):
    @property
    def elapsed_ms(self) -> int:
        return int(self.get("elapsed_ms", 0))

    @property
    def token_estimate(self) -> int:
        return int(self.get("token_estimate", 0))


@dataclass(frozen=True)
class ResolvedLlmConfig:
    base_url: str
    api_key: str
    model: str
    source: str


class LlmClient:
    def resolve_config(self, workspace_id: str = "global") -> ResolvedLlmConfig | None:
        if workspace_id != "global":
            config = state_store.get_workspace_llm_config(workspace_id)
            if config and config.get("base_url") and config.get("api_key") and config.get("model"):
                return ResolvedLlmConfig(
                    base_url=str(config["base_url"]),
                    api_key=str(config["api_key"]),
                    model=str(config["model"]),
                    source="session",
                )
        if settings.llm_base_url and settings.llm_api_key:
            return ResolvedLlmConfig(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                source="global",
            )
        return None

    def is_configured(self, workspace_id: str = "global") -> bool:
        return self.resolve_config(workspace_id) is not None

    def complete_json(self, system: str, user: str, workspace_id: str = "global") -> LlmResult:
        config = self.resolve_config(workspace_id)
        if config is None:
            return LlmResult({"data": None, "elapsed_ms": 0, "token_estimate": estimate_tokens([system, user])})
        started = time.perf_counter()
        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": 1400,
            "response_format": {"type": "json_object"},
        }
        try:
            data = self._post(payload, config)
            content = data["choices"][0]["message"]["content"]
            return LlmResult(
                {
                    "data": json.loads(content),
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "token_estimate": estimate_tokens([system, user, content]),
                }
            )
        except Exception as exc:
            return LlmResult(
                {
                    "data": None,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "token_estimate": estimate_tokens([system, user]),
                    "error": str(exc),
                }
            )

    def complete_text(self, system: str, user: str, workspace_id: str = "global") -> LlmResult:
        config = self.resolve_config(workspace_id)
        if config is None:
            return LlmResult({"data": None, "elapsed_ms": 0, "token_estimate": estimate_tokens([system, user])})
        started = time.perf_counter()
        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 900,
        }
        try:
            data = self._post(payload, config)
            content = data["choices"][0]["message"]["content"]
            return LlmResult(
                {
                    "data": content,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "token_estimate": estimate_tokens([system, user, content]),
                }
            )
        except Exception as exc:
            return LlmResult(
                {
                    "data": None,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "token_estimate": estimate_tokens([system, user]),
                    "error": str(exc),
                }
            )

    def _post(self, payload: dict[str, Any], config: ResolvedLlmConfig) -> dict[str, Any]:
        base = config.base_url.rstrip("/")
        url = f"{base}/chat/completions"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.llm_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc


llm_client = LlmClient()
