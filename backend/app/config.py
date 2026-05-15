from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


def _path_from_env(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    if not path.is_absolute():
        path = ROOT_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
    upload_dir: Path = _path_from_env("UPLOAD_DIR", "./data/uploads")
    index_dir: Path = _path_from_env("INDEX_DIR", "./data/indexes")
    generated_dir: Path = _path_from_env("GENERATED_DIR", "./data/generated")
    frontend_dist: Path | None = (
        Path(os.environ["FRONTEND_DIST"]).resolve()
        if os.getenv("FRONTEND_DIST")
        else None
    )
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "90"))
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    embedding_allow_download: bool = os.getenv("EMBEDDING_ALLOW_DOWNLOAD", "0") == "1"
    ocr_enabled: bool = os.getenv("OCR_ENABLED", "1") == "1"
    ocr_max_pages: int = int(os.getenv("OCR_MAX_PAGES", "120"))
    ocr_lang: str = os.getenv("OCR_LANG", "chi_sim+eng")
    graph_max_chapters: int = int(os.getenv("GRAPH_MAX_CHAPTERS", "30"))

    @property
    def database_path(self) -> Path:
        if self.database_url.startswith("sqlite:///"):
            raw = self.database_url.replace("sqlite:///", "", 1)
            path = Path(raw)
            if not path.is_absolute():
                path = ROOT_DIR / path
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        raise ValueError("Only sqlite:/// DATABASE_URL is supported in this app")


settings = Settings()
