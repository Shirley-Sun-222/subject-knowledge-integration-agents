# ADR 0004: Two-Stage Parse and LLM-First Graphs

## Status

Accepted

## Context

Public demo deployments run in a constrained single-container environment. Full PDF parsing and OCR can take too long before the user sees any usable state, especially for scanned medical textbooks. At the same time, keyword-only graph extraction produces poor teaching concepts and makes the graph look more complete than it is.

## Decision

Split textbook ingestion into two stages:

- Preview Parse creates a small usable chapter set from TOC/bookmarks and limited page text.
- Full Parse continues in the background and is required before RAG indexing.

Graph construction is LLM-first:

- preview graph chapters attempt LLM extraction first
- full graph chapters skip only obvious non-teaching pages before attempting LLM extraction
- missing LLM configuration still permits a low-quality keyword graph, but the API and UI must mark it clearly
- excessive chapter-level LLM failure fails the graph task rather than silently returning mostly fallback content

## Consequences

Users can see a usable preview much sooner on ModelScope-style deployments, while the system keeps RAG answers tied to full parsed content. The trade-off is that preview-derived graphs may become stale after Full Parse completes, so the UI and API must expose graph scope and stale state instead of silently replacing or rebuilding outputs.
