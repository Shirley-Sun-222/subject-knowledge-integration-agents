from __future__ import annotations

from types import SimpleNamespace

from backend.app.services.rag import _has_specific_query_overlap
from scripts.run_rag_benchmark import evaluate_response


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
