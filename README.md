# PR_AGENT

A Codex workflow and companion desktop app for making careful, reviewable contributions to open-source projects.

The repository combines two pieces:

- **Upstream PR Contributor skill** — a repeatable process for finding a suitable issue, checking that nobody is already working on it, reproducing or validating it, implementing a focused change, testing it, and following the upstream review.
- **Contribution Monitor** — a small Windows desktop app that tracks your GitHub pull requests, contribution history, and candidate repositories.

## Use the Codex workflow

Copy [`skills/upstream-pr-contributor/SKILL.md`](skills/upstream-pr-contributor/SKILL.md) into a Codex skill directory, or ask Codex to use the skill from this repository. For a project-specific workflow, copy and adapt [`AGENTS.md`](AGENTS.md) into your working repository. See [the workflow guide](docs/workflow.md) for the full process and configuration guidance.

The workflow favors confirmed, reproducible work over PR volume. Repository rules and maintainer decisions take precedence. It does not promise that a PR will be accepted or merged.

## Contribution Monitor

The monitor is a read-only GitHub PR dashboard. It can show PR review and check status, merged contributions, candidate repositories, and contribution statistics. It uses a GitHub credential already available on the machine when present; it does not bundle or persist a token.

See [`app/README.md`](app/README.md) for setup, usage, tests, and packaging instructions. The app source and tests are in `app/`; generated executables and build outputs are intentionally excluded.

## Personal workflow records

Contribution history, private research notes, API snapshots, and local repository clones are maintained separately from this reusable project. Keep account-specific records in your own workspace and publish only material you intend to make public.

