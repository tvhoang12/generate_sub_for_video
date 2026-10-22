---
name: project-bootstrap
description: Bootstrap or extend an AI Project OS project, including initializing framework runtime files, selecting Claude/Codex/Generic adapters, generating platform instruction files, and starting Vision/MVP. Use when creating a new project from a copied `docs/framework`, running `aios init`, or adding an AI platform to an existing project.
---

# Project Bootstrap

Follow `docs/framework/workflows/initial-project.md` from the target project.

1. Confirm the framework exists at `docs/framework` or the path supplied by the user.
2. Run `aios init --agents <agents> --dry-run` first when files may already exist.
3. Explain conflicts and preserve existing instruction/config files; never force replacement.
4. Run the real init after the user has authorized any material replacement choice.
5. Run `aios doctor` and report warnings separately from errors.
6. For a new product, guide the Product Owner through Vision and MVP without inventing strategic or scope decisions.
7. Stop before Product Scope unless the user asks to continue.
