# 学科知识整合智能体

本项目依据 [AI 全栈极速黑客松「学科知识整合智能体开发」赛题要求](./docs/%E5%8E%9F%E5%A7%8B%E8%B5%9B%E9%A2%98%E6%96%87%E6%A1%A3.md) 实现，目标是把多本教材整合为可检索、可追溯、可压缩的知识系统，并通过 Web 界面对外提供上传、图谱、RAG、对话和报告能力。

## 项目概览

- 多格式教材上传与解析：PDF、Markdown、TXT、DOCX
- 单本教材知识图谱构建与可视化
- 跨教材知识点对齐、整合与压缩决策
- 带引用的 RAG 问答与领域外拒答
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

## 隐私与数据安全

- 不提交 `textbooks/` 官方教材 PDF
- 不提交 `data/` 运行产物、SQLite、索引和实验原始结果
- 不提交 `.env`、`.env.modelscope` 或任何真实密钥
- 对外仓库只保留可复现代码、公开文档和聚合后的实验结论

详细运行、Docker、部署、benchmark 和 P2 实验说明见 [docs/操作指南.md](./docs/%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97.md)。
