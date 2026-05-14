from __future__ import annotations

import hashlib
import os
from pathlib import Path
from functools import lru_cache

from ..config import settings
from ..utils.text import cosine, tokenize


class EmbeddingService:
    def __init__(self) -> None:
        self._model = None
        self._model_failed = False

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        if model is not None:
            vectors = model.encode(texts, normalize_embeddings=True)
            return [list(map(float, vector)) for vector in vectors]
        return [_hash_embedding(text) for text in texts]

    def similarity(self, left: str, right: str) -> float:
        a, b = self.embed([left, right])
        return cosine(a, b)

    @property
    def using_fallback(self) -> bool:
        return self._model is None

    def _load_model(self):
        if self._model_failed:
            return None
        if self._model is not None:
            return self._model
        is_local_path = Path(settings.embedding_model).expanduser().exists()
        try:
            from sentence_transformers import SentenceTransformer

            if settings.embedding_allow_download or is_local_path:
                self._model = SentenceTransformer(settings.embedding_model)
            else:
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                self._model = SentenceTransformer(settings.embedding_model, local_files_only=True)
            return self._model
        except TypeError:
            self._model_failed = True
            return None
        except Exception:
            self._model_failed = True
            return None


@lru_cache(maxsize=4096)
def _hash_embedding(text: str, dimensions: int = 128) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0:
        return vector
    return [value / norm for value in vector]


embedding_service = EmbeddingService()
