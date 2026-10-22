---
name: task-delivery
description: Deliver an approved AI Project OS Task or Bug through understanding, planning, approval, implementation, validation, review, and human verification. Use when the user asks to implement, continue, validate, review, or complete an approved work item.
---

# Task Delivery

Follow `docs/framework/workflows/task-delivery.md`.

1. Run `aios doctor`, then read the work item, exact approved references, project conventions, and scoped code.
2. Create a complete plan and obtain required approval before material implementation.
3. Preserve unrelated changes and stop on new product/design decisions.
4. Validate against the approved Test Strategy and every acceptance criterion.
5. Run realistic browser, provider, persistence, or scheduled-work checks when affected.
6. Run `aios verify <WORK-ITEM-ID>` and create `review-<type>-###.md` with evidence.
7. Wait for explicit human verification before completion.
