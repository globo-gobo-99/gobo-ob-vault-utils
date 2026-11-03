# Portable vault maintenance implementation plan

> **For agentic workers:** Use executing-plans to implement this plan task by task. No cloud resource start, external publication or live personal vault mutation is authorized after the expired r4 commissioning window.

**Goal:** Finish the deterministic portable maintenance skill specified by the r4 handoff.

**Architecture:** A standard-library Python script reads one explicit native Sync log and stores a cursor outside its explicitly selected vault. Dry-run reports are default. Checked edits use snapshots and private checkpoints; ambiguous content is reported without guessing. Separate root-arrival move/reference support is gated by fixture verification before activation.

**Tech Stack:** Python 3.11+, unittest, uv for isolated development when needed. No runtime packages or Hermes dependency.

**Spec:** Wreckless Abandon `20261102-DevPod-Handoff-r4.md`, portable maintenance paragraph. Do not copy personal notes/logs/auth into this repository.

## Global constraints

- Recent logged changes only; baseline skips prior and partially written history. Rotation/gaps fail closed.
- Preserve fields/prose and never infer creation dates. Timezone configurable, default America/Boise.
- No article fetching, summaries, curation or live personal vault sweep.
- Explicit paths, checkpoint outside vault, dry-run default, no symlink traversal, no collision guessing.
- Reread before edits, skip concurrent changes, durable checkpoint only after successful work; repeat is idempotent.
- Public source only generic fixtures; no account binding or credentials.

## Review focus

- First baseline in the middle of a log record must not capture a historical arrival later.
- An event arriving during a run must remain pending for the next cursor read.
- A stale checkpoint, log rotation or malformed completion must not silently advance coverage.
- A human editing between planning and apply must retain their bytes and leave the cursor retryable.
- Ambiguous links, symlink targets and destination collisions must block unsafe moves.

## Task 1: Native log cursor and checked metadata CLI

Files: `vault_maintenance.py`, `tests/test_maintenance.py`, `tests/test_cli.py`, `README.md`.

- [x] Write failing fixtures for partial baseline, partial new record, upload versus download provenance, CLI dry-run/baseline/apply, unclosed YAML, private checkpoint, concurrent edit and symlink exclusion.
- [x] Run `python3 -m unittest discover -s tests -v`; confirm failures reflect missing behavior.
- [x] Implement `read_changes(log_path, cursor, timezone)` with bounded incremental reads and stable cursor fingerprints. Add `build_plan(vault, changes, stamp)` and `apply_plan(vault, plan)`; preserve unsupported frontmatter and report unresolved metadata.
- [x] Add `baseline` / `run` CLI with explicit `--vault`, `--sync-log`, `--checkpoint`, `--timezone`; `run` defaults to dry-run, `--apply` saves only after checks. Internal state outside vault, atomic checkpoint writes, same-process lock.
- [x] Run the full fixture suite, CLI fixture smoke and diff checks. Commit locally only.

## Task 2: Root-arrival moves, references and file checks

Files: split a focused reference module if needed; add fixture tests.

- [x] Test actual Downloaded arrivals versus uploads, dates, root exemptions/exclusions, collision, ambiguous wiki names, Markdown/embedded relative paths, date-note navigation, concurrent changes and interrupted apply recovery.
- [x] Implement only after red fixtures; physical no-overwrite moves with original names, explicit rewrite checks and durable recovery journal. Do not activate a move if any affected reference is unresolved.
- [x] Test idempotence, crash recovery and no retrospective sweep. Keep ambiguity visible rather than guessing.
- [x] Commit locally only.

## Task 3: Portable skill and packaging

Files: `skills/vault-maintenance/SKILL.md`, examples, root README/license/project metadata.

- [ ] Package standalone scripts without copied host state. Explain bounded nightly invocation without installing a timer. Include deterministic manifest/schema attribution to the public Wanderloots core guide; exclude its knowledge-compilation workflow.
- [ ] Validate skill and complete fixture behavior. Request independent review under the code-review skill, fix demonstrated problems, update r4 checkpoint.
- [ ] Record unpublished local commits and remaining human acceptance. No whole-project completion claim while required manual enrollment/device checks remain.
