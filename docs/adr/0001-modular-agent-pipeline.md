# ADR 0001: Modular Agent Pipeline

## Status

Accepted

## Context

The system must parse textbooks, extract knowledge graphs, align concepts across textbooks, compress content, answer RAG questions with citations, accept teacher feedback, and generate reports. These tasks have different failure modes and require different levels of LLM involvement.

## Decision

Use a modular runtime agent pipeline orchestrated by FastAPI services. Agents communicate through SQLite, files, and JSON schema validated objects rather than conversation history.

The runtime agents are:

- Parser
- KnowledgeExtractionAgent
- AlignmentAgent
- CompressionPlannerAgent
- CitationQAAgent
- TeacherDialogueAgent
- ReportAgent

## Consequences

This keeps each stage testable and observable. Deterministic work remains in code, while LLM calls are limited to semantic judgment and generation. The trade-off is that the orchestrator and database schema must be kept consistent across modules.

