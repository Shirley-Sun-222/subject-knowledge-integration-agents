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
  sources?: string[];
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

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return (await response.json()) as T;
}

export const api = {
  async upload(files: FileList): Promise<{ textbooks: Textbook[] }> {
    const form = new FormData();
    Array.from(files).forEach((file) => form.append("files", file));
    return request("/api/textbooks/upload", { method: "POST", body: form });
  },
  async textbooks(): Promise<{ textbooks: Textbook[] }> {
    return request("/api/textbooks");
  },
  async buildGraph(textbookId: string): Promise<{ nodes: KnowledgeNode[]; edges: KnowledgeEdge[] }> {
    return request("/api/graphs/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ textbook_id: textbookId })
    });
  },
  async graph(textbookId: string): Promise<{ nodes: KnowledgeNode[]; edges: KnowledgeEdge[] }> {
    return request(`/api/graphs/${textbookId}`);
  },
  async runIntegration(): Promise<IntegrationResult> {
    return request("/api/integration/run", { method: "POST" });
  },
  async integration(): Promise<IntegrationResult> {
    return request("/api/integration");
  },
  async indexRag(): Promise<{ indexed_textbooks: number; chunk_count: number }> {
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
  }
};

