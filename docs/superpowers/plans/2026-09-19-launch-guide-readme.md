# Local Launch Guide README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the root README into the single step-by-step entry point for validating the current repository and launching the complete local crisis demo once all six workstreams are implemented.

**Architecture:** Keep one progressive how-to guide: current runnable baseline first, then the ordered full-stack launch, controlled external interaction, optional Azure deployment, reset, and troubleshooting. Clearly label commands that depend on planned files so the guide never implies that unimplemented components exist.

**Tech Stack:** Markdown, Node.js/npm, Supabase/Postgres, Azure Functions/SWA, HappyRobot, shell commands

---

## Delivery constraints

- No TDD or documentation test framework.
- Modify only `README.md` in the implementation task.
- Use exact variables, routes, IDs, flags, and filenames frozen by the seven crisis plans.
- Mark current commands as available and full-stack commands as available after implementation.
- Prefer one recommended path over alternatives.
- Do not include secrets, contact details, or production-security guidance.

## Task 1: Replace the README with the progressive launch guide

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Preserve project context and add status**

Keep the project name, event, challenge, and links. Add a capability table that marks contracts as available now and the six workstreams as planned until their files exist.

- [ ] **Step 2: Add the current quick start**

Document:

```bash
npm ci
npm run contracts:check
```

Include the two expected PASS lines.

- [ ] **Step 3: Add full local setup in dependency order**

Document prerequisites, `.env`, migration/seed, Gateway, HappyRobot workflows, dashboard, controller dry-runs, E2E, and controlled interaction. Every section includes a continue condition.

- [ ] **Step 4: Add Azure, stop/reset, and troubleshooting**

Keep Azure optional. Reset only the two named demo runs by reapplying `supabase/seed.sql`. Include common symptoms for missing env, dirty runs, workflow lookup, `version_conflict`, and Realtime fallback.

## Task 2: Verify the guide

**Files:**

- Verify: `README.md`

- [ ] **Step 1: Verify current runnable commands**

Run:

```bash
npm ci
npm run contracts:check
```

Expected: DANA and wildfire contract chains pass.

- [ ] **Step 2: Verify references and hygiene**

Run:

```bash
pending_pattern='TO''DO|TB''D|PLACE''HOLDER'
rg -n "$pending_pattern" README.md && exit 1 || true
git diff --check -- README.md
```

Expected: no placeholder match and no whitespace error.

- [ ] **Step 3: Commit and push the dedicated README branch**

```bash
git add README.md docs/superpowers/plans/2026-09-19-launch-guide-readme.md
git commit -m "docs: add local launch guide"
git push
```
