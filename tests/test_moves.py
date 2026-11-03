import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'vault_maintenance.py'


class MoveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.vault = self.base / 'vault'
        self.vault.mkdir()
        self.journal = self.base / 'journal.json'
        spec = importlib.util.spec_from_file_location('maintenance', SCRIPT)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.events = []

    def put(self, name, text='# Fixture\n'):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def arrival(self, name, arrival=True):
        self.events.append({'path': name, 'date': '2026-11-02', 'arrival': arrival})

    def plan(self):
        return self.m.build_plan(self.vault, {'complete': True, 'events': self.events},
            '2026-11-02T18:40')

    def apply(self, plan):
        return self.m.apply_plan(self.vault, plan, journal=self.journal)

    def test_root_move_rewrites_wiki_embeds_markdown_and_own_relative_links(self):
        self.put('loose note.md', '# Prose\n\n[asset](assets/a.png)\n`[[loose note]]`\n')
        self.put('assets/a.png', 'fixture asset')
        ref = self.put('Wiki/reference.md', '[[loose note#Heading|label]]\n![[loose note.md]]\n[link](../loose%20note.md#part "title")\n')
        self.arrival('loose note.md')
        plan = self.plan()
        self.assertEqual(len(plan.get('moves', [])), 1)
        self.assertTrue(self.apply(plan)['complete'])
        moved = self.vault / 'Sessions/2026-11-02/loose note.md'
        self.assertFalse((self.vault / 'loose note.md').exists())
        self.assertIn('[asset](../../assets/a.png)', moved.read_text())
        self.assertIn('`[[loose note]]`', moved.read_text())
        self.assertIn('[[Sessions/2026-11-02/loose note#Heading|label]]', ref.read_text())
        self.assertIn('![[Sessions/2026-11-02/loose note.md]]', ref.read_text())
        self.assertIn('../Sessions/2026-11-02/loose%20note.md#part "title"', ref.read_text())
        self.assertIn('[[Sessions/2026-11-02/loose note]]',
            (self.vault / 'Sessions/2026-11-02.md').read_text())
        self.assertTrue((self.vault / 'Sessions/2026-11-02/README.md').is_file())
        self.assertFalse(self.journal.exists())
        # Replaying the same log batch changes nothing after source disappears.
        self.assertEqual(self.plan().get('moves', []), [])

    def test_upload_root_configs_daily_notes_and_explicit_exclusions_are_not_moved(self):
        for name in ('README.md', 'AGENTS.md', '2026-11-02.md', 'settings.json', 'existing.md'):
            self.put(name)
            self.arrival(name, arrival=name != 'existing.md')
        self.assertEqual(self.plan().get('moves', []), [])

    def test_destination_collision_never_overwrites(self):
        original = self.put('note.md', '# New\n')
        target = self.put('Sessions/2026-11-02/note.md', '# Existing\n')
        self.arrival('note.md')
        plan = self.plan()
        self.assertEqual(plan.get('moves', []), [])
        self.assertTrue(any('collision' in i['issue'] for i in plan['issues']))
        self.assertEqual(original.read_text(), '# New\n')
        self.assertEqual(target.read_text(), '# Existing\n')

    def test_ambiguous_wiki_link_blocks_move(self):
        self.put('note.md')
        self.put('Other/note.md')
        self.put('Wiki/ref.md', '[[note]]\n')
        self.arrival('note.md')
        plan = self.plan()
        self.assertEqual(plan.get('moves', []), [])
        self.assertTrue(any('ambiguous' in i['issue'] for i in plan['issues']))

    def test_changed_backlink_aborts_before_any_move(self):
        root = self.put('note.md')
        ref = self.put('Wiki/ref.md', '[[note]]\n')
        self.arrival('note.md')
        plan = self.plan()
        ref.write_text('Human editing now\n')
        self.assertFalse(self.apply(plan)['complete'])
        self.assertTrue(root.exists())
        self.assertEqual(ref.read_text(), 'Human editing now\n')

    def test_recover_after_one_operation_uses_durable_journal(self):
        self.put('note.md')
        self.put('Wiki/ref.md', '[[note]]\n')
        self.arrival('note.md')
        plan = self.plan()
        # Public fault injection hook used only by fixtures; actual process exit leaves same journal.
        with self.assertRaises(InterruptedError):
            self.m.apply_plan(self.vault, plan, journal=self.journal, interrupt_after=1)
        self.assertTrue(self.journal.exists())
        result = self.m.recover_journal(self.vault, self.journal)
        self.assertTrue(result['complete'])
        self.assertFalse(self.journal.exists())
        self.assertFalse((self.vault / 'note.md').exists())
        self.assertTrue((self.vault / 'Sessions/2026-11-02/note.md').exists())

    def test_crash_after_move_before_journal_progress_is_recoverable(self):
        import json
        self.put('note.md')
        self.put('Wiki/ref.md', '[[note]]\n')
        self.arrival('note.md')
        plan = self.plan()
        count = len(self.m.transaction_operations(plan))
        with self.assertRaises(InterruptedError):
            self.m.apply_plan(self.vault, plan, journal=self.journal, interrupt_after=count)
        state = json.loads(self.journal.read_text())
        state['completed'] -= 1
        self.journal.write_text(json.dumps(state))
        self.assertTrue(self.m.recover_journal(self.vault, self.journal)['complete'])

    def test_new_reference_in_previously_unmodified_note_holds_recovery(self):
        self.put('note.md')
        other = self.put('Wiki/other.md', '# Initially no link\n')
        self.arrival('note.md')
        plan = self.plan()
        with self.assertRaises(InterruptedError):
            self.m.apply_plan(self.vault, plan, journal=self.journal, interrupt_after=1)
        other.write_text('Human added [[note]]\n')
        self.assertFalse(self.m.recover_journal(self.vault, self.journal)['complete'])
        self.assertTrue((self.vault / 'note.md').exists())
        self.assertIn('Human added [[note]]', other.read_text())

    def test_collision_is_retryable_and_no_edits_are_applied(self):
        original = self.put('note.md', '# Keep this\n')
        self.put('Sessions/2026-11-02/note.md', '# Existing\n')
        self.arrival('note.md')
        plan = self.plan()
        self.assertTrue(plan.get('retry_required'))
        self.assertFalse(self.apply(plan)['complete'])
        self.assertEqual(original.read_text(), '# Keep this\n')

    def test_explicit_exclusion_and_unsafe_daily_folder(self):
        self.put('private.md', 'Do not read or touch\n')
        self.arrival('private.md')
        changes = {'complete': True, 'events': self.events}
        plan = self.m.build_plan(self.vault, changes, '2026-11-02T18:40', excludes=['private.md'])
        self.assertEqual(plan['edits'], [])
        self.assertEqual(plan.get('moves', []), [])
        with self.assertRaises(ValueError):
            self.m.build_plan(self.vault, changes, '2026-11-02T18:40', daily_folder='../outside')


if __name__ == '__main__':
    unittest.main()
