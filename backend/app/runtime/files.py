from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import UploadFile

from ..config import settings


class RuntimeFiles:
    def workspace_upload_dir(self, workspace_id: str) -> Path:
        path = settings.upload_dir / workspace_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def workspace_generated_dir(self, workspace_id: str) -> Path:
        path = settings.generated_dir / workspace_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def upload_path(self, workspace_id: str, textbook_id: str, format_name: str) -> Path:
        suffix = f".{format_name}" if format_name and not format_name.startswith(".") else format_name
        return self.workspace_upload_dir(workspace_id) / f"{textbook_id}{suffix or '.txt'}"

    async def save_upload(self, workspace_id: str, textbook_id: str, file: UploadFile, format_name: str) -> tuple[Path, int]:
        destination = self.upload_path(workspace_id, textbook_id, format_name)
        size = 0
        with destination.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                buffer.write(chunk)
        return destination, size

    def copy_upload(self, workspace_id: str, textbook_id: str, source: Path, format_name: str) -> Path:
        destination = self.upload_path(workspace_id, textbook_id, format_name)
        shutil.copy2(source, destination)
        return destination

    def report_markdown_path(self, workspace_id: str) -> Path:
        return self.workspace_generated_dir(workspace_id) / "整合报告.md"

    def report_pdf_path(self, workspace_id: str) -> Path:
        return self.workspace_generated_dir(workspace_id) / "整合报告.pdf"

    def stored_textbook_path(self, workspace_id: str, textbook_id: str, format_name: str) -> Path:
        return self.upload_path(workspace_id, textbook_id, format_name)

    def delete_textbook_file(self, workspace_id: str, textbook_id: str, format_name: str) -> None:
        path = self.stored_textbook_path(workspace_id, textbook_id, format_name)
        if path.exists():
            path.unlink()

    def delete_workspace_files(self, workspace_id: str) -> None:
        for path in [settings.upload_dir / workspace_id, settings.generated_dir / workspace_id]:
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)

    def cleanup_legacy_global_layout(self) -> None:
        for child in settings.upload_dir.iterdir():
            if child.is_file():
                child.unlink()
        for child in settings.generated_dir.iterdir():
            if child.is_file():
                child.unlink()


runtime_files = RuntimeFiles()
