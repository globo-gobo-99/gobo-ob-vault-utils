# Agent session tools

Portable deterministic maintenance for recent native Obsidian Sync changes, with no inference or Hermes dependency.

- [CLI](vault_maintenance.py) — Repository command and import entrypoint.
- [Portable skill](skills/vault-maintenance/SKILL.md) — Copyable workflow and standalone implementation.
- [Examples](examples/README.md) — Explicit nightly invocation without installation.
- [Manifest](manifest.json) — Versioned interface and coverage boundaries.
- [Plan](PLAN.md) — Implementation requirements and fixture evidence.
- [Ledger](LEDGER.md) — Decisions and independent review receipts.
- [License](LICENSE) — MIT reuse and attribution terms.

Linux Python 3.11+; runtime is standard-library only. `python3 -m unittest discover -s tests -v` runs disposable fixtures. No tests use a personal vault, private log, account state or cloud compute. The full skill folder is independently copyable; no symlink to this repository is needed. No scheduler or global skill installation is performed.

## Commands

Select the intended replica/log explicitly, then establish its cursor once:

```bash
python3 vault_maintenance.py baseline --vault /path/to/replica \
  --sync-log /path/to/native/sync.log --checkpoint /private/state/cursor.json
python3 vault_maintenance.py run --vault /path/to/replica \
  --sync-log /path/to/native/sync.log --checkpoint /private/state/cursor.json
```

`run` is dry-run by default; `--apply` applies checked work and saves the cursor only after success. Reports omit replacement note text; keep reports private because they contain paths/diagnostics. `baseline` does not sweep old history or loose files. Specify `--timezone` (default America/Boise), `--daily-folder` (default Sessions) and repeatable `--exclude` patterns at baseline and keep them consistent. Exclusions apply to reference checks too: automated moves cannot repair references hidden by an exclusion.

New root arrivals move to `Sessions/YYYY-MM-DD/` with original names. Common wiki/Markdown links and embeds, own-relative links and daily/README navigation are repaired. Existing root uploads remain put; new local files are recognized against the baseline root inventory. Default exemptions cover README/AGENTS/license, date-named daily notes, config suffixes, hidden paths, symlinks and dependencies/build output. No overwrite or ambiguous basename resolution. Missing creation dates are reported, never invented. Metadata fixes preserve human text and intentional trailing spaces.

Exit 2 is incomplete work, coverage or an error. Cursor stays unadvanced on gaps/rotation, collision or ambiguous affected links. A pending journal blocks normal runs. Use the same options with `recover --apply`, inspect unexpected changes, and then rerun maintenance to save the log cursor. Journals are mode600 outside the vault and may contain private note text. Do not remove them to force progress.

Supported completion records are native `ob` 0.0.14's `[ISO timestamp] Downloaded path`, `Upload complete path`, `Merge successful path`, and `Conflicted copy stored path`; other completion spellings fail closed. Unread log batches over 8MiB require explicit investigation; they are not silently truncated. This is recent-change coverage, not an audit of all historical files.

## Limits and provenance

Common inline/reference Markdown and wiki links are supported; code samples are preserved. HTML links are not rewritten; detected affected HTML/query/unsupported references hold moves. Unusual Markdown, anchor existence and hidden/excluded content still need explicit review. Filesystem hard links must work within the vault. A reference scan reads visible Markdown to find backlinks when moves are planned; ordinary lint targets logged changes only. Hash/reread guards do not impose a distributed lock on editors in the final check/replace interval; schedule a quiet period and retain normal Sync/Git recovery.

The r4 handoff supplied the maintenance contract. [Wanderloots' public core guide](https://github.com/wanderloots-tutorials/vibe-coding/blob/main/wanderloots-llm-wiki-core-setup-v1.0.0.md) informed the explicit schema/versioned manifest and deterministic lint approach. Its knowledge-compilation, curation and summary workflow is not included; no guide prose is copied. Native log format was checked against the official `obsidian-headless` package 0.0.14.

This repository is prepared locally for later publication under gobo-99. The expired commissioning deadline permits free local work only; no remote repository has been created for this component.
