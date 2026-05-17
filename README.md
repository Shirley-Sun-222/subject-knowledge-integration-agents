# 学科知识整合智能体

本项目依据 [AI 全栈极速黑客松「学科知识整合智能体开发」赛题要求](./docs/%E5%8E%9F%E5%A7%8B%E8%B5%9B%E9%A2%98%E6%96%87%E6%A1%A3.md) 实现，目标是把多本教材整合为可检索、可追溯、可压缩的知识系统，并通过 Web 界面对外提供上传、图谱、RAG、对话和报告能力。

## 项目概览

- 多格式教材上传与解析：PDF、Markdown、TXT、DOCX
- 双阶段 PDF 解析：先用 TOC/书签和少量正文生成预览，后台继续全量解析
- 优先使用 PDF TOC/书签切顶层教学章，缺失时回退正则识别
- 并行原生文本抽取 + 受页数预算限制的并行 OCR，加速大 PDF 解析
- 相同教材按文件哈希复用解析结果，减少重复等待
- LLM 优先的单本教材知识图谱构建与可视化；未配置 LLM 时允许生成低质量关键词图谱并显著警示
- 跨教材知识点对齐、整合与压缩决策
- 带引用的 RAG 问答与领域外拒答；RAG 索引只基于全量解析完成的教材建立
- 教师反馈修订整合方案
- Markdown 报告导出与 P2 技术报告实验资产

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
npm install
npm --prefix frontend install
npm run dev
```

开发环境入口：

- 前端开发服务：`http://localhost:5173`
- 后端健康检查：`http://localhost:8000/api/health`

公网演示地址：

- [ModelScope 部署](https://shirley222-subject-knowledge-integration-agents.ms.show)
- [GitHub 仓库](https://github.com/Shirley-Sun-222/subject-knowledge-integration-agents)

## 文档导航

- [系统操作指南](./docs/%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97.md)
- [P2 技术报告草稿](./docs/P2%E6%8A%80%E6%9C%AF%E6%8A%A5%E5%91%8A.md)
- [系统设计](./docs/%E7%B3%BB%E7%BB%9F%E8%AE%BE%E8%AE%A1.md)
- [Agent 架构说明](./docs/Agent%E6%9E%B6%E6%9E%84%E8%AF%B4%E6%98%8E.md)
- [需求分析](./docs/%E9%9C%80%E6%B1%82%E5%88%86%E6%9E%90.md)
- [原始赛题文档](./docs/%E5%8E%9F%E5%A7%8B%E8%B5%9B%E9%A2%98%E6%96%87%E6%A1%A3.md)

## 官方教材与实验资产

- 官方教材放在本地 `textbooks/` 目录，仅用于本地实验与报告撰写，不提交到 GitHub。
- P2 医学 benchmark 题集位于 `scripts/benchmark_sets/medical_official_questions.json`。
- P2 实验脚本为 `scripts/run_p2_rag_experiments.py`，会把原始结果写到本地 `data/generated/p2-rag-official/`。
- PDF 解析阶段语义已区分：
  - `预览解析`：默认抽取前 3 个教学章、每章最多 3 页，OCR 总页数最多 9 页，用于公网快速可预览
  - `全量解析`：后台处理整本教材，OCR 仍受 `OCR_MAX_PAGES` 限制，避免扫描版全书无上限 OCR
- 图谱模式语义已区分：
  - `预览图谱`：预览可用后即可构建，前 3 章优先尝试 LLM
  - `全量图谱`：必须等待全量解析完成，明显非教学章节会跳过 LLM，其余章节优先尝试 LLM
- 图谱质量语义已区分：
  - 已配置 LLM：每章最多重试 1 次，失败比例超过 30% 会标记任务失败
  - 未配置 LLM：仍允许快速构建，但 API metrics 和页面会显示“未配置 LLM，当前为低质量关键词图谱”

## 关键配置

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=gpt-4o-mini
OCR_MAX_PAGES=120
PREVIEW_PARSE_CHAPTERS=3
PREVIEW_PARSE_PAGES_PER_CHAPTER=3
PREVIEW_OCR_MAX_PAGES=9
GRAPH_MAX_CHAPTERS=30
```

前端会话级 LLM 配置优先于全局环境变量；后端通过 `resolve_config(workspace_id)` 判断是否可用，而不是只读取全局环境变量。部署到 ModelScope 等公网低配环境时，建议保留默认预览预算，并按机器能力调低 `OCR_MAX_PAGES`。

## 隐私与数据安全

- 不提交 `textbooks/` 官方教材 PDF
- 不提交 `data/` 运行产物、SQLite、索引和实验原始结果
- 不提交 `.env`、`.env.modelscope` 或任何真实密钥
- 对外仓库只保留可复现代码、公开文档和聚合后的实验结论

详细运行、Docker、部署、benchmark 和 P2 实验说明见 [docs/操作指南.md](./docs/%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97.md)。
