# Project Agent Instructions

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for the eventual public repository. See `docs/agents/issue-tracker.md`.

### Triage labels

The project uses the default triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context project. Domain vocabulary lives in `CONTEXT.md`; architecture decisions live in `docs/adr/`. See `docs/agents/domain.md`.

## Implementation guardrails

- Keep P0 end-to-end behavior working before expanding P1 scope.
- Do not commit textbook PDF files or generated vector indexes.
- Persist important implementation state in `docs/实施进度.md` before risky context operations.
- Compact, handoff, session switching, major replanning, or dropping committed P1 scope requires user confirmation.

