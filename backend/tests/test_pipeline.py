from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pytest
from backend.app.agents.compression import CompressionPlannerAgent
from backend.app.agents.extraction import KnowledgeExtractionAgent
from backend.app.config import settings
from backend.app.services import parser
from backend.app.services.llm import LlmResult, llm_client
from backend.app.services.parser import parse_textbook, parse_textbook_preview
from backend.app.utils.text import chunk_text, split_chapters, tokenize


class PipelineTest(unittest.TestCase):
    def test_split_chapters_detects_chinese_chapters(self) -> None:
        text = "第 1 章 绪论\n数据结构是研究数据组织的学科。\n第 2 章 排序\n排序算法包括插入排序。"
        chapters = split_chapters(text, title="数据结构", total_pages=20)
        self.assertEqual(len(chapters), 2)
        self.assertTrue(chapters[0]["title"].startswith("第 1 章"))
        self.assertGreaterEqual(chapters[1]["page_start"], chapters[0]["page_start"])

    def test_chunk_text_uses_overlap(self) -> None:
        text = "数据结构。" * 240
        chunks = chunk_text(text, size=120, overlap=20)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(chunks))
        self.assertLessEqual(max(len(chunk) for chunk in chunks), 125)

    def test_tokenize_supports_chinese_terms(self) -> None:
        tokens = tokenize("排序算法包括快速排序和归并排序。")
        self.assertIn("排序", tokens)
        self.assertIn("算法", tokens)

    def test_parse_markdown_textbook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book_123.md"
            path.write_text("# 第 1 章 绪论\n知识图谱用于表示概念关系。", encoding="utf-8")
            parsed = parse_textbook(path, "原始教材名称.md")
        self.assertEqual(parsed["format"], "md")
        self.assertEqual(parsed["title"], "原始教材名称")
        self.assertGreater(parsed["total_chars"], 0)
        self.assertTrue(parsed["chapters"])

    def test_compression_planner_enforces_ratio(self) -> None:
        nodes = [
            [{"id": f"node_{index}", "name": f"概念{index}", "definition": "定义" * 80, "source_excerpt": "原文" * 80}]
            for index in range(20)
        ]
        decisions, stats = CompressionPlannerAgent().plan(nodes, original_chars=2000)
        self.assertTrue(decisions)
        self.assertLessEqual(stats["compression_ratio"], 0.3)
        self.assertTrue(any(decision.action == "remove" for decision in decisions))


def test_parse_pdf_uses_ocr_when_page_has_no_extractable_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "scanned.pdf"
    document = fitz.open()
    document.new_page()
    document.save(path)
    document.close()

    original_ocr_enabled = settings.ocr_enabled
    original_ocr_max_pages = settings.ocr_max_pages
    object.__setattr__(settings, "ocr_enabled", True)
    object.__setattr__(settings, "ocr_max_pages", 1)
    monkeypatch.setattr(parser, "_ocr_pdf_page", lambda page: "第 1 章 OCR\n排序算法用于处理教材扫描页中的知识点。")

    try:
        parsed = parse_textbook(path, "扫描教材.pdf")
    finally:
        object.__setattr__(settings, "ocr_enabled", original_ocr_enabled)
        object.__setattr__(settings, "ocr_max_pages", original_ocr_max_pages)

    assert parsed["title"] == "扫描教材"
    assert parsed["total_pages"] == 1
    assert parsed["total_chars"] > 20
    assert parsed["chapters"][0]["title"].startswith("第 1 章")


def test_llm_client_returns_error_result_when_provider_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    original_llm_base_url = settings.llm_base_url
    original_llm_api_key = settings.llm_api_key
    object.__setattr__(settings, "llm_base_url", "https://llm.example.test/v1")
    object.__setattr__(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_client, "_post", lambda payload, config: (_ for _ in ()).throw(RuntimeError("provider unavailable")))

    try:
        result = llm_client.complete_json("system", "user")
    finally:
        object.__setattr__(settings, "llm_base_url", original_llm_base_url)
        object.__setattr__(settings, "llm_api_key", original_llm_api_key)

    assert result["data"] is None
    assert result["error"] == "provider unavailable"
    assert result["elapsed_ms"] >= 0
    assert result["token_estimate"] > 0


def test_extraction_fallback_metrics_include_llm_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    chapter = {
        "id": "chapter_test",
        "title": "第 1 章 排序",
        "page_start": 1,
        "content": "排序算法包括快速排序和归并排序。",
    }

    def fake_complete_json(system: str, user: str, workspace_id: str = "global") -> dict:
        return LlmResult({"data": {"nodes": [{}], "edges": []}, "elapsed_ms": 12, "token_estimate": 34})

    monkeypatch.setattr(llm_client, "complete_json", fake_complete_json)

    nodes, edges, metrics = KnowledgeExtractionAgent().extract(chapter, "book_test")

    assert nodes
    assert edges
    assert metrics["fallback"] is True
    assert metrics["elapsed_ms"] == 12
    assert "schema_error" in metrics


