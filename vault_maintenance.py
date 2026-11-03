#!/usr/bin/env python3
"""Recent native Sync changes and conservative Markdown maintenance, without inference."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from zoneinfo import ZoneInfo

COMPLETED = re.compile(
    r'^\[([^]]+)\] (Downloaded|Upload complete|Merge successful|Conflicted copy stored) (.+)$'
)
MAX_BATCH_BYTES = 8 * 1024 * 1024
EXCLUDED = {"node_modules", "vendor", "__pycache__", "dist", "build"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_changes(log_path, cursor, timezone="America/Boise"):
    """Read complete records only; keep rotation/gap failures at the previous cursor."""
    zone = ZoneInfo(timezone)
    with Path(log_path).open("rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Sync log must be a regular file")

        def point(offset, skip_partial=False):
            source.seek(max(0, offset - 256))
            fingerprint = digest(source.read(min(256, offset)))
            return {"device": info.st_dev, "inode": info.st_ino, "offset": offset,
                    "prefix": fingerprint, "skip_partial": skip_partial}

        def result(events, new_cursor, issues=(), baseline=False):
            return {"events": events, "cursor": new_cursor, "complete": not issues,
                    "baseline": baseline, "issues": list(issues)}

        if cursor is None:
            source.seek(max(0, info.st_size - 1))
            partial = info.st_size > 0 and source.read(1) != b"\n"
            return result([], point(info.st_size, partial), baseline=True)
        offset = cursor["offset"]
        if (not isinstance(offset, int) or offset < 0 or offset > info.st_size
                or cursor["device"] != info.st_dev or cursor["inode"] != info.st_ino
                or point(offset)["prefix"] != cursor["prefix"]):
            return result([], cursor, ["log-rotation-or-gap"])
        if info.st_size - offset > MAX_BATCH_BYTES:
            return result([], cursor, ["unread-log-exceeds-batch-limit"])
        source.seek(offset)
        data = source.read(info.st_size - offset)
        end = data.rfind(b"\n") + 1
        if not end:
            return result([], cursor)
        try:
            lines = data[:end].decode("utf-8").splitlines()
        except UnicodeDecodeError:
            return result([], cursor, ["invalid-log-encoding"])
        if cursor.get("skip_partial"):
            lines = lines[1:]
        events, issues = [], []
        for line in lines:
            match = COMPLETED.match(line)
            if match:
                stamp, action, path = match.groups()
                try:
                    when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    if when.tzinfo is None:
                        raise ValueError("Timestamp has no zone")
                    day = when.astimezone(zone).date().isoformat()
                except ValueError:
                    issues.append("unusable-event-timestamp")
                    continue
                if (path.startswith("/") or ".." in Path(path).parts
                        or "\x00" in path or "\\" in path):
                    issues.append("unsafe-event-path")
                    continue
                event = {"path": path, "date": day, "arrival": action == "Downloaded"}
                if event not in events:
                    events.append(event)
            elif any(word in line for word in (
                    "Downloaded", "Upload complete", "Merge successful", "Conflicted copy stored")):
                issues.append("unrecognized-completion-format")
        # Check the exact bytes used for planning still exist at their original position.
        source.seek(offset)
        if source.read(end) != data[:end] or os.fstat(source.fileno()).st_size < info.st_size:
            issues.append("log-changed-during-read")
        return result(events if not issues else [],
                      cursor if issues else point(offset + end), issues)


def lint_text(text, stamp):
    """Add missing modified metadata only. Never invent created or rewrite prose."""
    issues = []
    newline = "\r\n" if "\r\n" in text else "\n"
    if text.startswith("\ufeff"):
        return {"text": text, "issues": ["unsupported-byte-order-mark"]}
    if text.startswith("---" + newline):
        closing = re.search(r"^---[ \t]*\r?$", text[3 + len(newline):], re.M)
        if closing is None:
            return {"text": text, "issues": ["unclosed-frontmatter"]}
        end = 3 + len(newline) + closing.start()
        front = text[3 + len(newline):end]
        for key in ("created", "modified"):
            if len(re.findall(rf"^{key}\s*:", front, re.M)) > 1:
                return {"text": text, "issues": ["duplicate-date-field"]}
        if not re.search(r"^created\s*:", front, re.M):
            issues.append("missing-created")
        if not re.search(r"^modified\s*:", front, re.M):
            text = text[:end] + f'modified: "{stamp}"{newline}' + text[end:]
    else:
        issues.append("missing-created")
        text = f'---{newline}modified: "{stamp}"{newline}---{newline}' + text
    return {"text": text, "issues": issues}


def safe_file(vault, relative):
    """Refuse hidden/excluded paths and every symlink component before opening."""
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or any(
            part in (".", "..") or part.startswith(".") or part in EXCLUDED for part in rel.parts):
        raise ValueError("excluded-or-unsafe-path")
    path = Path(vault)
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("symlink-skipped")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("not-a-regular-file")
    return path


def snapshot(path):
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    if (before.st_ino, before.st_dev, before.st_mtime_ns, before.st_size) != (
            after.st_ino, after.st_dev, after.st_mtime_ns, after.st_size):
        raise ValueError("concurrent-change")
    return data, {"device": after.st_dev, "inode": after.st_ino,
                  "mtime_ns": after.st_mtime_ns, "size": after.st_size, "sha256": digest(data)}


def metadata_plan(vault, changes, stamp):
    if not changes["complete"]:
        raise ValueError("Cannot plan incomplete log coverage")
    edits, issues, seen = [], [], set()
    for event in changes["events"]:
        rel = event["path"]
        if rel in seen:
            continue
        seen.add(rel)
        try:
            path = safe_file(vault, rel)
            if path.suffix.lower() != ".md":
                continue
            data, state = snapshot(path)
            result = lint_text(data.decode("utf-8"), stamp)
            issues.extend({"path": rel, "issue": issue} for issue in result["issues"])
            if result["text"].encode("utf-8") != data:
                edits.append({"path": rel, "before": state, "text": result["text"]})
        except (OSError, ValueError) as exc:
            issues.append({"path": rel, "issue": type(exc).__name__ + ": " + str(exc)})
    return {"edits": edits, "issues": issues}


def fsync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_checkpoint(path, state):
    fd, temporary = tempfile.mkstemp(prefix=".cursor-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(state, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def checkpoint_lock(checkpoint):
    checkpoint.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if checkpoint.is_symlink():
        raise ValueError("Checkpoint must not be a symlink")
    fd = os.open(str(checkpoint) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


ROOT_EXEMPT = {"readme.md", "agents.md", "license", "license.md", "license.txt"}
CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"}


def inventory_files(vault, excludes=()):
    import fnmatch
    files = []
    for directory, dirs, names in os.walk(vault, followlinks=False):
        relative = Path(directory).relative_to(vault)
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in EXCLUDED
                         and not (Path(directory) / d).is_symlink()
                         and not any(fnmatch.fnmatch(str(relative / d), e) for e in excludes))
        for name in sorted(names):
            path = Path(directory) / name
            rel = path.relative_to(vault).as_posix()
            if name.startswith('.') or path.is_symlink() or any(fnmatch.fnmatch(rel, e) for e in excludes):
                continue
            if path.is_file():
                files.append(rel)
    return sorted(files)


def updated_modified(text, stamp):
    result = lint_text(text, stamp)
    if result['issues'] and any(i != 'missing-created' for i in result['issues']):
        raise ValueError('unsupported-frontmatter-for-rewrite')
    text = result['text']
    end = re.search(r'^---[ \t]*\r?$', text[4:], re.M)
    if end is None:
        raise ValueError('unclosed-frontmatter')
    stop = 4 + end.start()
    front = text[:stop]
    front = re.sub(r'^modified\s*:[^\r\n]*', f'modified: "{stamp}"', front, flags=re.M)
    return front + text[stop:]


def build_plan(vault, changes, stamp, daily_folder='Sessions', excludes=()):
    from vault_references import rewrite_references
    vault = Path(vault)
    folder = Path(daily_folder)
    if folder.is_absolute() or '..' in folder.parts or any(p.startswith('.') for p in folder.parts):
        raise ValueError('unsafe-daily-folder')
    inventory = inventory_files(vault, excludes)
    allowed = set(inventory)
    bounded = {**changes, 'events': [e for e in changes['events'] if e['path'] in allowed]}
    plan = metadata_plan(vault, bounded, stamp)
    plan['edits'] = [e for e in plan['edits'] if e['path'] in allowed]
    plan.update(moves=[], reads={}, inventory=inventory, excludes=list(excludes), retry_required=False)
    candidates = {}
    for event in changes['events']:
        rel = event['path']
        path = Path(rel)
        if (not event.get('arrival') or len(path.parts) != 1 or rel not in allowed
                or rel.lower() in ROOT_EXEMPT or path.suffix.lower() in CONFIG_SUFFIXES
                or re.fullmatch(r'\d{4}-\d{2}-\d{2}\.md', rel)):
            continue
        try:
            datetime.strptime(event['date'], '%Y-%m-%d')
            source = safe_file(vault, rel)
            _, state = snapshot(source)
            target = f"Sessions/{event['date']}/{rel}"
            destination = vault / target
            if destination.exists() or destination.is_symlink():
                plan['issues'].append({'path': rel, 'issue': 'destination-collision'})
                plan['retry_required'] = True
                continue
            # Malformed frontmatter must not be moved implicitly.
            if any(i['path'] == rel and i['issue'] != 'missing-created' for i in plan['issues']):
                plan['retry_required'] = True
                continue
            candidates.setdefault(rel, {'path': rel, 'target': target, 'before': state,
                                        'date': event['date']})
        except (OSError, ValueError) as exc:
            plan['issues'].append({'path': rel, 'issue': str(exc)})
    if not candidates:
        return plan
    moves = {rel: value['target'] for rel, value in candidates.items()}
    edit_map = {e['path']: e for e in plan['edits']}
    rewritten = {}
    blocking = False
    for rel in inventory:
        if not rel.lower().endswith('.md'):
            continue
        try:
            data, state = snapshot(safe_file(vault, rel))
            plan['reads'][rel] = state
            original = data.decode('utf-8')
            text = edit_map.get(rel, {}).get('text', original)
            text, issues = rewrite_references(text, rel, moves.get(rel, rel), moves, allowed)
            plan['issues'].extend(issues)
            if any(i.get('blocks_move') for i in issues):
                blocking = True
            if text != original:
                rewritten[rel] = {'path': rel, 'before': state, 'text': updated_modified(text, stamp)}
        except (OSError, ValueError) as exc:
            blocking = True
            plan['issues'].append({'path': rel, 'issue': 'reference-scan-incomplete: ' + str(exc)})
    if blocking:
        plan['retry_required'] = True
        plan['issues'].append({'path': '', 'issue': 'moves-held-for-reference-review'})
        return plan
    plan['edits'] = list({**edit_map, **rewritten}.values())
    plan['moves'] = list(candidates.values())

    def append_navigation(rel, lines, title):
        path = vault / rel
        existing = next((e for e in plan['edits'] if e['path'] == rel), None)
        if existing:
            text, state = existing['text'], existing['before']
        elif path.exists():
            data, state = snapshot(safe_file(vault, rel))
            plan['reads'][rel] = state
            text = data.decode('utf-8')
        else:
            state = None
            text = f'---\ncreated: {stamp[:10]}\nmodified: "{stamp}"\n---\n# {title}\n'
        changed = False
        for line in lines:
            if line not in text.splitlines():
                text = text.rstrip('\n') + '\n\n' + line + '\n'
                changed = True
        if changed or state is None:
            edit = {'path': rel, 'before': state, 'text': updated_modified(text, stamp)}
            if existing:
                plan['edits'].remove(existing)
            plan['edits'].append(edit)

    dates = sorted({m['date'] for m in plan['moves']})
    for day in dates:
        group = [m for m in plan['moves'] if m['date'] == day]
        append_navigation(f'{daily_folder}/{day}.md'.removeprefix('./'),
                          ['- [[' + m['target'].removesuffix('.md') + ']]' for m in group], day)
        append_navigation(f'Sessions/{day}/README.md',
                          ['- [' + m['path'] + '](' + __import__('urllib.parse', fromlist=['quote']).quote(m['path'])
                           + ') — File received on this date.' for m in group],
                          f'Arrivals — {day}')
    append_navigation('Sessions/README.md',
                      [f'- [{d}]({d}/README.md) — Files received on this date.' for d in dates],
                      'Sessions')
    if (vault / 'README.md').is_file():
        append_navigation('README.md', ['- [Sessions](Sessions/README.md) — Dated sessions and received files.'],
                          'Vault')
    return plan


def ensure_parent(vault, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or any(p.startswith('.') for p in rel.parts):
        raise ValueError('unsafe-destination')
    parent = Path(vault)
    for part in rel.parent.parts:
        parent = parent / part
        if parent.is_symlink():
            raise ValueError('symlink-destination')
        parent.mkdir(exist_ok=True)
        if not parent.is_dir():
            raise ValueError('destination-parent-not-directory')
    return Path(vault) / rel


def current_hash(vault, relative):
    path = Path(vault) / relative
    if not path.exists() and not path.is_symlink():
        return None
    return snapshot(safe_file(vault, relative))[1]['sha256']


def transaction_operations(plan):
    operations = []
    after = {}
    for edit in plan['edits']:
        after[edit['path']] = digest(edit['text'].encode('utf-8'))
        operations.append({'kind': 'write', 'path': edit['path'], 'text': edit['text'],
                           'before_hash': edit['before']['sha256'] if edit['before'] else None,
                           'after_hash': after[edit['path']]})
    for move in plan.get('moves', []):
        operations.append({'kind': 'move', 'path': move['path'], 'target': move['target'],
                           'hash': after.get(move['path'], move['before']['sha256'])})
    return operations


def check_plan(vault, plan):
    if plan.get('retry_required'):
        raise ValueError('Unresolved arrivals require review; cursor must remain retryable')
    if plan.get('moves') and inventory_files(vault, plan.get('excludes', ())) != plan['inventory']:
        raise ValueError('vault-inventory-changed')
    guards = dict(plan.get('reads', {}))
    guards.update({e['path']: e['before'] for e in plan['edits']})
    guards.update({m['path']: m['before'] for m in plan.get('moves', [])})
    for rel, expected in guards.items():
        if expected is None:
            if (Path(vault) / rel).exists() or (Path(vault) / rel).is_symlink():
                raise ValueError('destination-collision: ' + rel)
        elif snapshot(safe_file(vault, rel))[1] != expected:
            raise ValueError('concurrent-change: ' + rel)
    for move in plan.get('moves', []):
        destination = Path(vault) / move['target']
        if destination.exists() or destination.is_symlink():
            raise ValueError('destination-collision: ' + move['target'])


def perform_operation(vault, op):
    if op['kind'] == 'write':
        current = current_hash(vault, op['path'])
        if current == op['after_hash']:
            return
        if current != op['before_hash']:
            raise ValueError('concurrent-change: ' + op['path'])
        target = ensure_parent(vault, op['path'])
        fd, temporary = tempfile.mkstemp(prefix='.maintenance-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                mode = stat.S_IMODE(target.stat().st_mode) if current is not None else 0o600
                os.fchmod(stream.fileno(), mode)
                stream.write(op['text'].encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
            if current_hash(vault, op['path']) != op['before_hash']:
                raise ValueError('concurrent-change: ' + op['path'])
            if current is None:
                # Hard-link installation provides no-overwrite semantics, unlike rename().
                os.link(temporary, target)
            else:
                os.replace(temporary, target)
            fsync_directory(target.parent)
        finally:
            Path(temporary).unlink(missing_ok=True)
    elif op['kind'] == 'move':
        source = Path(vault) / op['path']
        target = ensure_parent(vault, op['target'])
        source_hash = current_hash(vault, op['path'])
        target_hash = current_hash(vault, op['target'])
        if source_hash is None and target_hash == op['hash']:
            return
        if source_hash != op['hash']:
            raise ValueError('concurrent-change: ' + op['path'])
        if target_hash is None:
            os.link(source, target)  # Same-filesystem, atomic refusal if destination exists.
            fsync_directory(target.parent)
        elif target_hash != op['hash'] or not os.path.samefile(source, target):
            raise ValueError('destination-collision: ' + op['target'])
        if current_hash(vault, op['path']) != op['hash']:
            raise ValueError('concurrent-change-during-move: ' + op['path'])
        source.unlink()
        fsync_directory(source.parent)
    else:
        raise ValueError('unknown-journal-operation')


def recover_journal(vault, journal, interrupt_after=None):
    journal = Path(journal)
    state = json.loads(journal.read_text())
    if state.get('schema') != 1 or state['vault'] != str(Path(vault).resolve()):
        raise ValueError('Journal belongs to another vault or schema')
    completed = state.get('completed', 0)

    def guard_unmodified():
        for rel, expected in state.get('guards', {}).items():
            if snapshot(safe_file(vault, rel))[1] != expected:
                raise ValueError('concurrent-change-in-reference-scan: ' + rel)
        if state.get('inventory') is not None:
            permitted = {o['path'] for o in state['operations']}
            permitted.update(o['target'] for o in state['operations'] if o['kind'] == 'move')
            current = set(inventory_files(vault, state.get('excludes', ()))) - permitted
            original = set(state['inventory']) - permitted
            if current != original:
                raise ValueError('vault-inventory-changed-during-transaction')

    try:
        guard_unmodified()
        # A crash may occur after filesystem mutation but before progress is saved.
        # Infer the already-completed move by its target hash, never by a filename alone.
        all_moves = {o['path']: o['target'] for o in state['operations'] if o['kind'] == 'move'}
        for op in state['operations'][:completed]:
            rel = op['path']
            expected = op['after_hash'] if op['kind'] == 'write' else op['hash']
            if op['kind'] == 'move' or (current_hash(vault, rel) is None and rel in all_moves):
                rel = all_moves[rel]
            if current_hash(vault, rel) != expected:
                raise ValueError('concurrent-change-after-partial-apply: ' + rel)
        for index in range(completed, len(state['operations'])):
            guard_unmodified()
            perform_operation(vault, state['operations'][index])
            state['completed'] = index + 1
            save_checkpoint(journal, state)
            if interrupt_after is not None and index + 1 >= interrupt_after:
                raise InterruptedError('fixture interruption after durable operation')
        journal.unlink()
        fsync_directory(journal.parent)
        return {'complete': True, 'applied': [o['path'] for o in state['operations']], 'skipped': []}
    except InterruptedError:
        raise
    except (OSError, ValueError) as exc:
        return {'complete': False, 'applied': [], 'skipped': [{'issue': str(exc)}]}


def apply_plan(vault, plan, journal=None, interrupt_after=None):
    try:
        check_plan(vault, plan)
        operations = transaction_operations(plan)
        if journal is not None and Path(journal).exists():
            raise ValueError('Pending journal must be recovered before planning again')
        if journal is not None:
            journal = Path(journal)
            if journal.resolve().is_relative_to(Path(vault).resolve()):
                raise ValueError('Journal must be outside the vault')
            journal.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            changed = {op['path'] for op in operations}
            guards = {rel: before for rel, before in plan.get('reads', {}).items() if rel not in changed}
            save_checkpoint(journal, {'schema': 1, 'vault': str(Path(vault).resolve()),
                                     'operations': operations, 'completed': 0, 'guards': guards,
                                     'inventory': plan.get('inventory') if plan.get('moves') else None,
                                     'excludes': plan.get('excludes', [])})
            return recover_journal(vault, journal, interrupt_after)
        if plan.get('moves'):
            raise ValueError('Moves require an external durable journal')
        for operation in operations:
            perform_operation(vault, operation)
        return {'complete': True, 'applied': [o['path'] for o in operations], 'skipped': []}
    except InterruptedError:
        raise
    except (OSError, ValueError) as exc:
        return {'complete': False, 'applied': [], 'skipped': [{'issue': str(exc)}]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("baseline", "run", "recover"))
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--sync-log", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--timezone", default="America/Boise")
    parser.add_argument("--daily-folder", default="Sessions")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--apply", action="store_true", help="Apply checked metadata edits and save cursor")
    args = parser.parse_args(argv)
    try:
        vault = args.vault.resolve(strict=True)
        log = args.sync_log.resolve(strict=True)
        checkpoint = args.checkpoint.absolute()
        if not vault.is_dir():
            raise ValueError("Vault must be a directory")
        if checkpoint.resolve().is_relative_to(vault) or checkpoint.resolve() == log:
            raise ValueError("Checkpoint must be outside the vault and distinct from Sync log")
        zone = ZoneInfo(args.timezone)
        binding = {"daily_folder": args.daily_folder, "excludes": args.exclude, "schema": 1, "vault": str(vault), "sync_log": str(log), "timezone": args.timezone}
        with checkpoint_lock(checkpoint):
            journal = checkpoint.with_name(checkpoint.name + ".journal.json")
            if args.command == "recover":
                if not args.apply:
                    raise ValueError("Recovery requires explicit --apply; journal may contain private note text")
                result = recover_journal(vault, journal)
                print(json.dumps(result, indent=2))
                return 0 if result["complete"] else 2
            if journal.exists():
                raise ValueError("Pending journal: run recover --apply before new maintenance")
            if args.command == "baseline":
                if checkpoint.exists():
                    raise ValueError("Checkpoint already exists; do not silently discard pending history")
                changes = read_changes(log, None, args.timezone)
                save_checkpoint(checkpoint, {**binding, "cursor": changes["cursor"]})
                print(json.dumps({"baseline": True, "complete": True, "edits": []}))
                return 0
            saved = json.loads(checkpoint.read_text())
            if any(saved.get(key) != value for key, value in binding.items()):
                raise ValueError("Checkpoint belongs to another vault/log/timezone or schema")
            changes = read_changes(log, saved["cursor"], args.timezone)
            if not changes["complete"]:
                print(json.dumps(changes))
                return 2
            stamp = datetime.now(zone).strftime("%Y-%m-%dT%H:%M")
            plan = build_plan(vault, changes, stamp, args.daily_folder, args.exclude)
            report = {"complete": not plan.get("retry_required", False), "dry_run": not args.apply,
                      "edits": [{k: v for k, v in e.items() if k != "text"} for e in plan["edits"]],
                      "moves": plan.get("moves", []), "issues": plan["issues"]}
            if args.apply:
                result = apply_plan(vault, plan, journal=journal)
                report.update(result)
                if result["complete"]:
                    save_checkpoint(checkpoint, {**binding, "cursor": changes["cursor"]})
            print(json.dumps(report, indent=2))
            return 0 if report["complete"] else 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"complete": False, "error": type(exc).__name__ + ": " + str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
