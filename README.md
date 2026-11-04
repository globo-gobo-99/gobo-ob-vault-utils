# devpod-agent-tools

- Portable skills and deterministic maintenance for recent Obsidian Sync changes.
- Python 3.11+; standard library; dry-run by default.
- [Usage and recovery](USAGE.md) · [CLI](vault_maintenance.py) · [Portable skill](skills/vault-maintenance/SKILL.md).
- [Source Snapshot skill](skills/source-snapshot/SKILL.md) — Disposable commit-pinned Markdown source trees for Obsidian review.
- [Examples](examples/README.md) · [Manifest](manifest.json) · [Plan](PLAN.md) · [Review ledger](LEDGER.md) · [MIT license](LICENSE).
- No scheduler, model calls, global installation, or live-vault tests. Source snapshots use Git and keep review output separate from authoritative source.

```bash
python3 -m unittest discover -s tests -v
```
