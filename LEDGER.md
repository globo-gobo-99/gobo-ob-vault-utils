# Implementation ledger

- Task 1: 12 fixture tests pass after observed red failures (maintenance-t1-red.log, private r4 evidence). Explicit baseline/dry-run/apply CLI, partial history handling, rotation/gap checks, checked metadata writes and private atomic cursor implemented. No live vault mutation or remote publication.
- Ruling: stdlib-only script runs directly on Linux Python 3.11+, without installing uv on the host — no runtime dependencies need an environment; target Dev-Pod already has uv. Cost if wrong: development commands need adapting for extra dependencies, which are not currently used.
- Task 2: 22 fixture tests pass after observed move/crash red failures. Root Downloaded arrivals move without overwrite, wiki/Markdown/embedded/own-relative paths update, day navigation is created, and external journal recovers filesystem mutation before progress-save. Collision/ambiguous references hold cursor; changed notes and new references stop apply/recovery. No live vault touched.
