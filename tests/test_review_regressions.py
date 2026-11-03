import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'vault_maintenance.py'


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        spec = importlib.util.spec_from_file_location('maintenance', SCRIPT)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def plan_arrival(self, filename, reference):
        (self.vault / filename).write_text('# Keep human text\n')
        (self.vault / 'Wiki').mkdir()
        (self.vault / 'Wiki/ref.md').write_text(reference)
        return self.m.build_plan(self.vault, {'complete': True, 'events': [
            {'path': filename, 'date': '2026-11-02', 'arrival': True}]}, '2026-11-02T18:50')

    def test_unsupported_affected_query_is_held_without_cursor_advance(self):
        plan = self.plan_arrival('note.md', '[open](note.md?view=1)\n')
        self.assertTrue(plan.get('retry_required'))
        self.assertEqual(plan['moves'], [])

    def test_balanced_parenthesized_path_is_rewritten_or_held(self):
        plan = self.plan_arrival('note(1).md', '[open](../note(1).md)\n')
        if plan.get('moves'):
            edit = next((e for e in plan['edits'] if e['path'] == 'Wiki/ref.md'), None)
            self.assertIsNotNone(edit, 'A moved target requires an updated incoming reference')
            self.assertIn('Sessions/2026-11-02/note%281%29.md', edit['text'])
        else:
            self.assertTrue(plan.get('retry_required'))

    def test_affected_html_reference_holds_move(self):
        plan = self.plan_arrival('note.md', '<a href="../note.md">open</a>\n')
        self.assertTrue(plan.get('retry_required'))
        self.assertEqual(plan['moves'], [])

    def test_quoted_date_keys_are_preserved_without_duplicate_fields(self):
        for quote in ('"', "'"):
            with self.subTest(quote=quote):
                text = f'---\n{quote}created{quote}: 2026-11-02\n{quote}modified{quote}: 2026-11-02T18:40\n---\n# Prose\n'
                result = self.m.lint_text(text, '2026-11-02T18:50')
                self.assertEqual(result['text'], text)
                self.assertEqual(result['issues'], [])

    def test_block_scalar_date_is_held_without_invalidating_yaml(self):
        plan = self.plan_arrival('note.md', '---\ncreated: 2026-11-02\nmodified: |\n  historical date\n---\n[[note]]\n')
        self.assertTrue(plan.get('retry_required'))
        self.assertEqual(plan['moves'], [])
        self.assertFalse(self.m.apply_plan(self.vault, plan, journal=self.root/'journal.json')['complete'])
        self.assertIn('modified: |\n  historical date', (self.vault/'Wiki/ref.md').read_text())

    def test_indented_code_is_preserved_while_target_moves(self):
        plan = self.plan_arrival('note.md', 'Code examples:\n\n    [[note]]\n    [example](../note.md)\n')
        self.assertEqual(len(plan['moves']), 1)
        self.assertTrue(self.m.apply_plan(self.vault, plan, journal=self.root/'journal.json')['complete'])
        self.assertEqual((self.vault/'Wiki/ref.md').read_text(), 'Code examples:\n\n    [[note]]\n    [example](../note.md)\n')

    def test_nested_list_reference_is_updated_or_held(self):
        plan = self.plan_arrival('note.md', '- Parent item\n\n    - Child [[note]]\n')
        if plan.get('moves'):
            edit=next((e for e in plan['edits'] if e['path']=='Wiki/ref.md'), None)
            self.assertIsNotNone(edit)
            self.assertIn('[[Sessions/2026-11-02/note]]',edit['text'])
        else:
            self.assertTrue(plan.get('retry_required'))

    def test_multiline_html_holds_affected_move(self):
        plan = self.plan_arrival('note.md', '<a\n  href="../note.md"\n>open</a>\n')
        self.assertTrue(plan.get('retry_required'))
        self.assertEqual(plan['moves'], [])

    def test_escaped_parentheses_in_path_are_rewritten_or_held(self):
        plan = self.plan_arrival('note(1).md', '[open](../note\\(1\\).md)\n')
        if plan.get('moves'):
            edit=next((e for e in plan['edits'] if e['path']=='Wiki/ref.md'), None)
            self.assertIsNotNone(edit)
            self.assertIn('Sessions/2026-11-02/note%281%29.md',edit['text'])
        else:
            self.assertTrue(plan.get('retry_required'))


if __name__ == '__main__':
    unittest.main()
