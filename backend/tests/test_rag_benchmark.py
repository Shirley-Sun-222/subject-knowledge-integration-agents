from __future__ import annotations

import json
from collections import Counter
from types import SimpleNamespace

from backend.app.services.rag import _has_specific_query_overlap
from scripts.run_p2_rag_experiments import choose_best_chunk_size
from scripts.run_rag_benchmark import evaluate_response, load_questions


def test_benchmark_evaluation_passes_cited_domain_answer() -> None:
    item = {
        "id": "fact_sort_01",
        "category": "fact",
        "question": "快速排序的核心思想是什么？",
        "should_cite": True,
        "expected_source_hints": ["快速排序", "分治"],
        "expected_answer_terms": ["分治"],
    }
    response = SimpleNamespace(
        answer="快速排序通常采用分治思想。",
        citations=[
            SimpleNamespace(
                textbook="数据结构与算法图解",
                chapter="排序算法",
                text="快速排序采用分治思想处理排序问题。",
            )
        ],
    )

    result = evaluate_response(item, response)

    assert result["passed"] is True
    assert result["has_citation"] is True
    assert result["citation_matches_source_hint"] is True
    assert result["answer_matches_expected_terms"] is True


def test_benchmark_evaluation_passes_rejected_out_of_domain_answer() -> None:
    item = {
        "id": "reject_01",
        "category": "out_of_domain",
        "question": "免疫系统如何工作？",
        "should_cite": False,
        "expected_source_hints": [],
        "expected_answer_terms": [],
    }
    response = SimpleNamespace(answer="当前知识库中未找到相关信息", citations=[])

    result = evaluate_response(item, response)

    assert result["passed"] is True
    assert result["correctly_rejected"] is True


def test_benchmark_evaluation_fails_when_source_hint_is_missing() -> None:
    item = {
        "id": "fact_graph_01",
        "category": "fact",
        "question": "图由哪些基本元素组成？",
        "should_cite": True,
        "expected_source_hints": ["图", "顶点", "边"],
        "expected_answer_terms": ["顶点"],
    }
    response = SimpleNamespace(
        answer="图由顶点和边组成。",
        citations=[{"textbook": "数据结构", "chapter": "排序算法", "text": "快速排序采用分治思想。"}],
    )

    result = evaluate_response(item, response)

    assert result["passed"] is False
    assert result["citation_matches_source_hint"] is False


def test_rag_overlap_guard_rejects_single_incidental_match() -> None:
    top = [(0.8, {"text": "航班票价为 220 美元，图算法可以计算最低价格。"})]

    assert _has_specific_query_overlap("今天美元兑人民币汇率是多少？", top) is False


def test_rag_overlap_guard_allows_domain_query() -> None:
    top = [(0.8, {"text": "快速排序采用分治思想处理排序问题，平均情况下效率较好。"})]

    assert _has_specific_query_overlap("快速排序的核心思想是什么？", top) is True


def test_external_question_set_loads(tmp_path) -> None:
    path = tmp_path / "questions.json"
    path.write_text(json.dumps([{"id": "q1", "category": "fact", "question": "什么是稳态？"}], ensure_ascii=False), encoding="utf-8")

    questions = load_questions(path)

    assert questions[0]["id"] == "q1"
    assert questions[0]["question"] == "什么是稳态？"


def test_choose_best_chunk_size_prefers_quality_then_cost() -> None:
    best = choose_best_chunk_size(
        [
            {"chunk_size": 300, "pass_rate": 0.70, "source_hint_score": 0.80, "rejection_score": 1.0, "avg_elapsed_ms": 120},
            {"chunk_size": 500, "pass_rate": 0.70, "source_hint_score": 0.82, "rejection_score": 1.0, "avg_elapsed_ms": 150},
            {"chunk_size": 700, "pass_rate": 0.68, "source_hint_score": 0.90, "rejection_score": 1.0, "avg_elapsed_ms": 90},
        ]
    )

    assert best == 500


def test_medical_question_set_keeps_25_questions_and_five_categories() -> None:
    questions = load_questions("scripts/benchmark_sets/medical_official_questions.json")
    counts = Counter(question["category"] for question in questions)

    assert len(questions) == 25
    assert counts == {
        "fact": 5,
        "compare": 5,
        "reason": 5,
        "cross_textbook": 5,
        "out_of_domain": 5,
    }
