import React from "react";
import ReactDOM from "react-dom/client";
import { Download, FileText, GitMerge, MessageSquare, Network, Play, Search, UploadCloud } from "lucide-react";
import { GraphCanvas } from "./components/GraphCanvas";
import { api, IntegrationResult, KnowledgeNode, RagResponse, Textbook } from "./lib/api";
import "./styles.css";

type Tab = "integration" | "rag" | "dialogue" | "report";

function App() {
  const [textbooks, setTextbooks] = React.useState<Textbook[]>([]);
  const [graphNodes, setGraphNodes] = React.useState<KnowledgeNode[]>([]);
  const [graphEdges, setGraphEdges] = React.useState<any[]>([]);
  const [integration, setIntegration] = React.useState<IntegrationResult | null>(null);
  const [selectedNode, setSelectedNode] = React.useState<KnowledgeNode | null>(null);
  const [query, setQuery] = React.useState("");
  const [activeTab, setActiveTab] = React.useState<Tab>("integration");
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const [ragQuestion, setRagQuestion] = React.useState("");
  const [ragAnswer, setRagAnswer] = React.useState<RagResponse | null>(null);
  const [ragStatus, setRagStatus] = React.useState({ indexed_textbooks: 0, chunk_count: 0 });
  const [dialogueMessage, setDialogueMessage] = React.useState("");
  const [dialogueReply, setDialogueReply] = React.useState("");
  const [report, setReport] = React.useState("");

  React.useEffect(() => {
    refresh();
  }, []);

  async function run<T>(label: string, action: () => Promise<T>): Promise<T | undefined> {
    setBusy(label);
    setError("");
    try {
      return await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return undefined;
    } finally {
      setBusy("");
    }
  }

  async function refresh() {
    const result = await api.textbooks();
    setTextbooks(result.textbooks);
    setRagStatus(await api.ragStatus());
    const current = await api.integration();
    setIntegration(current);
    if (current.nodes.length) {
      setGraphNodes(current.nodes);
      setGraphEdges(current.edges);
    }
  }

  async function upload(files: FileList | null) {
    if (!files?.length) {
      return;
    }
    await run("上传并解析教材", async () => {
      await api.upload(files);
      await refresh();
    });
  }

  async function buildGraph(textbookId: string) {
    const result = await run("构建单本图谱", () => api.buildGraph(textbookId));
    if (result) {
      setGraphNodes(result.nodes);
      setGraphEdges(result.edges);
      await refresh();
    }
  }

  async function integrate() {
    const result = await run("跨教材整合", () => api.runIntegration());
    if (result) {
      setIntegration(result);
      setGraphNodes(result.nodes);
      setGraphEdges(result.edges);
    }
  }

  async function indexRag() {
    const result = await run("建立 RAG 索引", () => api.indexRag());
    if (result) {
      setRagStatus(result);
    }
  }

  async function ask() {
    if (!ragQuestion.trim()) {
      return;
    }
    const result = await run("RAG 问答", () => api.ask(ragQuestion));
    if (result) {
      setRagAnswer(result);
    }
  }

  async function sendDialogue() {
    if (!dialogueMessage.trim()) {
      return;
    }
    const result = await run("处理教师反馈", () => api.dialogue(dialogueMessage));
    if (result) {
      setDialogueReply((result as any).reply);
      await integrate();
    }
  }

  async function loadReport() {
    const result = await run("生成整合报告", () => api.report());
    if (result) {
      setReport(result.markdown);
    }
  }

  const visibleNodes = React.useMemo(() => {
    if (!query.trim()) {
      return graphNodes.slice(0, 180);
    }
    return graphNodes.filter((node) => node.name.includes(query) || node.definition.includes(query)).slice(0, 180);
  }, [graphNodes, query]);
  const visibleIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = graphEdges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target));

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <header>
          <div className="brand-mark"><Network size={22} /></div>
          <div>
            <h1>学科知识整合智能体</h1>
            <p>P0 全链路 + 关键 P1</p>
          </div>
        </header>

        <label className="upload-zone">
          <UploadCloud size={24} />
          <span>拖拽或选择教材文件</span>
          <input type="file" multiple accept=".pdf,.md,.markdown,.txt,.docx" onChange={(event) => upload(event.target.files)} />
        </label>

        <section className="list-panel">
          <h2>教材管理</h2>
          {textbooks.length === 0 && <p className="muted">尚未上传教材。</p>}
          {textbooks.map((book) => (
            <article key={book.id} className="textbook-row">
              <div>
                <strong>{book.title}</strong>
                <span>{book.format.toUpperCase()} · {Math.round(book.size_bytes / 1024)} KB · {book.total_chars} 字</span>
                <span className={`status ${book.status}`}>{book.status}</span>
              </div>
              <button onClick={() => buildGraph(book.id)} disabled={book.status !== "completed" || !!busy} aria-label="构建图谱">
                <Play size={16} />
              </button>
            </article>
          ))}
        </section>

        <section className="stats-grid">
          <div><span>教材</span><strong>{textbooks.length}</strong></div>
          <div><span>节点</span><strong>{graphNodes.length}</strong></div>
          <div><span>Chunk</span><strong>{ragStatus.chunk_count}</strong></div>
          <div><span>压缩</span><strong>{integration ? `${(integration.stats.compression_ratio * 100).toFixed(1)}%` : "-"}</strong></div>
        </section>
      </aside>

      <section className="workspace">
        <div className="toolbar">
          <div className="search-box">
            <Search size={17} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索知识点" />
          </div>
          <button onClick={integrate} disabled={!!busy}><GitMerge size={16} />跨教材整合</button>
          <button onClick={indexRag} disabled={!!busy}><FileText size={16} />建立 RAG 索引</button>
        </div>
        {error && <div role="alert" className="error-bar">{error}</div>}
        {busy && <div className="busy-bar">{busy}中...</div>}
        <GraphCanvas nodes={visibleNodes} edges={visibleEdges} query={query} selectedNodeId={selectedNode?.id} onSelect={setSelectedNode} />
      </section>

      <aside className="right-panel">
        <nav className="tabs">
          {(["integration", "rag", "dialogue", "report"] as Tab[]).map((tab) => (
            <button key={tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)}>
              {tabLabel(tab)}
            </button>
          ))}
        </nav>

        {selectedNode && (
          <section className="detail-panel">
            <h2>{selectedNode.name}</h2>
            <p>{selectedNode.definition}</p>
            <dl>
              <dt>分类</dt><dd>{selectedNode.category}</dd>
              <dt>页码</dt><dd>{selectedNode.page}</dd>
              <dt>来源</dt><dd>{selectedNode.sources?.join("、") || selectedNode.textbook_title || selectedNode.textbook_id}</dd>
            </dl>
            <blockquote>{selectedNode.source_excerpt}</blockquote>
          </section>
        )}

        {activeTab === "integration" && (
          <section className="tab-panel">
            <h2>整合决策</h2>
            <p className="muted">合并 {integration?.stats.decision_counts.merge || 0}，保留 {integration?.stats.decision_counts.keep || 0}，删除 {integration?.stats.decision_counts.remove || 0}</p>
            <div className="decision-list">
              {integration?.decisions.slice(0, 12).map((decision) => (
                <article key={decision.id}>
                  <strong>{decision.action}</strong>
                  <span>置信度 {(decision.confidence * 100).toFixed(0)}%</span>
                  <p>{decision.reason}</p>
                </article>
              ))}
            </div>
          </section>
        )}

        {activeTab === "rag" && (
          <section className="tab-panel">
            <h2>RAG 精准问答</h2>
            <textarea value={ragQuestion} onChange={(event) => setRagQuestion(event.target.value)} placeholder="输入教材相关问题" />
            <button onClick={ask} disabled={!!busy}>提交问题</button>
            {ragAnswer && (
              <div className="answer">
                <p>{ragAnswer.answer}</p>
                <small>{ragAnswer.elapsed_ms} ms · 约 {ragAnswer.token_estimate} tokens</small>
                {ragAnswer.citations.map((citation) => (
                  <details key={citation.chunk_id}>
                    <summary>{citation.textbook} · {citation.chapter} · 第 {citation.page} 页 · {citation.relevance_score.toFixed(2)}</summary>
                    <p>{citation.text}</p>
                  </details>
                ))}
              </div>
            )}
          </section>
        )}

        {activeTab === "dialogue" && (
          <section className="tab-panel">
            <h2>教师反馈</h2>
            <textarea value={dialogueMessage} onChange={(event) => setDialogueMessage(event.target.value)} placeholder="例如：我觉得某个知识点不应该被删除，请保留" />
            <button onClick={sendDialogue} disabled={!!busy}><MessageSquare size={16} />发送反馈</button>
            {dialogueReply && <p className="reply">{dialogueReply}</p>}
          </section>
        )}

        {activeTab === "report" && (
          <section className="tab-panel">
            <h2>整合报告</h2>
            <div className="button-row">
              <button onClick={loadReport} disabled={!!busy}>生成 Markdown</button>
              <a className="download-link" href="/api/report/pdf"><Download size={16} />导出 PDF</a>
            </div>
            <pre className="report-preview">{report || "生成报告后将在这里预览 Markdown。"}</pre>
          </section>
        )}
      </aside>
    </main>
  );
}

function tabLabel(tab: Tab) {
  return {
    integration: "整合",
    rag: "RAG",
    dialogue: "对话",
    report: "报告"
  }[tab];
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);

