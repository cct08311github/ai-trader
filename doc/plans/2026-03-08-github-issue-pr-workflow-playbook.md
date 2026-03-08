# GitHub Issue + PR Workflow Playbook

## Purpose

Use GitHub Issues and Pull Requests as the primary development management system.
Do not use ad hoc local files as the source of truth for detailed task tracking.

This playbook is designed for:
- human developers
- AI coding agents
- multi-agent / multi-branch parallel execution

## Core Principle

**Issue = task record**

**Branch = implementation workspace**

**PR = delivery and review record**

**Main = only stable integration line**

## Why This Works Better Than Local Progress Files

Problems with local progress files:
- easy to drift from real code state
- no enforced status lifecycle
- weak traceability between task, code, review, and tests
- easy for multiple AI sessions to overwrite or misread status
- hard to audit who changed what and why

Benefits of GitHub-native workflow:
- each task has a durable ID
- issue, branch, commit, PR, review, and CI are linkable
- open vs in-progress vs done is visible
- easier to parallelize work safely
- better audit trail for later debugging and handoff

## Standard Workflow

### 1. Check for an Existing Issue

Before starting work:
- search GitHub issues
- do not start coding if the work is already tracked
- if an existing issue matches, use that issue

### 2. Create an Issue for New Work

If no issue exists:
- create a new issue first
- define scope, acceptance criteria, risks, and validation
- apply labels

Recommended labels:
- `backend`
- `frontend`
- `ops`
- `documentation`
- `process`
- `enhancement`
- `bug`
- `in-progress`

### 3. Mark the Issue In Progress

When work actually starts:
- add `in-progress`
- optionally assign the developer / owner
- leave a short comment if needed:
  - branch name
  - intended scope
  - dependencies or blockers

### 4. Create a Dedicated Branch From Main

Rules:
- branch from latest `main`
- one issue per branch whenever possible
- do not mix unrelated work

Suggested naming:
- `codex/<short-topic>`
- `fix/<short-topic>`
- `feat/<short-topic>`

Examples:
- `codex/pm-review-history-api`
- `codex/dashboard-stress-test`
- `fix/reports-context-auth`

### 5. Implement and Test

While working:
- keep scope aligned with the issue
- update tests with the code change
- avoid unrelated cleanup unless explicitly included in scope
- do not silently expand work beyond the issue

Minimum expectations:
- code change
- test evidence or explicit reason tests were not run
- docs/runbook updates if behavior changed

### 6. Push and Open a PR

PR must include:
- summary
- related issue
- tests run
- risks / rollout notes
- operational or documentation impact

Recommended pattern:
- `Closes #<issue>`

This ensures merge automatically closes the issue when appropriate.

### 7. Link the PR Back to the Issue

Every in-progress issue should contain:
- PR URL
- current implementation status if useful

This is critical for AI handoff and cross-session continuity.

### 8. Review, Merge, Clean Up

After approval:
- merge into `main`
- delete merged branch
- prune local/remote stale branches
- remove `in-progress` from issue if not auto-closed

## Roles of Each Artifact

### GitHub Issue

Use for:
- problem statement
- scope
- acceptance criteria
- priority
- dependencies
- execution status

Do not use issue for:
- storing full patch details
- long changelog-style code narration

### Branch

Use for:
- isolated implementation of one task

Do not use branch for:
- tracking task status
- long-lived mixed-purpose work

### PR

Use for:
- implementation summary
- code review
- test evidence
- merge gate

Do not use PR for:
- replacing issue definition
- carrying unrelated follow-up tasks

### Local Status File (`progress.md` or equivalent)

Use for:
- high-level current state
- handoff summary
- mainline policy
- immediate next recommended task

Do not use it for:
- detailed backlog
- authoritative completion tracking
- per-subtask truth

## Recommended Repo Conventions

### Labels

At minimum:
- `bug`
- `enhancement`
- `documentation`
- `backend`
- `frontend`
- `ops`
- `process`
- `in-progress`

### Templates

Recommended:
- issue template for feature/task work
- PR template with:
  - summary
  - related issue
  - testing
  - risk
  - docs/ops impact
  - issue linkback check

### Mainline Policy

Recommended policy:
- `main` is the only active integration branch
- all work starts from `main`
- merged branches should be deleted
- stale merged branches should be periodically pruned

## AI Agent Rules

For AI sessions, enforce these rules:

1. Check GitHub issues before starting work.
2. If no issue exists, create one before coding.
3. Mark the issue `in-progress` when implementation begins.
4. Create a dedicated branch from `main`.
5. Push changes and open a PR.
6. Add the PR link back to the issue.
7. Do not use local progress files as the detailed backlog source of truth.
8. Only update local handoff files with high-level state, not full task management.

## Example Operating Loop

1. Review open GitHub issues.
2. Choose one issue.
3. Add `in-progress`.
4. Create branch from `main`.
5. Implement.
6. Run tests.
7. Push branch.
8. Open PR.
9. Comment PR link on issue.
10. Merge after review.
11. Delete merged branch.
12. Return to step 1.

## Migration Plan for Existing Projects

If a project currently uses a local tracking file:

1. Keep the file, but reduce it to summary/handoff only.
2. Create GitHub issues for all still-meaningful backlog items.
3. Add labels and templates.
4. Update project instructions (`AGENTS.md`, `CONTRIBUTING.md`, runbooks).
5. Enforce issue-first behavior for all new work.
6. Periodically prune merged branches.

## Anti-Patterns

Avoid:
- starting work without an issue
- one branch covering multiple unrelated tasks
- PRs with no linked issue
- local checklist files acting as the true backlog
- keeping merged branches around indefinitely
- reopening old stale branches instead of rebasing fresh from `main`
- AI sessions inventing task state that is not reflected in GitHub

## Minimal Policy You Can Reuse Across Projects

Copy this into any project:

> We use GitHub Issues and PRs as the primary development workflow.
> Before starting work, check for an existing issue.
> If none exists, create one and mark it `in-progress` when implementation starts.
> Create a dedicated branch from `main`, complete the work, run tests, push, and open a PR.
> Add the PR link back to the issue.
> Local progress files may be used only for high-level handoff summaries, not as the detailed source of truth.
