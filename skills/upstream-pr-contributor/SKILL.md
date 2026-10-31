---
name: upstream-pr-contributor
description: Find, validate, implement, test, and submit focused contributions to upstream open-source repositories, then handle CI and review feedback. Use when the user asks to create or prepare one or more upstream PRs.
---

# Upstream PR Contributor

Carry the user's requested contribution through to a reviewable upstream PR. A PR is not complete merely because a patch exists locally, and an open PR is not merged.

## 1. Inspect the project

- Read `AGENTS.md`, contribution guides, development setup, and relevant code and tests.
- Check current maintenance, issue and PR activity, labels, assignees, discussions, and reviewer comments.
- Search for duplicate issues and existing implementations. Do not compete with an active contributor.
- If a task is already handled, claimed, rejected, or blocked on a design decision, explain briefly and select another task when the requested batch allows it.

## 2. Confirm the problem or need

- For a bug, reproduce it on the unmodified base with a minimal test or script and preserve the observed failure.
- For a feature, state the use case, expected behavior, alternatives, and compatibility implications. Seek maintainer agreement before non-trivial implementation when the project expects it.
- If evidence does not support the report, do not manufacture a fix. Report what you found and continue with another candidate if appropriate.

## 3. Implement and test

- Make a focused, backward-compatible change following the project's architecture and dependency rules.
- Add meaningful tests for the user-visible behavior, including relevant edge cases.
- Run focused tests, then related tests and applicable formatting, lint, type, and pre-commit checks. Use broader checks when reasonable.
- Review the final diff and commit history. Keep commits honest and aligned with repository practice. Never pad code or commits to satisfy arbitrary metrics.
- Record exact checks and distinguish failures caused by the patch from baseline or infrastructure failures.

## 4. Submit and follow up

- Push to the user's fork and create an upstream PR with issue linkage, rationale, behavior, tests, limitations, and required checklist items.
- Monitor CI and reviewer feedback. Make requested changes, rerun affected checks, and reply with concise evidence.
- Update the user's contribution history after submission and when status changes, if such a file exists or the user requested one.
- Stop when the PR is reviewable and only external CI, maintainer, or reviewer action remains. Report remaining blockers plainly.

## Batch requests

For a request to create N PRs, work through N distinct contributions, briefly report each one as it reaches a reviewable state, and finish with links, validation, and current status. Do not stop after a candidate list when the user asked for completed PRs.

## Safety and accuracy

- Never discard unrelated user changes.
- Do not sign a CLA, approve a workflow, merge, or send messages beyond the issue/PR communication needed for the explicitly requested contribution.
- Do not claim a full test suite passed unless it actually ran and passed.
- Treat local notes as potentially stale; verify live GitHub state before choosing work or reporting status.

