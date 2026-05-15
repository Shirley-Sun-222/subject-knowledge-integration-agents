from __future__ import annotations

import json
import time
from collections import Counter

from ..db import connect, json_dumps, row_to_dict
from ..schemas import Citation, RagQueryResponse
from ..services.embedding import embedding_service
from ..services.llm import llm_client
from ..utils.ids import new_id
from ..utils.text import chunk_text, estimate_tokens, tokenize

GENERIC_QUERY_TERMS = {
    "什么",
    "为何",
    "为什么",
    "如何",
    "怎么",
    "多少",
    "今天",
    "通常",
    "哪些",
    "用于",
    "解决",
    "介绍",
    "工作",
    "系统",
    "推荐",
    "三家",
    "餐厅",
    "意思",
    "区别",
    "联系",
    "共同",
    "主题",
}


def build_index() -> dict:
    with connect() as conn:
        chapters = [
            row_to_dict(row)
            for row in conn.execute(
                """
                SELECT c.*, t.title AS textbook_title
                FROM chapters c JOIN textbooks t ON t.id = c.textbook_id
                ORDER BY c.textbook_id, c.position
                """
            )
        ]
        conn.execute("DELETE FROM chunks")
        total = 0
        for chapter in chapters:
            chunks = chunk_text(chapter["content"], size=700, overlap=90)
            vectors = embedding_service.embed(chunks)
            for index, text in enumerate(chunks):
                conn.execute(
                    """
                    INSERT INTO chunks (id, textbook_id, chapter_id, chunk_index, text, page_start, char_count, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("chunk"),
                        chapter["textbook_id"],
                        chapter["id"],
                        index,
                        text,
                        chapter["page_start"],
                        len(text),
                        json_dumps(vectors[index]),
                    ),
                )
                total += 1
    return {"indexed_textbooks": _count_textbooks(), "chunk_count": total}


def query(question: str, top_k: int = 5) -> RagQueryResponse:
    started = time.perf_counter()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT chunks.*, textbooks.title AS textbook, chapters.title AS chapter
            FROM chunks
            JOIN textbooks ON textbooks.id = chunks.textbook_id
            JOIN chapters ON chapters.id = chunks.chapter_id
            """
        ).fetchall()
    if not rows:
        return RagQueryResponse(answer="当前知识库中未找到相关信息", citations=[], source_chunks=[], elapsed_ms=0, token_estimate=estimate_tokens([question]))

    chunks = [row_to_dict(row) for row in rows]
    vector_scores = _vector_scores(question, chunks)
    bm25_scores = _bm25_scores(question, chunks)
    ranked = []
    for chunk in chunks:
        vector_score = vector_scores.get(chunk["id"], 0.0)
        keyword_score = bm25_scores.get(chunk["id"], 0.0)
        if embedding_service.using_fallback and keyword_score <= 0:
            continue
        score = 0.68 * vector_score + 0.32 * keyword_score
        if score >= 0.12:
            ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    top = [(score, chunk) for score, chunk in ranked[:top_k] if score > 0]
    if not top or not _has_specific_query_overlap(question, top):
        return RagQueryResponse(answer="当前知识库中未找到相关信息", citations=[], source_chunks=[], elapsed_ms=int((time.perf_counter() - started) * 1000), token_estimate=estimate_tokens([question]))

    answer_result = _answer_with_context(question, top)
    citations = [
        Citation(
            textbook=chunk["textbook"],
            chapter=chunk["chapter"],
            page=chunk["page_start"],
            relevance_score=round(float(score), 4),
            chunk_id=chunk["id"],
            text=chunk["text"],
        )
        for score, chunk in top
    ]
    elapsed = int((time.perf_counter() - started) * 1000) + answer_result.get("elapsed_ms", 0)
    token_estimate = estimate_tokens([question, *(chunk["text"] for _, chunk in top), answer_result["answer"]])
    _record_metric("rag_elapsed_ms", elapsed, {"question": question})
    _record_metric("rag_token_estimate", token_estimate, {"question": question})
    return RagQueryResponse(
        answer=answer_result["answer"],
        citations=citations,
        source_chunks=[chunk["text"] for _, chunk in top],
        elapsed_ms=elapsed,
        token_estimate=token_estimate,
    )


