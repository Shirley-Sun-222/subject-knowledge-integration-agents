from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db import init_db
from backend.app.services.embedding import embedding_service
from backend.app.services import rag


QUESTIONS: list[dict[str, Any]] = [
    {"id": "fact_sort_01", "category": "fact", "question": "快速排序的核心思想是什么？", "should_cite": True, "expected_source_hints": ["快速排序", "排序", "分治"], "expected_answer_terms": ["分治", "排序"]},
    {"id": "fact_sort_02", "category": "fact", "question": "归并排序为什么属于分治算法？", "should_cite": True, "expected_source_hints": ["归并排序", "排序", "分治"], "expected_answer_terms": ["分治", "归并"]},
    {"id": "fact_sort_03", "category": "fact", "question": "插入排序通常如何处理待排序元素？", "should_cite": True, "expected_source_hints": ["插入排序", "排序"], "expected_answer_terms": ["插入", "排序"]},
    {"id": "fact_sort_04", "category": "fact", "question": "选择排序和冒泡排序都解决什么问题？", "should_cite": True, "expected_source_hints": ["选择排序", "冒泡排序", "排序"], "expected_answer_terms": ["排序"]},
    {"id": "fact_ds_01", "category": "fact", "question": "数组适合用来表示什么类型的数据集合？", "should_cite": True, "expected_source_hints": ["数组", "线性"], "expected_answer_terms": ["数组"]},
    {"id": "fact_ds_02", "category": "fact", "question": "链表和数组在存储结构上有什么区别？", "should_cite": True, "expected_source_hints": ["链表", "数组"], "expected_answer_terms": ["链表", "数组"]},
    {"id": "fact_ds_03", "category": "fact", "question": "栈的先进后出特性是什么意思？", "should_cite": True, "expected_source_hints": ["栈", "先进后出", "后进先出"], "expected_answer_terms": ["栈"]},
    {"id": "fact_ds_04", "category": "fact", "question": "队列的先进先出特性是什么意思？", "should_cite": True, "expected_source_hints": ["队列", "先进先出"], "expected_answer_terms": ["队列"]},
    {"id": "fact_tree_01", "category": "fact", "question": "二叉树节点之间通常有什么父子关系？", "should_cite": True, "expected_source_hints": ["二叉树", "树"], "expected_answer_terms": ["节点", "树"]},
    {"id": "fact_tree_02", "category": "fact", "question": "二叉搜索树为什么能支持较快查找？", "should_cite": True, "expected_source_hints": ["二叉搜索树", "查找"], "expected_answer_terms": ["查找"]},
    {"id": "fact_graph_01", "category": "fact", "question": "图由哪些基本元素组成？", "should_cite": True, "expected_source_hints": ["图", "顶点", "边"], "expected_answer_terms": ["顶点", "边"]},
    {"id": "fact_graph_02", "category": "fact", "question": "最短路径算法用于解决什么问题？", "should_cite": True, "expected_source_hints": ["最短路径", "路径", "图"], "expected_answer_terms": ["路径"]},
    {"id": "compare_sort_01", "category": "compare", "question": "快速排序和归并排序的共同点是什么？", "should_cite": True, "expected_source_hints": ["快速排序", "归并排序", "分治"], "expected_answer_terms": ["分治", "排序"]},
    {"id": "compare_ds_01", "category": "compare", "question": "栈和队列的访问顺序有什么不同？", "should_cite": True, "expected_source_hints": ["栈", "队列"], "expected_answer_terms": ["栈", "队列"]},
    {"id": "compare_ds_02", "category": "compare", "question": "数组和链表在插入删除操作上有什么差异？", "should_cite": True, "expected_source_hints": ["数组", "链表", "插入", "删除"], "expected_answer_terms": ["数组", "链表"]},
    {"id": "compare_graph_tree_01", "category": "compare", "question": "树和图在结构上有什么联系和区别？", "should_cite": True, "expected_source_hints": ["树", "图"], "expected_answer_terms": ["树", "图"]},
    {"id": "reason_complexity_01", "category": "reason", "question": "为什么算法分析要关注时间复杂度？", "should_cite": True, "expected_source_hints": ["时间复杂度", "算法分析", "复杂度"], "expected_answer_terms": ["复杂度", "时间"]},
    {"id": "reason_recursion_01", "category": "reason", "question": "递归算法为什么需要终止条件？", "should_cite": True, "expected_source_hints": ["递归", "终止"], "expected_answer_terms": ["递归"]},
    {"id": "reason_hash_01", "category": "reason", "question": "散列表为什么能实现较快的查找？", "should_cite": True, "expected_source_hints": ["散列表", "哈希", "查找"], "expected_answer_terms": ["查找"]},
    {"id": "reason_heap_01", "category": "reason", "question": "堆结构为什么常用于优先队列？", "should_cite": True, "expected_source_hints": ["堆", "优先队列"], "expected_answer_terms": ["堆", "优先"]},
    {"id": "cross_book_01", "category": "cross_textbook", "question": "多本教材中排序算法通常会覆盖哪些共同主题？", "should_cite": True, "expected_source_hints": ["排序", "快速排序", "归并排序"], "expected_answer_terms": ["排序"]},
    {"id": "cross_book_02", "category": "cross_textbook", "question": "多本教材对线性数据结构通常会介绍哪些概念？", "should_cite": True, "expected_source_hints": ["数组", "链表", "栈", "队列"], "expected_answer_terms": ["数组", "链表"]},
    {"id": "reject_01", "category": "out_of_domain", "question": "免疫系统如何工作？", "should_cite": False, "expected_source_hints": [], "expected_answer_terms": []},
    {"id": "reject_02", "category": "out_of_domain", "question": "今天美元兑人民币汇率是多少？", "should_cite": False, "expected_source_hints": [], "expected_answer_terms": []},
    {"id": "reject_03", "category": "out_of_domain", "question": "请推荐三家北京烤鸭餐厅。", "should_cite": False, "expected_source_hints": [], "expected_answer_terms": []},
]


