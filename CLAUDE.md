# CLAUDE.md

## Commit conventions
- Use Conventional Commits: feat:, fix:, refactor:, test:, docs:, chore:
- Subject line under 72 characters
- Body: brief bullet list of what changed and why, when non-trivial
- Include a Co-Authored-By trailer for Claude Code

## Workflow
- Work one phase at a time per `codebase-intelligence-assistant-spec.md` — do not start the next phase
  until the current one is committed
- Do not save up a phase's work for one commit at the end. Commit incrementally as
  logical units of work are finished within the phase (e.g. one commit per module,
  per test file, per meaningful step) — at least 5 commits per phase, each pushed to
  `origin main` as it's made, without waiting to be asked
- Run pytest before each commit; do not commit failing tests
- After the phase's final commit/push, stop, report what phase was completed and
  list what was committed, and wait before starting the next phase
- Ask before modifying files outside the phase currently in progress
