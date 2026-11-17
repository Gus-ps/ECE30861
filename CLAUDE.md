@AGENTS.md

## Current work on this branch

- The task list is `PHASE5_TASKS.md`. Its Rules section governs every change on
  `Jon-Gus_branch`.
- Choices the agent may not make alone go in `PHASE5_DECISIONS.md` as 1 to 5 options.
- Load the `minimal-code` skill (`.claude/skills/minimal-code/`) before writing any code.
- The test gate is `python scripts/test_gate.py`. It passes only when there are no failures
  beyond the recorded baseline.
