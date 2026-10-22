---
name: feature-change
description: Classify and govern product or localized design changes across AI Project OS artifacts. Use when adding a capability, changing approved behaviour, widening a field or relationship, changing an API/UI contract, or deciding which artifacts and release plans are actually impacted.
---

# Feature Change

Follow `docs/framework/workflows/change-routing.md`, then `docs/framework/workflows/feature-change.md`.

1. Classify the request as Lane 2 localized design change or Lane 3 product capability; redirect true defects to `bugfix`.
2. Identify and obtain approval in the single owning artifact before cascading.
3. Run `aios impact <artifact>` and classify every candidate Impacted: Yes/No with a reason.
4. Update only Yes artifacts in dependency order through the artifact workflow.
5. Keep migration safety, test-strategy impact, backward compatibility, and no-data-loss requirements explicit.
6. Generate new planning/work-item identifiers rather than repurposing completed ones.
