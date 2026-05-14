from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.agents.compression import CompressionPlannerAgent
from backend.app.services.parser import parse_textbook
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
            path = Path(directory) / "demo.md"
            path.write_text("# 第 1 章 绪论\n知识图谱用于表示概念关系。", encoding="utf-8")
            parsed = parse_textbook(path, "demo.md")
        self.assertEqual(parsed["format"], "md")
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


if __name__ == "__main__":
    unittest.main()
