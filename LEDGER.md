# Implementation ledger

- Task 1: 12 fixture tests pass after observed red failures (maintenance-t1-red.log, private r4 evidence). Explicit baseline/dry-run/apply CLI, partial history handling, rotation/gap checks, checked metadata writes and private atomic cursor implemented. No live vault mutation or remote publication.
- Ruling: stdlib-only script runs directly on Linux Python 3.11+, without installing uv on the host — no runtime dependencies need an environment; target Dev-Pod already has uv. Cost if wrong: development commands need adapting for extra dependencies, which are not currently used.
