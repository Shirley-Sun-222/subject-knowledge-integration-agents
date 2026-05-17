from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr


TaskStatus = Literal["queued", "running", "succeeded", "failed"]
TaskType = Literal[
    "parse_textbook",
    "preview_parse_textbook",
    "full_parse_textbook",
    "build_graph",
    "run_integration",
    "build_rag_index",
    "build_report_pdf",
]
ResourceType = Literal["textbook", "system", "report"]


class Textbook(BaseModel):
    id: str
    filename: str
    title: str
    format: str
    size_bytes: int
    total_pages: int = 0
    total_chars: int = 0
    status: str
    error: str | None = None
    parse_stage: str = "full"
    preview_ready: bool = True
    full_ready: bool = True
    parse_scope: str = "full"
    full_parse_error: str | None = None
    graph_scope: str = "full"
    graph_stale_after_full_parse: bool = False
    created_at: str


class Chapter(BaseModel):
    id: str
    textbook_id: str
    title: str
    page_start: int
    page_end: int
    content: str
    char_count: int
    position: int


class Chunk(BaseModel):
    id: str
    textbook_id: str
    chapter_id: str
    chunk_index: int
    text: str
    page_start: int
    char_count: int
    embedding: str | None = None


class KnowledgeNode(BaseModel):
    id: str
    textbook_id: str
    chapter_id: str
    name: str
    definition: str
    category: str
    page: int
    source_excerpt: str
    frequency: int = 1
    metadata: dict = Field(default_factory=dict)


class KnowledgeEdge(BaseModel):
    id: str
    textbook_id: str
    source: str
    target: str
    relation_type: Literal["prerequisite", "parallel", "contains", "applies_to"]
    description: str


class IntegrationDecision(BaseModel):
    id: str
    action: Literal["merge", "keep", "remove"]
    affected_nodes: list[str]
    result_node: str | None
    reason: str
    confidence: float
    created_at: str


class Citation(BaseModel):
    textbook: str
    chapter: str
    page: int
    relevance_score: float
    chunk_id: str
    text: str


class RagQueryRequest(BaseModel):
    question: str
    top_k: int = 5


class RagQueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    source_chunks: list[str]
    elapsed_ms: int
    token_estimate: int


class DialogueRequest(BaseModel):
    message: str


class DialogueResponse(BaseModel):
    reply: str
    updated_decision: IntegrationDecision | None = None
    graph_updated: bool = False


class TaskSummary(BaseModel):
    id: str
    task_type: TaskType
    resource_type: ResourceType
    resource_id: str
    status: TaskStatus
    phase: str


class TaskDetail(TaskSummary):
    progress_current: int = 0
    progress_total: int = 0
    truncated: bool = False
    error_summary: str | None = None
    metadata: dict = Field(default_factory=dict)
    result_ref: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class SessionLlmConfigRequest(BaseModel):
    base_url: str
    api_key: SecretStr
    model: str


class SessionLlmConfigStatus(BaseModel):
    configured: bool
    source: Literal["session", "global", "none"]
    model: str | None = None
    base_url: str | None = None


class SessionWorkspaceStatus(BaseModel):
    workspace_id: str
    ttl_seconds: int
