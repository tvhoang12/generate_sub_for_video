---
name: artifact-workflow
description: Generate, amend, validate, and route AI Project OS artifacts using closed inputs, approval gates, stable identifiers, and bidirectional traceability. Use when creating or updating Product Scope, PRD, design documents, Test Strategy, Roadmap, Sprint, Task, or Bug artifacts.
---

# Artifact Workflow

Follow `docs/framework/workflows/artifact-workflow.md`.

1. Resolve the artifact in `docs/framework/core/artifact-graph.json` and read its recipe under `docs/framework/artifacts/`.
2. Read `docs/framework/core/principles.md` and only the recipe's allowed inputs.
3. Distinguish Generate from Update before reading or writing the existing output.
4. Stop on blocking decisions; never self-approve.
5. Preserve stable identifiers and unaffected content during Update.
6. Run `aios artifact validate <artifact>` and `aios doctor` before handoff.
7. Report the exact inputs used, gate results, unresolved items, and downstream candidate impact.
