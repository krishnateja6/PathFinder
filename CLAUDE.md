# CLAUDE.md

## Commit conventions
- Use Conventional Commits: feat:, fix:, refactor:, test:, docs:, chore:
- Subject line under 72 characters
- Body: brief bullet list of what changed and why, when non-trivial
- Include a Co-Authored-By trailer for Claude Code

## Workflow
- Work one phase at a time per `codebase-intelligence-assistant-spec.md` — do not start the next phase
  until the current one is committed
- Run pytest before committing; do not commit failing tests
- After a phase's tests pass, commit and push to `origin main` without waiting to be asked,
  then stop, report what phase was completed and what was committed, and wait before
  starting the next phase
- Ask before modifying files outside the phase currently in progress
