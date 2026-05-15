# ADR 0003: Session Workspaces for Public Demo Isolation

## Status

Accepted

## Context

The public deployment originally exposed a single shared runtime state: uploaded textbooks, parsed chapters, graph results, RAG chunks, integration decisions, and report artifacts were visible to every visitor of the same deployment instance. That behavior was acceptable for a single-tenant prototype, but it is a poor fit for a public demo or judging environment where each visitor should start from an empty workspace and should not inherit another visitor's textbooks or model configuration.

## Decision

Introduce anonymous **Session Workspaces** as the public-facing runtime model.

- every browser session receives its own workspace identifier via cookie
- all runtime entities are scoped to that workspace: textbooks, chapters, chunks, graph results, integration decisions, tasks, metrics, and temporary LLM configuration
- workspaces support selective textbook deletion
- workspaces expire automatically after a TTL and are cleaned up server-side
- existing legacy shared runtime state is cleared during migration rather than preserved

LLM configuration also becomes workspace-scoped: a visitor may provide a temporary OpenAI-compatible model configuration for the current workspace, which overrides the deployment's global model settings only for that session.

## Consequences

This makes the public site behave much closer to an "empty original site" for each new visitor, which improves demo isolation and removes cross-user leakage of textbooks and generated results. It also enables user-provided model credentials without turning them into shared global deployment state.

The trade-off is additional runtime bookkeeping: every read/write path now carries a workspace dimension, server-side cleanup must enforce TTL expiry, and any future administrative or collaborative workflow would need an explicit policy for sharing or promoting workspace data.
