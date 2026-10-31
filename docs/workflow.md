# End-to-end contribution workflow

This guide is for contributors using Codex to prepare work for upstream review. It is designed to preserve context between sessions while keeping live repository state verifiable.

## Before implementation

1. Read the target repository's contribution guide and applicable `AGENTS.md` or equivalent instructions.
2. Confirm the repository is maintained and that its issue, PR, and review activity is current enough for a contribution.
3. Search issues, discussions, branches, and open PRs for duplicate or claimed work. Read maintainer comments, not just the issue title.
4. For a bug, reproduce it on the unmodified base and record the input, observed behavior, and expected behavior. For a feature, validate the use case and agree on its scope with maintainers when appropriate.
5. Stop or choose a different issue if the behavior is not reproducible, the design is undecided, or another contributor already owns the work.

## Implement and verify

Keep the patch focused and compatible with the project's existing design. Add regression or feature tests that fail for the relevant behavior before the fix and pass after it. Run focused tests first, then related checks and broader tests where practical. Record exact commands and distinguish code failures from unavailable services or infrastructure.

Review the complete diff before publishing. Commits should reflect the actual development process and follow upstream norms. Do not add unrelated changes, artificial line count, empty commits, or knowingly broken final code to meet a metric.

## Open and maintain the PR

Push a branch to the contributor's fork and open an upstream PR. Link the issue, explain the before-and-after behavior, list the tests, and mention limitations. Check CI and respond to review requests with code changes and concise explanations. Keep the history current, and report a PR as merged only when GitHub confirms a merge timestamp.

## Carry context between sessions

Use `AGENTS.md` for stable project-wide instructions and a separate contribution-history file for completed work. Treat those files as context, not as authoritative live state: recheck issue ownership, PR status, CI, and reviews before acting. Keep tokens, credential output, and private notes out of committed files.

## Optional personal settings

Users can maintain private preferences such as target repository types, preferred batch size, reporting style, or minimum contribution scope. Keep these settings separate from universal project instructions. A numeric threshold must never justify unrelated code or weaker tests, and commit-count preferences should defer to upstream conventions.

