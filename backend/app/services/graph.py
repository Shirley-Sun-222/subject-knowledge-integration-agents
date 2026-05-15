from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable

from ..agents.extraction import KnowledgeExtractionAgent
from ..config import settings
from ..runtime.store import state_store
from ..runtime.tasks import TaskContext, task_runner

GraphProgress = Callable[[int, int, bool], None]


def enqueue_build_graph(textbook_id: str, max_chapters: int | None = None) -> tuple[dict, bool]:
    chapter_limit = _resolved_chapter_limit_for_textbook(textbook_id, max_chapters)
    cache_key = state_store.graph_cache_key(textbook_id, chapter_limit)
    cache = state_store.get_graph_cache(textbook_id)
    if cache is not None and cache["cache_key"] == cache_key and cache["chapter_limit"] == chapter_limit:
        task = state_store.create_finished_task(
            "build_graph",
            "textbook",
            textbook_id,
            phase="cache_hit",
            result_ref=textbook_id,
            truncated=chapter_limit < len(state_store.get_chapters(textbook_id)),
        )
        return task, False
    return task_runner.enqueue(
        "build_graph",
        "textbook",
        textbook_id,
        lambda context: _build_graph_task(context, textbook_id, max_chapters),
    )


def _build_graph_task(context: TaskContext, textbook_id: str, max_chapters: int | None = None) -> dict:
    chapters = state_store.get_chapters(textbook_id)
    original_chapter_count = len(chapters)
    chapter_limit = _resolve_chapter_limit(max_chapters)
    if chapter_limit > 0:
        chapters = chapters[:chapter_limit]
    processed_total = len(chapters)
    context.start("extracting_graph", progress_total=original_chapter_count)
    graph = build_graph(
        textbook_id,
        max_chapters=max_chapters,
        progress=lambda current, total, truncated: context.progress(
            phase="extracting_graph" if current < processed_total else "writing_graph",
            progress_current=current,
            progress_total=total,
            truncated=truncated,
        ),
    )
    return {
        "result_ref": textbook_id,
        "truncated": bool(graph.get("metrics", {}).get("truncated", len(chapters) < original_chapter_count)),
        "phase": "completed",
    }


def build_graph(textbook_id: str, max_chapters: int | None = None, progress: GraphProgress | None = None) -> dict:
    total_tokens = 0
    total_elapsed = 0
    fallback_chapters = 0
    llm_errors: list[str] = []
    chapters = state_store.get_chapters(textbook_id)
    original_chapter_count = len(chapters)
    chapter_limit = _resolve_chapter_limit(max_chapters)
    if chapter_limit > 0:
        chapters = chapters[:chapter_limit]

    extracted: list[tuple[list, list]] = []
    truncated = len(chapters) < original_chapter_count
    workers = _resolve_extract_workers(len(chapters))
    if workers == 1:
        for index, chapter in enumerate(chapters, start=1):
            nodes, edges, metrics = _extract_chapter(chapter, textbook_id)
            total_tokens += int(metrics.get("token_estimate", 0))
            total_elapsed += int(metrics.get("elapsed_ms", 0))
            if metrics.get("fallback"):
                fallback_chapters += 1
            error = metrics.get("error") or metrics.get("schema_error")
            if error:
                llm_errors.append(str(error)[:200])
            extracted.append((nodes, edges))
            if progress is not None:
                progress(index, original_chapter_count, truncated)
    else:
        by_position: dict[int, tuple[list, list]] = {}
        completed = 0
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="graph-extract") as executor:
            futures = {
                executor.submit(_extract_chapter, chapter, textbook_id): chapter["position"]
                for chapter in chapters
            }
            for future in as_completed(futures):
                nodes, edges, metrics = future.result()
                total_tokens += int(metrics.get("token_estimate", 0))
                total_elapsed += int(metrics.get("elapsed_ms", 0))
                if metrics.get("fallback"):
                    fallback_chapters += 1
                error = metrics.get("error") or metrics.get("schema_error")
                if error:
                    llm_errors.append(str(error)[:200])
                by_position[futures[future]] = (nodes, edges)
                completed += 1
                if progress is not None:
                    progress(completed, original_chapter_count, truncated)
        extracted = [by_position[position] for position in sorted(by_position)]

    flat_nodes = [node for nodes, _ in extracted for node in nodes]
    flat_edges = [edge for _, edges in extracted for edge in edges]
    state_store.replace_graph_with_cache(
        textbook_id,
        flat_nodes,
        flat_edges,
        cache_key=state_store.graph_cache_key(textbook_id, len(chapters)),
        chapter_limit=len(chapters),
    )
    graph = state_store.get_graph(textbook_id)
    graph["metrics"] = {
        "token_estimate": total_tokens,
        "elapsed_ms": total_elapsed,
        "processed_chapters": len(chapters),
        "total_chapters": original_chapter_count,
        "truncated": truncated,
        "fallback_chapters": fallback_chapters,
        "llm_chapters": len(chapters) - fallback_chapters,
        "llm_configured": bool(settings.llm_base_url and settings.llm_api_key),
        "llm_errors": llm_errors[:5],
    }
    return graph


def _resolve_chapter_limit(max_chapters: int | None = None) -> int:
    configured = settings.graph_max_chapters
    if max_chapters is None:
        return configured
    if configured <= 0:
        return max_chapters
    return min(configured, max_chapters)


def _resolved_chapter_limit_for_textbook(textbook_id: str, max_chapters: int | None = None) -> int:
    chapters = state_store.get_chapters(textbook_id)
    limit = _resolve_chapter_limit(max_chapters)
    if limit <= 0:
        return len(chapters)
    return min(limit, len(chapters))


def _resolve_extract_workers(chapter_count: int) -> int:
    configured = max(settings.graph_extract_workers, 1)
    if chapter_count <= 1:
        return 1
    return min(configured, chapter_count)


def _extract_chapter(chapter: dict, textbook_id: str):
    agent = KnowledgeExtractionAgent()
    return agent.extract(chapter, textbook_id)


def get_graph(textbook_id: str) -> dict:
    return state_store.get_graph(textbook_id)


def get_all_graph_nodes() -> list[dict]:
    return state_store.get_all_graph_nodes()
