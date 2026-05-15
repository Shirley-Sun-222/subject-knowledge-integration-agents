# Compact Handoff

**Created:** 2026-05-15 16:03:05 CST  
**Project:** `/Users/sunxueli/CodexFile/subject-knowledge-integration-agents`  
**Next focus:** Implement the LLM and ModelScope public deployment plan, starting with safe local DeepSeek configuration and smoke validation.

## Objective

Prepare the subject knowledge integration app for public deployment through GitHub and ModelScope Studio, with DeepSeek LLM enabled through environment variables and no secrets or textbook/runtime data committed to GitHub.

## Current State

The user asked to implement the LLM + ModelScope deployment plan, then interrupted the turn and invoked `$my-auto-compact`. No deployment implementation was started after the interruption.

Current git state is clean. Latest commits:

- `791298d test: expand rag benchmark coverage`
- `d6750bd fix: preserve graph viewport on node selection`
- `ec0f147 docs: add compact handoff snapshot`
- `42d80e9 docs: record compact handoff`
- `1749d49 feat: add chapter mind map graph view`

Docker container `subject-knowledge-integration-agents-app-1` is running and exposes `0.0.0.0:8000->8000/tcp`.

## Latest Plan

Implement LLM and ModelScope deployment:

1. Configure local `.env` with DeepSeek values without committing it.
2. Add or use a safe LLM smoke check that validates `complete_text` and `complete_json` without printing secrets.
3. Verify local tests/build and a minimal LLM graph/RAG smoke flow.
4. Confirm GitHub publishing safety: no tracked PDFs, no tracked `.env`, no tracked runtime data, no `sk-` secrets in git-tracked files.
5. Create/push public GitHub repo `subject-knowledge-integration-agents`.
6. Deploy ModelScope Studio from GitHub using environment variables, with empty initial database and upload-through-UI workflow.
7. Update README and `docs/实施进度.md` with verified LLM/ModelScope results and public URL.

## Files Touched

No files are currently modified.

Recent relevant files from prior work:

- `backend/app/services/llm.py`: OpenAI-compatible LLM client.
- `backend/app/agents/extraction.py`: LLM JSON extraction with fallback heuristic.
- `scripts/start_modelscope.sh`: ModelScope startup script.
- `README.md`: deployment, benchmark, and GitHub publication documentation.
- `docs/实施进度.md`: current project status and remaining blockers.
- `scripts/run_rag_benchmark.py`: 25-question benchmark.
- `backend/app/services/rag.py`: RAG retrieval and domain-out rejection guard.

## Files To Read First

1. `README.md`
2. `docs/实施进度.md`
3. `backend/app/services/llm.py`
4. `backend/app/agents/extraction.py`
5. `scripts/start_modelscope.sh`
6. `.env.example`

## Decisions And Constraints

- The user provided a DeepSeek API key in the conversation. Treat it as exposed: it may be used only for temporary local validation if necessary, and must be rotated before official deployment.
- Do not write the real API key into tracked files, docs, handoff files, screenshots, logs, or commit messages.
- Store local secrets only in `.env`; store ModelScope secrets only in ModelScope environment variables.
- Planned DeepSeek values:
  - `LLM_BASE_URL=https://api.deepseek.com`
  - `LLM_MODEL=deepseek-v4-pro`
  - `LLM_API_KEY=<secret, never commit>`
- GitHub target repository name: `subject-knowledge-integration-agents`.
- Deployment source: GitHub import into ModelScope Studio.
- ModelScope initial state: empty database; users upload textbooks through the web UI.
- Do not commit `book_samples/`, PDF textbooks, `data/`, SQLite databases, FAISS/index files, `.env`, or generated runtime artifacts.
- `setup-matt-pocock-skills` is already configured: GitHub Issues, default labels, single-context domain docs.

## Validation

Recent validated state before this handoff:

- `.venv/bin/python -m pytest backend/tests`: 15 passed.
- `npm --prefix frontend run build`: passed with existing Cytoscape bundle size warning.
- `/usr/local/bin/docker compose build --progress plain`: passed.
- `/usr/local/bin/docker compose up -d`: passed.
- `curl --noproxy '*' http://127.0.0.1:8000/api/health`: returned `{"status":"ok"}`.
- `scripts/run_rag_benchmark.py`: 25 questions; citation presence 100%, source hint score about 95.5%, out-of-domain rejection 100%, automatic pass rate 52% on current sample index.

Validation not yet run:

- DeepSeek LLM smoke check.
- Graph extraction with real DeepSeek output.
- ModelScope public deployment.
- GitHub remote push.

## Pending Work

1. Update local `.env` with DeepSeek values safely, without staging it.
2. Add a safe LLM smoke script if needed; ensure it masks secrets and validates JSON mode.
3. Run LLM smoke check and one minimal real-LLM graph/RAG flow.
4. Re-run tests/build/Docker health.
5. Check secret hygiene with `git grep -n "sk-"` and tracked file checks.
6. Create GitHub repo or add provided remote and push `main`.
7. Configure ModelScope environment variables and start command.
8. Verify public URL, `/api/health`, upload, graph, RAG, and report/PDF behavior.
9. Rotate the exposed DeepSeek key before final deployment.
10. Commit documentation updates after verification.

## Skills To Use Next

- `openai-docs` only if OpenAI-specific docs are needed; for DeepSeek, use provider docs or local smoke tests.
- `diagnose` for LLM JSON mode, graph extraction, or ModelScope runtime failures.
- `grill-me` for deployment tradeoff decisions if new platform constraints appear.
- `verification-loop` before final public release.
- `my-compact` if runtime compaction becomes available.
