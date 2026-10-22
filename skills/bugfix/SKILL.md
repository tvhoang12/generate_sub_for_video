---
name: bugfix
description: Classify, diagnose, plan, fix, and verify defects against approved AI Project OS behaviour. Use when shipped or implemented behaviour is reported broken, a regression appears, tests expose a defect, or a direct-fix versus full Bug workflow decision is needed.
---

# Bug Fix

Follow `docs/framework/workflows/bugfix.md`.

1. Establish approved expected behaviour or explicit owner confirmation before calling the issue a Bug.
2. Diagnose root cause from scoped code and evidence; never use code as correctness authority.
3. Apply the lightweight path only when all documented conditions hold and the owner explicitly agrees.
4. Otherwise create and approve a Bug artifact before planning implementation.
5. Add regression coverage for the diagnosed cause and deliver through the task-delivery workflow.
6. Record accepted-without-fix outcomes honestly as `closed-wont-fix`.
