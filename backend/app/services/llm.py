from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from ..config import settings
from ..utils.text import estimate_tokens


class LlmResult(dict):
    @property
    def elapsed_ms(self) -> int:
        return int(self.get("elapsed_ms", 0))

    @property
    def token_estimate(self) -> int:
        return int(self.get("token_estimate", 0))


class LlmClient:
    def is_configured(self) -> bool:
        return bool(settings.llm_base_url and settings.llm_api_key)

    def complete_json(self, system: str, user: str) -> LlmResult:
        if not self.is_configured():
            return LlmResult({"data": None, "elapsed_ms": 0, "token_estimate": estimate_tokens([system, user])})
        started = time.perf_counter()
        payload = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        data = self._post(payload)
        content = data["choices"][0]["message"]["content"]
        return LlmResult(
            {
                "data": json.loads(content),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "token_estimate": estimate_tokens([system, user, content]),
            }
        )

    def complete_text(self, system: str, user: str) -> LlmResult:
        if not self.is_configured():
            return LlmResult({"data": None, "elapsed_ms": 0, "token_estimate": estimate_tokens([system, user])})
        started = time.perf_counter()
        payload = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        data = self._post(payload)
        content = data["choices"][0]["message"]["content"]
        return LlmResult(
            {
                "data": content,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "token_estimate": estimate_tokens([system, user, content]),
            }
        )

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        base = settings.llm_base_url.rstrip("/")
        url = f"{base}/chat/completions"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc


llm_client = LlmClient()

