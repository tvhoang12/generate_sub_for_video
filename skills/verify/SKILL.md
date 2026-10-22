---
name: verify
description: How to build/launch/drive HR OS (backend + frontend) for runtime verification.
---

# HR OS — verify recipe

## Launch

Both dev servers are usually already running (check first, don't blindly restart):

```bash
lsof -iTCP:4000 -sTCP:LISTEN -P   # backend (Express)
lsof -iTCP:5173 -sTCP:LISTEN -P   # frontend (Vite)
pg_isready                        # Postgres must be up too
```

If not running:

```bash
cd backend && npm run dev   # :4000
cd frontend && npm run dev  # :5173
```

Login: `admin@example.com` / `Admin123!` (bootstrap HR/Admin user).

DB for direct psql inspection/seeding: `postgresql://hros:hros@localhost:5432/hros`.

## Drive it

This is a GUI surface (React SPA). Use Playwright directly (not the committed
`frontend/e2e/*.spec.ts` suite — those are the author's own tests/evidence,
re-running them is re-running CI, not independent verification). A standalone
driver script works well:

```js
const { chromium } = require("<repo>/frontend/node_modules/@playwright/test");
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto("http://localhost:5173/login");
// ...fill #email/#password, click 'Log In', waitForURL('**/dashboard')
```

Take `page.screenshot({ path, fullPage: true })` at each meaningful step, and
capture `page.on("console", ...)`/`page.on("pageerror", ...)` — this app has at
least one gap (see Gotchas) that only shows up as a `pageerror`, never in the UI.

## Known real-provider limitation

`AI_PROVIDER=openai` is configured locally, but the real OpenAI provider
reliably fails (`BUG-001`, Closed — Accepted As-Is) for both URL-sourced and
synthetic-fixture candidates. When seeding a Candidate for verification that
needs a `COMPLETE` AI Evaluation, don't wait on the real pipeline — insert the
`ai_evaluations` row directly via `psql` (see the existing e2e specs for the
exact INSERT shape) instead of relying on the fire-and-forget real analysis.

## Gotchas

- **Pages with an initial `reload()` on mount (`JobDetail.tsx`, `CandidateDetail.tsx`) have no error handling around it.** If the fetched resource 404s (bad/stale id, deleted record), the page renders `Loading…` forever — no error message, no back-navigation — and the actual error only surfaces as an uncaught `pageerror` in the browser console, invisible to a real user. This is a systemic pattern across screens, not specific to one Task's diff — worth flagging in any verify report that touches a detail page, not silently working around it.
- Organization Setup / Jobs / Candidate flows all use plain `<select>`/`<input>` with stable `id` attributes (e.g. `#dept-name`, `#job-description`, `#interview-outcome`) — prefer those selectors over text matching where available, they're stable across copy changes.
- Job creation no longer uses "Job Templates" (removed, `PRD-DEC-006`) — job content fields (`#job-description`, `#job-requirements`, etc.) are entered directly on `/jobs/new`. Three pre-existing e2e specs (`candidate-ranking`, `candidate-compare`, `candidate-intake`) still reference the removed "Job Templates" nav link and are currently broken as a result — unrelated pre-existing issue, not something to "fix" mid-verification.
