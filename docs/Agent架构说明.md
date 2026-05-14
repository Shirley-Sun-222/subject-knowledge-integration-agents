# Agent 架构说明

## 架构总览

本系统采用模块化多 Agent 架构，但运行时由一个 FastAPI Orchestrator 调度。Agent 不是独立聊天窗口，而是有明确输入输出 schema 的任务单元。

## Agent 职责

| Agent | 输入 | 输出 | 说明 |
| --- | --- | --- | --- |
| Parser | 教材文件 | Textbook, Chapter | 确定性解析，不依赖 LLM |
| KnowledgeExtractionAgent | Chapter | KnowledgeNode, KnowledgeEdge | 抽取概念和关系 |
| AlignmentAgent | KnowledgeNode | 候选重复组 | embedding 召回 + LLM 等价复核 |
| CompressionPlannerAgent | 候选组、原始字数 | IntegrationDecision | 控制 30% 压缩目标 |
| CitationQAAgent | 问题、Chunks | Answer, Citation | 引用只能来自 chunk metadata |
| TeacherDialogueAgent | 教师反馈、决策 | 修订后的决策 | 支持保留、删除、合并、拆分 |
| ReportAgent | 统计数据、决策 | Markdown, PDF | 保证报告与系统数据一致 |

## 设计决策论证

教材整合包含解析、抽取、对齐、压缩、引用问答和教师修订六类不同任务。它们的上下文长度、失败模式和测试方式不同。模块化后可以限制 LLM 的影响范围，减少幻觉传播，并让每个阶段可单独测试和回放。

## 通信方式

Agent 之间不通过自然语言聊天通信，而是通过：

- SQLite 表
- 文件系统产物
- Pydantic/JSON schema
- Orchestrator 状态

这保证任一阶段失败后可以从结构化状态恢复。

## 取舍与局限

没有引入 CrewAI、LangGraph 等重型运行框架，原因是比赛时长短，框架调试成本高。当前架构保留模块化 Agent 的可解释性和可测试性，但牺牲了复杂工作流可视化能力。若有更多时间，可以引入任务队列和异步进度推送。

## 创新点

- 将知识图谱整合决策作为可解释、可修改的一等对象。
- RAG citation 从 metadata 自动生成，避免模型编造页码。
- 以报告 Markdown 为事实源派生 PDF，避免报告内容漂移。
- 使用 benchmark 记录回答准确率、引用准确率、响应时间和 token 消耗。