def test_parse_pdf_reports_progress_and_detects_pdf_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "digital.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "第 1 章 绪论\n知识图谱用于表示概念关系。")
    document.save(path)
    document.close()

    progress_events: list[tuple[str, int, int]] = []
    parsed = parse_textbook(path, path.name, progress=lambda phase, current, total: progress_events.append((phase, current, total)))

    assert parsed["total_pages"] == 1
    assert parsed["chapters"]
    assert any(event[0] == "detecting_pdf_mode" for event in progress_events)
    assert any(event[0] == "reading_pdf_pages" for event in progress_events)


def test_parse_pdf_prefers_top_level_toc_chapters(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "toc.pdf"
    document = fitz.open()
    document.new_page().insert_text((72, 72), "cover page")
    document.new_page().insert_text((72, 72), "chapter one overview\nacid base balance keeps body fluids stable.")
    document.new_page().insert_text((72, 72), "section one cells\ncells are the basic unit of life.")
    document.new_page().insert_text((72, 72), "chapter two immunity\nimmune defense protects the body.")
    document.set_toc(
        [
            [1, "封面页", 1],
            [1, "第一章 绪论", 2],
            [2, "第一节 细胞", 3],
            [1, "第二章 免疫", 4],
        ]
    )
    document.save(path)
    document.close()

    parsed = parse_textbook(path, path.name)

    assert len(parsed["chapters"]) == 2
    assert parsed["chapters"][0]["title"] == "第一章 绪论"
    assert parsed["chapters"][0]["page_start"] == 2
    assert "cells are the basic unit of life" in parsed["chapters"][0]["content"]
    assert parsed["chapters"][1]["title"] == "第二章 免疫"


def test_parse_pdf_scanned_mode_respects_ocr_max_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "scan-all.pdf"
    document = fitz.open()
    document.new_page()
    document.new_page()
    document.save(path)
    document.close()

    calls: list[int] = []
    monkeypatch.setattr(parser, "_ocr_pdf_page", lambda page: calls.append(page.number) or f"第 {page.number + 1} 页 OCR 文本，包含足够多的教材教学内容用于解析。")
    original_ocr_max_pages = settings.ocr_max_pages
    object.__setattr__(settings, "ocr_max_pages", 1)

    try:
        parsed = parse_textbook(path, path.name)
    finally:
        object.__setattr__(settings, "ocr_max_pages", original_ocr_max_pages)

    assert parsed["total_pages"] == 2
    assert sorted(calls) == [0]


def test_parse_pdf_preview_limits_to_three_teaching_chapters_and_three_pages(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "preview.pdf"
    document = fitz.open()
    toc = []
    page_number = 1
    for chapter in range(1, 5):
        toc.append([1, f"第 {chapter} 章 教学章{chapter}", page_number])
        for chapter_page in range(1, 5):
            page = document.new_page()
            page.insert_text((72, 72), f"第 {chapter} 章 第 {chapter_page} 页\n核心教学内容 {chapter}-{chapter_page}。")
            page_number += 1
    document.set_toc(toc)
    document.save(path)
    document.close()

    parsed = parse_textbook_preview(path, path.name)

    assert parsed["parse_scope"] == "preview"
    assert len(parsed["chapters"]) == 3
    assert all(chapter["page_end"] - chapter["page_start"] <= 2 for chapter in parsed["chapters"])
    assert "核心教学内容 1-4" not in parsed["chapters"][0]["content"]
    assert parsed["chapters"][0]["title"] == "第 1 章 教学章1"


def test_parse_pdf_preview_scanned_ocr_budget_is_nine_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "preview-scan.pdf"
    document = fitz.open()
    toc = []
    page_number = 1
    for chapter in range(1, 5):
        toc.append([1, f"第 {chapter} 章 扫描章{chapter}", page_number])
        for _ in range(3):
            document.new_page()
            page_number += 1
    document.set_toc(toc)
    document.save(path)
    document.close()

    calls: list[int] = []
    monkeypatch.setattr(parser, "_ocr_pdf_page", lambda page: calls.append(page.number) or f"第 {page.number + 1} 页 OCR 教学内容")

    parsed = parse_textbook_preview(path, path.name)

    assert parsed["parse_scope"] == "preview"
    assert len(parsed["chapters"]) == 3
    assert len(calls) == 9
    assert max(calls) == 8


if __name__ == "__main__":
    unittest.main()
