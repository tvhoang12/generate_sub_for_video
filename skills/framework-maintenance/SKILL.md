---
name: framework-maintenance
description: Review, change, migrate, and validate AI Project OS itself while preserving compatibility and vendor neutrality. Use when modifying core rules, artifact recipes, workflows, schemas, CLI commands, skills, adapters, framework versions, or project bootstrap behaviour.
---

# Framework Maintenance

Follow `docs/framework/workflows/framework-maintenance.md`.

1. Identify the single canonical component that owns the change and its compatibility surface.
2. Keep shared governance in core, reasoning in workflows/skills, deterministic checks in CLI/schema, and vendor syntax in adapters.
3. Preserve existing project artifacts and stable IDs unless an approved migration explicitly changes them.
4. Update version, changelog, schemas, adapters, tests, and migration notes together when applicable.
5. Validate skills, run CLI tests, pilot in temporary projects, and dry-run against a real project.
6. Never remove compatibility assets or publish a major version without human approval.
