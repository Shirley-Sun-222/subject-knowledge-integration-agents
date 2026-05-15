import React from "react";
import ReactDOM from "react-dom/client";
import { Download, FileText, GitMerge, MessageSquare, Network, Play, Search, UploadCloud } from "lucide-react";
import { api, type IntegrationResult, type KnowledgeEdge, type KnowledgeNode, type RagResponse, type TaskDetail, type Textbook } from "./lib/api";
import { taskLabel, useTaskWorkflow } from "./lib/workflow";
import type { GraphLayoutMode } from "./components/GraphCanvas";
import "./styles.css";

const GraphCanvas = React.lazy(() =>
  import("./components/GraphCanvas").then((module) => ({ default: module.GraphCanvas }))
);

type Tab = "integration" | "rag" | "dialogue" | "report";
type GraphMode = "empty" | "single" | "integration";

type GraphView = {
  mode: GraphMode;
  title: string;
  metrics?: {
    processed_chapters?: number;
    total_chapters?: number;
    truncated?: boolean;
    fallback_chapters?: number;
    llm_chapters?: number;
    llm_configured?: boolean;
  };
};

function App() {
  const [textbooks, setTextbooks] = React.useState<Textbook[]>([]);
  const [graphNodes, setGraphNodes] = React.useState<KnowledgeNode[]>([]);
  const [graphEdges, setGraphEdges] = React.useState<KnowledgeEdge[]>([]);
  const [graphView, setGraphView] = React.useState<GraphView>({ mode: "empty", title: "尚未加载图谱" });
  const [graphLayoutMode, setGraphLayoutMode] = React.useState<GraphLayoutMode>("chapter-map");
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
  const deferredQuery = React.useDeferredValue(query);

  const run = React.useCallback(async <T,>(label: string, action: () => Promise<T>): Promise<T | undefined> => {
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
  }, []);

  const refresh = React.useCallback(async (options: { loadIntegrationGraph?: boolean } = {}) => {
    const textbookResult = await api.textbooks();
    const ragResult = await api.ragStatus();
    const integrationResult = await api.integration();
    setTextbooks(textbookResult.textbooks);
    setRagStatus(ragResult);
    setIntegration(integrationResult);
    if (options.loadIntegrationGraph && integrationResult.nodes.length) {
      setGraphNodes(integrationResult.nodes);
      setGraphEdges(integrationResult.edges);
      setGraphView({ mode: "integration", title: "跨教材整合图谱" });
    }
    return {
      textbooks: textbookResult.textbooks,
      ragStatus: ragResult,
      integration: integrationResult
    };
  }, []);

  const onTaskSucceeded = React.useCallback(
    async (task: TaskDetail) => {
      const snapshot = await refresh({ loadIntegrationGraph: false });
      if (task.task_type === "parse_textbook") {
        return;
      }
      if (task.task_type === "build_graph") {
        const graphResult = await api.graph(task.resource_id);
        const textbook = snapshot.textbooks.find((book) => book.id === task.resource_id);
        setGraphNodes(graphResult.nodes);
        setGraphEdges(graphResult.edges);
        setSelectedNode(null);
        setGraphView({
          mode: "single",
          title: textbook ? `单本图谱：${textbook.title}` : "单本图谱",
          metrics: {
            processed_chapters: task.progress_current,
            total_chapters: task.progress_total,
            truncated: task.truncated
          }
        });
        return;
      }
      if (task.task_type === "run_integration") {
        setIntegration(snapshot.integration);
        if (snapshot.integration.nodes.length) {
          setGraphNodes(snapshot.integration.nodes);
          setGraphEdges(snapshot.integration.edges);
          setSelectedNode(null);
          setGraphView({ mode: "integration", title: "跨教材整合图谱" });
        }
        return;
      }
      if (task.task_type === "build_rag_index") {
        setRagStatus(snapshot.ragStatus);
      }
    },
    [refresh]
  );

  const onTaskFailed = React.useCallback(
    async (task: TaskDetail) => {
      setError(task.error_summary || `${taskLabel(task)}失败`);
      await refresh({ loadIntegrationGraph: false });
    },
    [refresh]
  );

  const { activeTasks, lastFailedTask, trackTask, activeTaskFor } = useTaskWorkflow({
    onTaskSucceeded,
    onTaskFailed
  });

  async function settleImmediateTask(taskId: string) {
    const detail = (await api.task(taskId)).task;
    if (detail.status === "succeeded") {
      await onTaskSucceeded(detail);
    }
    if (detail.status === "failed") {
      await onTaskFailed(detail);
    }
  }

  React.useEffect(() => {
    void refresh({ loadIntegrationGraph: true });
  }, [refresh]);

  React.useEffect(() => {
    if (lastFailedTask?.error_summary) {
      setError(lastFailedTask.error_summary);
    }
  }, [lastFailedTask]);

  async function upload(files: FileList | null) {
    if (!files?.length) {
      return;
    }
    await run("上传教材", async () => {
      const result = await api.upload(files);
      result.uploads.forEach((item) => trackTask(item.task));
      await refresh({ loadIntegrationGraph: false });
    });
  }

  async function buildGraph(textbookId: string) {
    const result = await run("提交图谱任务", () => api.buildGraph(textbookId));
    if (result) {
      trackTask(result.task);
      if (result.task.status !== "queued" && result.task.status !== "running") {
        await settleImmediateTask(result.task.id);
      }
    }
  }

  async function integrate() {
    const result = await run("提交整合任务", () => api.runIntegration());
    if (result) {
      trackTask(result.task);
      if (result.task.status !== "queued" && result.task.status !== "running") {
        await settleImmediateTask(result.task.id);
      }
    }
  }

  function showIntegrationGraph() {
    if (!integration?.nodes.length) {
      return;
    }
    setGraphNodes(integration.nodes);
    setGraphEdges(integration.edges);
    setSelectedNode(null);
    setGraphView({ mode: "integration", title: "跨教材整合图谱" });
  }

  async function indexRag() {
    const result = await run("提交索引任务", () => api.indexRag());
    if (result) {
      trackTask(result.task);
      if (result.task.status !== "queued" && result.task.status !== "running") {
        await settleImmediateTask(result.task.id);
      }
    }
  }

  async function buildReportPdf() {
    const result = await run("提交 PDF 任务", () => api.buildReportPdf());
    if (result) {
      trackTask(result.task);
      if (result.task.status !== "queued" && result.task.status !== "running") {
        await settleImmediateTask(result.task.id);
      }
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
      setDialogueReply((result as { reply: string }).reply);
      const snapshot = await refresh({ loadIntegrationGraph: graphView.mode === "integration" });
      if (graphView.mode === "integration" && snapshot.integration.nodes.length) {
        setGraphNodes(snapshot.integration.nodes);
        setGraphEdges(snapshot.integration.edges);
        setSelectedNode(null);
      }
    }
  }

  async function loadReport() {
    const result = await run("生成整合报告", () => api.report());
    if (result) {
      setReport(result.markdown);
    }
  }

  const visibleNodes = React.useMemo(() => {
    if (!deferredQuery.trim()) {
      return graphNodes.slice(0, 180);
    }
    return graphNodes.filter((node) => node.name.includes(deferredQuery) || node.definition.includes(deferredQuery)).slice(0, 180);
  }, [graphNodes, deferredQuery]);

  const graphQuality = React.useMemo(() => describeGraphQuality(graphView.metrics, graphNodes), [graphView.metrics, graphNodes]);
  const visibleEdges = React.useMemo(() => {
    const visibleIds = new Set(visibleNodes.map((node) => node.id));
    return graphEdges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target));
  }, [graphEdges, visibleNodes]);

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
                <span>图谱 {book.graph_node_count || 0} 节点 / {book.graph_edge_count || 0} 边</span>
                <span className={`status ${book.status}`}>{book.status}</span>
                {book.error && <span className="row-error">{book.error}</span>}
              </div>
              <button
                onClick={() => buildGraph(book.id)}
                disabled={book.status !== "completed" || !!activeTaskFor("build_graph", book.id) || !!activeTaskFor("parse_textbook", book.id)}
                aria-label="构建图谱"
              >
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
          <div className="segmented-control" aria-label="图谱视图">
            <button className={graphLayoutMode === "chapter-map" ? "active" : ""} onClick={() => setGraphLayoutMode("chapter-map")} aria-pressed={graphLayoutMode === "chapter-map"}>
              章节思维导图
            </button>
            <button className={graphLayoutMode === "force" ? "active" : ""} onClick={() => setGraphLayoutMode("force")} aria-pressed={graphLayoutMode === "force"}>
              关系网络
            </button>
          </div>
          <button onClick={integrate} disabled={!!activeTaskFor("run_integration")}><GitMerge size={16} />跨教材整合</button>
          <button onClick={showIntegrationGraph} disabled={!integration?.nodes.length}><Network size={16} />显示整合图谱</button>
          <button onClick={indexRag} disabled={!!activeTaskFor("build_rag_index")}><FileText size={16} />建立 RAG 索引</button>
        </div>
        <div className="graph-status">
          <div>
            <strong>{graphView.title}</strong>
            <span>{graphNodes.length} 节点 · {graphEdges.length} 边 · 当前显示 {visibleNodes.length} 节点</span>
          </div>
          {graphView.metrics?.total_chapters !== undefined && (
            <span className={graphView.metrics.truncated ? "status-warning" : "status-ok"}>
              已处理 {graphView.metrics.processed_chapters || 0}/{graphView.metrics.total_chapters} 章{graphView.metrics.truncated ? "，已按上限截断" : ""}
            </span>
          )}
          {graphQuality && <span className={graphQuality.kind === "warning" ? "status-warning" : "status-ok"}>{graphQuality.label}</span>}
        </div>
        <div className="workspace-messages">
          {error && <div role="alert" className="error-bar">{error}</div>}
          {busy && <div className="busy-bar">{busy}中...</div>}
          {activeTasks.map((task) => (
            <div key={task.id} className="busy-bar">
              {taskLabel(task)} · {renderTaskProgress(task)}
            </div>
          ))}
        </div>
        <React.Suspense fallback={<div className="empty-state">正在加载图谱引擎...</div>}>
          <GraphCanvas
            nodes={visibleNodes}
            edges={visibleEdges}
            query={deferredQuery}
            layoutMode={graphLayoutMode}
            rootLabel={graphView.title}
            selectedNodeId={selectedNode?.id}
            onSelect={setSelectedNode}
          />
        </React.Suspense>
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
              <button onClick={buildReportPdf} disabled={!!activeTaskFor("build_report_pdf")}><FileText size={16} />生成 PDF</button>
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

function describeGraphQuality(metrics: GraphView["metrics"], nodes: KnowledgeNode[]) {
  if (metrics?.processed_chapters) {
    const fallbackChapters = metrics.fallback_chapters || 0;
    if (fallbackChapters > 0) {
      return { kind: "warning", label: `关键词降级抽取 ${fallbackChapters}/${metrics.processed_chapters} 章，质量有限` };
    }
    return { kind: "ok", label: `已处理 ${metrics.processed_chapters} 章图谱` };
  }
  if (!nodes.length) {
    return null;
  }
  const fallbackNodes = nodes.filter((node) => node.metadata?.fallback).length;
  if (fallbackNodes > 0) {
    return { kind: "warning", label: `含关键词降级节点 ${fallbackNodes}/${nodes.length}` };
  }
  return null;
}

function renderTaskProgress(task: TaskDetail) {
  if (task.progress_total > 0) {
    return `${task.progress_current}/${task.progress_total}${task.truncated ? "，已截断" : ""}`;
  }
  return task.status;
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
