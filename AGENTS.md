# Open-Source Contribution Workflow

When asked to create or prepare upstream PRs, treat the request as an end-to-end contribution task unless the user limits the scope. Continue each contribution until it is ready to await CI, maintainers, or reviewers. Never describe an open PR as merged.

## Candidate and issue selection

- Prefer repositories that match the user's interests and have recent maintenance, active reviews, and clear contribution guidance.
- Check the issue, discussions, open PRs, assignees, repository instructions, and recent project activity before choosing a task.
- Avoid duplicate work, already-claimed issues, rejected approaches, and unresolved design questions. If a task is taken or blocked, select another candidate when the user requested a count.
- Contributions may fix bugs or add focused features, defensive handling, performance improvements, tests, examples, or documentation.
- For non-trivial changes, describe the proposed scope on an issue and wait for maintainer acknowledgement when project norms call for it.

## Implementation and validation

1. Reproduce the reported behavior on the unmodified base, or validate the need and expected behavior for a feature.
2. Make a focused change that follows the project's architecture and compatibility expectations.
3. Add tests that demonstrate externally observable behavior.
4. Run focused tests and the relevant formatters, linters, type checks, and hooks. Run broader checks when practical and state exactly what passed.
5. Review the final diff and commit history. Do not inflate line counts or add meaningless commits; follow the upstream project's conventions.
6. Open a PR with the issue link, behavior, tests, limitations, and required checklist items.
7. Recheck CI and reviewer feedback, make requested changes, and update the PR description when needed.

## Reporting and records

- For a batch request, provide a brief update after each completed PR and a final list of links, validation, and remaining external blockers.
- Keep a contribution history if the user requests one. Record issue acknowledgement, reproduction or feature validation, changes, test commands, commits, PR, CI, review feedback, and current status.
- Recheck GitHub state live. Local notes may be stale.
- Do not sign CLAs, approve workflows, merge PRs, or send external messages unless the user explicitly authorizes that action.

## User-specific preferences

Apply numeric contribution-size or commit-count preferences only when the user configures them for their own workflow. They must not override upstream conventions, encourage unrelated scope, or weaken final validation. The final PR head must be coherent and tested.

