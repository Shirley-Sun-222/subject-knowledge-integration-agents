from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import UploadFile

from ..config import ROOT_DIR, settings


class RuntimeFiles:
    def upload_path(self, textbook_id: str, format_name: str) -> Path:
        suffix = f".{format_name}" if format_name and not format_name.startswith(".") else format_name
        return settings.upload_dir / f"{textbook_id}{suffix or '.txt'}"

    async def save_upload(self, textbook_id: str, file: UploadFile, format_name: str) -> tuple[Path, int]:
        destination = self.upload_path(textbook_id, format_name)
        size = 0
        with destination.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                buffer.write(chunk)
        return destination, size

    def copy_upload(self, textbook_id: str, source: Path, format_name: str) -> Path:
        destination = self.upload_path(textbook_id, format_name)
        shutil.copy2(source, destination)
        return destination

    def report_markdown_path(self) -> Path:
        path = ROOT_DIR / "report" / "整合报告.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def report_pdf_path(self) -> Path:
        settings.generated_dir.mkdir(parents=True, exist_ok=True)
        return settings.generated_dir / "整合报告.pdf"

    def stored_textbook_path(self, textbook_id: str, format_name: str) -> Path:
        return self.upload_path(textbook_id, format_name)


runtime_files = RuntimeFiles()