def status() -> dict:
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM chunks").fetchone()["count"]
    return {"indexed_textbooks": _count_textbooks(), "chunk_count": count}


def _vector_scores(question: str, chunks: list[dict]) -> dict[str, float]:
    query_vector = embedding_service.embed([question])[0]
    scores: dict[str, float] = {}
    for chunk in chunks:
        try:
            vector = json.loads(chunk["embedding"]) if chunk["embedding"] else embedding_service.embed([chunk["text"]])[0]
        except json.JSONDecodeError:
            vector = embedding_service.embed([chunk["text"]])[0]
        scores[chunk["id"]] = _cosine(query_vector, vector)
    if scores:
        min_score = min(scores.values())
        max_score = max(scores.values())
        spread = max(max_score - min_score, 1e-9)
        scores = {key: (value - min_score) / spread for key, value in scores.items()}
    return scores


def _bm25_scores(question: str, chunks: list[dict]) -> dict[str, float]:
    query_terms = tokenize(question)
    if not query_terms:
        return {chunk["id"]: 0.0 for chunk in chunks}
    documents = [tokenize(chunk["text"]) for chunk in chunks]
    doc_freq = Counter(term for document in documents for term in set(document))
    scores = {}
    for chunk, document in zip(chunks, documents):
        term_counts = Counter(document)
        score = 0.0
        for term in query_terms:
            if term not in term_counts:
                continue
            idf = max(0.1, len(documents) / (1 + doc_freq[term]))
            score += term_counts[term] * idf
        scores[chunk["id"]] = score
    max_score = max(scores.values()) if scores else 0
    if max_score > 0:
        scores = {key: value / max_score for key, value in scores.items()}
    return scores


def _specific_query_terms(question: str) -> set[str]:
    return {
        term
        for term in tokenize(question)
        if len(term) >= 2 and term not in GENERIC_QUERY_TERMS
    }


def _has_specific_query_overlap(question: str, top: list[tuple[float, dict]]) -> bool:
    terms = _specific_query_terms(question)
    if not terms:
        return False
    for _, chunk in top:
        chunk_terms = set(tokenize(chunk["text"]))
        if len(terms & chunk_terms) >= 2:
            return True
    return False


def _answer_with_context(question: str, top: list[tuple[float, dict]]) -> dict:
    context = "\n\n".join(
        f"[{index}] {chunk['textbook']} / {chunk['chapter']} / 第 {chunk['page_start']} 页\n{chunk['text']}"
        for index, (_, chunk) in enumerate(top, start=1)
    )
    result = llm_client.complete_text(
        "你是严谨的教材 RAG 问答 Agent。只基于上下文回答，必须引用来源；找不到就回答当前知识库中未找到相关信息。",
        f"问题: {question}\n\n上下文:\n{context}",
    )
    if result.get("data"):
        return {"answer": result["data"], "elapsed_ms": result.elapsed_ms}
    first = top[0][1]
    answer = f"根据《{first['textbook']}》{first['chapter']}第 {first['page_start']} 页，{first['text'][:220]}..."
    answer += f"\n\n引用来源：[《{first['textbook']}》, {first['chapter']}, 第 {first['page_start']} 页]"
    return {"answer": answer, "elapsed_ms": 0}


def _count_textbooks() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) AS count FROM textbooks WHERE status = 'completed'").fetchone()["count"]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _record_metric(name: str, value: float, metadata: dict) -> None:
    from ..db import utc_now

    with connect() as conn:
        conn.execute(
            "INSERT INTO metrics (id, name, value, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            (new_id("metric"), name, value, json_dumps(metadata), utc_now()),
        )
