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


def build_plan(vault, changes, stamp):
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


def apply_plan(vault, plan):
    applied, skipped = [], []
    for edit in plan["edits"]:
        temporary = None
        try:
            path = safe_file(vault, edit["path"])
            _, state = snapshot(path)
            if state != edit["before"]:
                raise ValueError("concurrent-change")
            fd, temporary = tempfile.mkstemp(prefix=".maintenance-", dir=path.parent)
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(path.stat().st_mode))
                stream.write(edit["text"].encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            # A second read after staging avoids replacing a change made while writing the temp file.
            checked = safe_file(vault, edit["path"])
            if checked != path or snapshot(checked)[1] != edit["before"]:
                raise ValueError("concurrent-change")
            os.replace(temporary, path)
            temporary = None
            fsync_directory(path.parent)
            applied.append(edit["path"])
        except (OSError, ValueError) as exc:
            skipped.append({"path": edit["path"], "issue": str(exc)})
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
    return {"complete": not skipped, "applied": applied, "skipped": skipped}


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("baseline", "run"))
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--sync-log", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--timezone", default="America/Boise")
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
        binding = {"schema": 1, "vault": str(vault), "sync_log": str(log), "timezone": args.timezone}
        with checkpoint_lock(checkpoint):
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
            plan = build_plan(vault, changes, stamp)
            report = {"complete": True, "dry_run": not args.apply,
                      "edits": [{k: v for k, v in e.items() if k != "text"} for e in plan["edits"]],
                      "issues": plan["issues"]}
            if args.apply:
                result = apply_plan(vault, plan)
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
