@AGENTS.md

## Claude's role in this repo

- Claude owns the specs in `docs/specs/`, the task list in `docs/TASKS.md`,
  and reviews every Codex PR against the task's acceptance criteria and the
  specs.
- When a review finds problems, comment on the PR with concrete fixes; keep the
  task in `review` until they are resolved, then set it to `done` in the merge.
- Ask Saheb before merging, pushing to `main`, or changing a spec decision.
