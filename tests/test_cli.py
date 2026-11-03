import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'vault_maintenance.py'


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.vault = self.base / 'vault'
        self.vault.mkdir()
        self.log = self.base / 'sync.log'
        self.log.write_text('old history\n')
        self.checkpoint = self.base / 'state' / 'cursor.json'
        spec = importlib.util.spec_from_file_location('maintenance', SCRIPT)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def cli(self, command, *extra):
        return subprocess.run([sys.executable, str(SCRIPT), command, '--vault', str(self.vault),
            '--sync-log', str(self.log), '--checkpoint', str(self.checkpoint), *extra],
            capture_output=True, text=True)

    def arrival(self, name='Wiki/new.md'):
        p = self.vault / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('---\ncreated: 2026-11-02\n---\n# Human text\n')
        with self.log.open('a') as f:
            f.write(f'[2026-11-03T00:10:00.000Z] Downloaded {name}\n')
        return p

    def test_explicit_baseline_dry_run_then_apply_is_idempotent(self):
        result = self.cli('baseline')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.checkpoint.is_file())
        self.assertEqual(self.checkpoint.stat().st_mode & 0o777, 0o600)
        old_cursor = self.checkpoint.read_bytes()
        note = self.arrival()
        old_note = note.read_bytes()
        result = self.cli('run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(note.read_bytes(), old_note)
        self.assertEqual(self.checkpoint.read_bytes(), old_cursor)
        self.assertEqual(len(json.loads(result.stdout)['edits']), 1)
        result = self.cli('run', '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('modified:', note.read_text())
        self.assertIn('# Human text', note.read_text())
        current = note.read_bytes()
        result = self.cli('run', '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['edits'], [])
        self.assertEqual(note.read_bytes(), current)

    def test_missing_baseline_and_in_vault_checkpoint_are_rejected(self):
        self.assertNotEqual(self.cli('run').returncode, 0)
        self.checkpoint = self.vault / 'cursor.json'
        self.assertNotEqual(self.cli('baseline').returncode, 0)
        self.assertFalse(self.checkpoint.exists())

    def test_rotation_fails_without_advancing_checkpoint(self):
        self.assertEqual(self.cli('baseline').returncode, 0)
        saved = self.checkpoint.read_bytes()
        self.log.write_text('a different log\n')
        result = self.cli('run', '--apply')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(saved, self.checkpoint.read_bytes())

    def test_concurrent_note_change_is_skipped(self):
        cursor = self.m.read_changes(self.log, None)['cursor']
        note = self.arrival()
        changes = self.m.read_changes(self.log, cursor)
        plan = self.m.build_plan(self.vault, changes, '2026-11-02T18:30')
        note.write_text('Human changed this after planning\n')
        result = self.m.apply_plan(self.vault, plan)
        self.assertFalse(result['complete'])
        self.assertEqual(note.read_text(), 'Human changed this after planning\n')

    def test_symlink_and_unclosed_yaml_are_never_rewritten(self):
        cursor = self.m.read_changes(self.log, None)['cursor']
        outside = self.base / 'private.md'
        outside.write_text('Private unrelated content\n')
        (self.vault / 'alias.md').symlink_to(outside)
        malformed = self.arrival('bad.md')
        malformed.write_text('---\ncreated: 2026-11-02\n# Missing closing delimiter\n')
        with self.log.open('a') as f:
            f.write('[2026-11-03T00:11:00.000Z] Downloaded alias.md\n')
        changes = self.m.read_changes(self.log, cursor)
        plan = self.m.build_plan(self.vault, changes, '2026-11-02T18:30')
        self.assertEqual(plan['edits'], [])
        self.assertTrue(plan['issues'])
        self.assertIn('Private unrelated content', outside.read_text())

    def test_new_local_root_upload_moves_but_existing_root_upload_does_not(self):
        existing = self.vault / 'old.md'
        existing.write_text('# Existing before baseline\n')
        self.assertEqual(self.cli('baseline').returncode, 0)
        new = self.vault / 'new.md'
        new.write_text('# New local arrival\n')
        with self.log.open('a') as stream:
            for name in ('old.md', 'new.md'):
                stream.write(f'[2026-11-03T00:10:00Z] Upload complete {name}\n')
        result = self.cli('run', '--apply')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(existing.exists())
        self.assertFalse(new.exists())
        self.assertTrue((self.vault / 'Sessions/2026-11-02/new.md').exists())


if __name__ == '__main__':
    unittest.main()
