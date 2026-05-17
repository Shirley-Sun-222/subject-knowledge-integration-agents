export type Textbook = {
  id: string;
  filename: string;
  title: string;
  format: string;
  size_bytes: number;
  total_pages: number;
  total_chars: number;
  status: string;
  error?: string | null;
  chapters?: Chapter[];
  chapter_count?: number;
  graph_node_count?: number;
  graph_edge_count?: number;
};

export type TaskSummary = {
  id: string;
  task_type: "parse_textbook" | "build_graph" | "run_integration" | "build_rag_index" | "build_report_pdf";
  resource_type: "textbook" | "system" | "report";
  resource_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  phase: string;
};

export type TaskDetail = TaskSummary & {
  progress_current: number;
  progress_total: number;
  truncated: boolean;
  error_summary?: string | null;
  metadata?: Record<string, unknown>;
  result_ref?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type Chapter = {
  id: string;
  textbook_id: string;
  title: string;
  page_start: number;
  page_end: number;
  char_count: number;
};

export type KnowledgeNode = {
  id: string;
  textbook_id: string;
  chapter_id: string;
  name: string;
  definition: string;
  category: string;
  page: number;
  source_excerpt: string;
  frequency: number;
  textbook_title?: string;
  chapter_title?: string;
  chapter_position?: number;
  page_start?: number;
  page_end?: number;
  sources?: string[];
  metadata?: Record<string, unknown>;
  decision_id?: string;
  decision_action?: string;
  decision_reason?: string;
};

export type KnowledgeEdge = {
  id: string;
  source: string;
  target: string;
  relation_type: string;
  description: string;
};

export type IntegrationDecision = {
  id: string;
  action: "merge" | "keep" | "remove";
  affected_nodes: string[];
  result_node?: string | null;
  reason: string;
  confidence: number;
};

export type IntegrationResult = {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  decisions: IntegrationDecision[];
  stats: {
    original_chars: number;
    integrated_chars: number;
    compression_ratio: number;
    decision_counts: Record<string, number>;
    node_count: number;
    edge_count: number;
  };
};

export type GraphResult = {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  metrics?: {
    token_estimate?: number;
    elapsed_ms?: number;
    processed_chapters?: number;
    total_chapters?: number;
    truncated?: boolean;
    fallback_chapters?: number;
    llm_chapters?: number;
    fast_chapters?: number;
    llm_configured?: boolean;
  };
};

export type RagResponse = {
  answer: string;
  citations: Array<{
    textbook: string;
    chapter: string;
    page: number;
    relevance_score: number;
    chunk_id: string;
    text: string;
  }>;
  source_chunks: string[];
  elapsed_ms: number;
  token_estimate: number;
};

export type UploadResponse = {
  uploads: Array<{
    textbook: Textbook;
    task: TaskSummary;
  }>;
};

export type SessionLlmConfigStatus = {
  configured: boolean;
  source: "session" | "global" | "none";
  model?: string | null;
  base_url?: string | null;
};

export type SessionWorkspaceStatus = {
  workspace_id: string;
  ttl_seconds: number;
};

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return (await response.json()) as T;
}

export const api = {
  async upload(files: FileList): Promise<UploadResponse> {
    const form = new FormData();
    Array.from(files).forEach((file) => form.append("files", file));
    return request("/api/textbooks/upload", { method: "POST", body: form });
  },
  async textbooks(): Promise<{ textbooks: Textbook[] }> {
    return request("/api/textbooks");
  },
  async deleteTextbook(textbookId: string): Promise<{ deleted: string }> {
    return request(`/api/textbooks/${textbookId}`, { method: "DELETE" });
  },
  async buildGraph(textbookId: string, options: { mode?: "preview" | "full"; maxChapters?: number } = {}): Promise<{ task: TaskSummary }> {
    const mode = options.mode || "preview";
    const maxChapters = options.maxChapters ?? 3;
    return request("/api/graphs/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(mode === "full" ? { textbook_id: textbookId, mode } : { textbook_id: textbookId, mode, max_chapters: maxChapters })
    });
  },
  async graph(textbookId: string): Promise<GraphResult> {
    return request(`/api/graphs/${textbookId}`);
  },
  async runIntegration(): Promise<{ task: TaskSummary }> {
    return request("/api/integration/run", { method: "POST" });
  },
  async integration(): Promise<IntegrationResult> {
    return request("/api/integration");
  },
  async indexRag(): Promise<{ task: TaskSummary }> {
    return request("/api/rag/index", { method: "POST" });
  },
  async ragStatus(): Promise<{ indexed_textbooks: number; chunk_count: number }> {
    return request("/api/rag/status");
  },
  async ask(question: string): Promise<RagResponse> {
    return request("/api/rag/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, top_k: 5 })
    });
  },
  async dialogue(message: string) {
    return request("/api/dialogue/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message })
    });
  },
  async report(): Promise<{ markdown: string }> {
    return request("/api/report/integration");
  },
  async buildReportPdf(): Promise<{ task: TaskSummary }> {
    return request("/api/report/pdf/build", { method: "POST" });
  },
  async sessionLlmStatus(): Promise<{ status: SessionLlmConfigStatus }> {
    return request("/api/session/llm-config/status");
  },
  async setSessionLlmConfig(payload: { base_url: string; api_key: string; model: string }): Promise<{ configured: boolean }> {
    return request("/api/session/llm-config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  },
  async clearSessionLlmConfig(): Promise<{ configured: boolean }> {
    return request("/api/session/llm-config", { method: "DELETE" });
  },
  async sessionWorkspace(): Promise<{ workspace: SessionWorkspaceStatus }> {
    return request("/api/session/workspace");
  },
  async tasks(filters: Partial<Pick<TaskDetail, "status" | "task_type" | "resource_type" | "resource_id">> = {}): Promise<{ tasks: TaskDetail[] }> {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value) {
        query.set(key, value);
      }
    });
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request(`/api/tasks${suffix}`);
  },
  async task(taskId: string): Promise<{ task: TaskDetail }> {
    return request(`/api/tasks/${taskId}`);
  }
};