def field(value: Any, name: str, default: Any = "") -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def citation_blob(citations: list[Any]) -> str:
    parts: list[str] = []
    for citation in citations:
        parts.extend(
            str(field(citation, name, ""))
            for name in ("textbook", "chapter", "text")
        )
    return "\n".join(parts)


def evaluate_response(item: dict[str, Any], response: Any) -> dict[str, Any]:
    answer = str(field(response, "answer", ""))
    citations = list(field(response, "citations", []))
    should_cite = bool(item.get("should_cite", True))
    source_hints = list(item.get("expected_source_hints", []))
    answer_terms = list(item.get("expected_answer_terms", []))
    source_text = citation_blob(citations)
    has_citation = bool(citations)
    citation_matches_source_hint = any(hint and hint in source_text for hint in source_hints) if source_hints else None
    answer_matches_expected_terms = any(term and term in answer for term in answer_terms) if answer_terms else None
    correctly_rejected = not should_cite and not has_citation and "未找到" in answer
    if should_cite:
        passed = has_citation
        if citation_matches_source_hint is not None:
            passed = passed and citation_matches_source_hint
        if answer_matches_expected_terms is not None:
            passed = passed and answer_matches_expected_terms
    else:
        passed = correctly_rejected
    return {
        "id": item["id"],
        "category": item["category"],
        "question": item["question"],
        "should_cite": should_cite,
        "has_citation": has_citation,
        "citation_count": len(citations),
        "citation_matches_source_hint": citation_matches_source_hint,
        "answer_matches_expected_terms": answer_matches_expected_terms,
        "correctly_rejected": correctly_rejected,
        "passed": bool(passed),
    }


def ratio(rows: list[dict[str, Any]], key: str) -> float:
    eligible = [row for row in rows if row.get(key) is not None]
    return (sum(1 for row in eligible if row[key]) / len(eligible)) if eligible else 0.0


def main() -> None:
    init_db()
    embedding_service._model_failed = True
    embedding_service._model = None
    output = []
    started = time.perf_counter()
    status = rag.status()
    for item in QUESTIONS:
        response = rag.query(item["question"], top_k=5)
        evaluation = evaluate_response(item, response)
        output.append(
            {
                **evaluation,
                "question": item["question"],
                "answer": response.answer,
                "elapsed_ms": response.elapsed_ms,
                "token_estimate": response.token_estimate,
                "citations": [
                    {
                        "textbook": citation.textbook,
                        "chapter": citation.chapter,
                        "page": citation.page,
                        "relevance_score": citation.relevance_score,
                    }
                    for citation in response.citations
                ],
            }
        )
    total_elapsed_ms = int((time.perf_counter() - started) * 1000)
    positive = [row for row in output if row["should_cite"]]
    negative = [row for row in output if not row["should_cite"]]
    summary = {
        "status": status,
        "question_count": len(QUESTIONS),
        "positive_question_count": len(positive),
        "negative_question_count": len(negative),
        "total_elapsed_ms": total_elapsed_ms,
        "avg_elapsed_ms": int(sum(row["elapsed_ms"] for row in output) / len(output)) if output else 0,
        "total_token_estimate": sum(row["token_estimate"] for row in output),
        "pass_rate": ratio(output, "passed"),
        "citation_presence_score": ratio(positive, "has_citation"),
        "source_hint_score": ratio(positive, "citation_matches_source_hint"),
        "answer_term_score": ratio(positive, "answer_matches_expected_terms"),
        "rejection_score": ratio(negative, "correctly_rejected"),
        "category_pass_rate": {
            category: ratio([row for row in output if row["category"] == category], "passed")
            for category in sorted({row["category"] for row in output})
        },
        "results": output,
    }
    path = Path("data/generated/rag-benchmark.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
