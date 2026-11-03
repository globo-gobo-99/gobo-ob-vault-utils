# Agent session tools — unfinished local scaffold

Portable native Sync cursor and conservative metadata primitives; not a complete maintenance CLI or skill.

- [Plan](PLAN.md) — Bounded maintenance implementation and verification.
- [Primitives](vault_maintenance.py) — Cursor and metadata parsing helpers.
- [Tests](tests/test_maintenance.py) — Four bounded fixture regression checks.

Run `python3 -m unittest discover -s tests -v`. No live vault sweep, external publication, or nightly task has run. Next: partial-line baseline safety, explicit CLI/checkpoint transactions, root-arrival moves with reference updates/collision/concurrent-edit protection, and packaged skill. Keep dry-run default and fixture-only validation until reviewed.
