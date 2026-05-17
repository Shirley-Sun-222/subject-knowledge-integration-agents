import React from "react";
import { api, type TaskDetail, type TaskSummary } from "./api";

type WorkflowOptions = {
  onTaskSucceeded?: (task: TaskDetail) => void | Promise<void>;
  onTaskFailed?: (task: TaskDetail) => void | Promise<void>;
};

type TaskMap = Record<string, TaskDetail>;

function toDetail(task: TaskSummary): TaskDetail {
  return {
    ...task,
    progress_current: 0,
    progress_total: 0,
    truncated: false,
    error_summary: null,
    metadata: {},
    result_ref: null,
    created_at: "",
    started_at: null,
    finished_at: null
  };
}

export function useTaskWorkflow(options: WorkflowOptions = {}) {
  const [tasks, setTasks] = React.useState<TaskMap>({});
  const [lastFailedTask, setLastFailedTask] = React.useState<TaskDetail | null>(null);
  const notifiedRef = React.useRef(new Set<string>());
  const { onTaskSucceeded, onTaskFailed } = options;

  const mergeTasks = React.useCallback((incoming: TaskDetail[]) => {
    if (incoming.length === 0) {
      return;
    }
    setTasks((current) => {
      const next = { ...current };
      incoming.forEach((task) => {
        next[task.id] = task;
      });
      return next;
    });
  }, []);

  const trackTask = React.useCallback((task: TaskSummary) => {
    setTasks((current) => ({ ...current, [task.id]: toDetail(task) }));
  }, []);

  const handleTransition = React.useCallback(
    async (task: TaskDetail) => {
      if (notifiedRef.current.has(task.id)) {
        return;
      }
      if (task.status === "succeeded") {
        notifiedRef.current.add(task.id);
        await onTaskSucceeded?.(task);
      }
      if (task.status === "failed") {
        notifiedRef.current.add(task.id);
        setLastFailedTask(task);
        await onTaskFailed?.(task);
      }
    },
    [onTaskFailed, onTaskSucceeded]
  );

  React.useEffect(() => {
    let active = true;
    async function recover() {
      const [running, queued] = await Promise.all([
        api.tasks({ status: "running" }),
        api.tasks({ status: "queued" })
      ]);
      if (!active) {
        return;
      }
      mergeTasks([...running.tasks, ...queued.tasks]);
    }
    void recover();
    return () => {
      active = false;
    };
  }, [mergeTasks]);

  const activeTasks = React.useMemo(
    () =>
      Object.values(tasks)
        .filter((task) => task.status === "queued" || task.status === "running")
        .sort((left, right) => left.task_type.localeCompare(right.task_type)),
    [tasks]
  );

  React.useEffect(() => {
    if (activeTasks.length === 0) {
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const results = await Promise.all(activeTasks.map((task) => api.task(task.id).then((result) => result.task)));
        if (cancelled) {
          return;
        }
        mergeTasks(results);
        await Promise.all(results.map((task) => handleTransition(task)));
      } catch (_error) {
        if (cancelled) {
          return;
        }
      }
      if (!cancelled) {
        timer = window.setTimeout(poll, nextPollingDelay(activeTasks));
      }
    };
    timer = window.setTimeout(poll, nextPollingDelay(activeTasks));
    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [activeTasks, handleTransition, mergeTasks]);

  const activeTaskFor = React.useCallback(
    (taskType: TaskDetail["task_type"], resourceId?: string) =>
      activeTasks.find((task) => task.task_type === taskType && (resourceId === undefined || task.resource_id === resourceId)),
    [activeTasks]
  );

  return {
    tasks,
    activeTasks,
    lastFailedTask,
    trackTask,
    activeTaskFor
  };
}

export function taskLabel(task: TaskDetail | TaskSummary) {
  const typeLabel = {
    parse_textbook: "解析教材",
    preview_parse_textbook: "预览解析",
    full_parse_textbook: "全量解析",
    build_graph: "构建图谱",
    run_integration: "跨教材整合",
    build_rag_index: "建立 RAG 索引",
    build_report_pdf: "生成 PDF 报告"
  }[task.task_type];
  return `${typeLabel} · ${task.phase}`;
}

function nextPollingDelay(tasks: TaskDetail[]) {
  const now = Date.now();
  const newestActivityAgeMs = tasks.reduce((youngest, task) => {
    const baseline = task.started_at || task.created_at;
    const age = baseline ? Math.max(0, now - new Date(baseline).getTime()) : 0;
    return Math.min(youngest, age);
  }, Number.POSITIVE_INFINITY);

  const pendingQueued = tasks.some((task) => task.status === "queued");
  const intensivePhase = tasks.some((task) =>
    ["parsing_textbook", "detecting_pdf_mode", "reading_pdf_pages", "ocr_pdf_pages", "extracting_graph", "chunking_textbooks"].includes(task.phase)
    || ["preview_parsing_textbook", "full_parsing_textbook", "reading_pdf_preview_pages"].includes(task.phase)
  );

  if (pendingQueued || newestActivityAgeMs < 4_000) {
    return 400;
  }
  if (intensivePhase || newestActivityAgeMs < 15_000) {
    return 1_000;
  }
  if (newestActivityAgeMs < 60_000) {
    return 2_500;
  }
  return 5_000;
}
