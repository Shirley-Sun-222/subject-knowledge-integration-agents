# ADR 0002: Single-Container Background Tasks for Public Deployment

## Status

Accepted

## Context

The application is deployed as a single FastAPI container backed by SQLite and local filesystem directories. Public cloud runs already showed that synchronous HTTP requests for textbook parsing, graph construction, RAG indexing, and PDF report generation can exceed gateway time limits. The project also depends on OCR, file upload, persisted runtime state, and PDF rendering, so it is not a static-site workload.

## Decision

Keep the public deployment target as a containerized backend application, optimized for ModelScope Spaces and generic Docker hosts.

Long-running write operations now use a persisted `TaskRun` workflow:

- clients call a `POST` endpoint that returns `202 Accepted`
- the backend enqueues a background task inside the same container
- task status, phase, progress, truncation, errors, and result references are stored in SQLite
- clients poll `GET /api/tasks` or `GET /api/tasks/{task_id}` to recover progress

Do not introduce an external task queue or separate worker process in this phase. Do not split the application into a static frontend on GitHub Pages plus a separate API tier.

## Consequences

This keeps the interface small and aligned with the current deployment model: one container, one SQLite database, one writable runtime directory tree. It removes the tight coupling between public request duration and textbook-sized workloads, while preserving the existing scripts, tests, and local Docker workflow.

The trade-off is that the application remains single-node and single-tenant. Background work survives within the running container but is still bounded by SQLite and local disk semantics. If future requirements demand higher concurrency or multi-user isolation, the next seam to revisit is the runtime state adapter, not the frontend deployment target.
