import importlib.util
from pathlib import Path
import tempfile
import unittest

class MaintenanceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.log=self.root/'sync.log';self.log.write_text('old history\n')
  spec=importlib.util.spec_from_file_location('maintenance',Path(__file__).parents[1]/'vault_maintenance.py');self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
 def test_first_run_baselines_without_retrospective_sweep(self):
  result=self.m.read_changes(self.log,None)
  self.assertEqual(result['events'],[]);self.assertTrue(result['baseline'])
 def test_native_completed_events_have_actual_arrival_date(self):
  cursor=self.m.read_changes(self.log,None)['cursor']
  with self.log.open('a') as f:f.write('[2026-11-03T00:10:00.000Z] Downloaded loose note.md\n')
  result=self.m.read_changes(self.log,cursor)
  self.assertEqual(result['events'],[{'path':'loose note.md','date':'2026-11-02','arrival':True}]);self.assertTrue(result['complete'])
 def test_rotation_or_rewritten_prefix_reports_incomplete_coverage(self):
  cursor=self.m.read_changes(self.log,None)['cursor'];self.log.write_text('different history, longer\n')
  result=self.m.read_changes(self.log,cursor)
  self.assertFalse(result['complete']);self.assertEqual(result['events'],[])
 def test_created_is_never_invented_and_prose_is_preserved(self):
  text='# Human prose\n\nKeep this  \n'
  result=self.m.lint_text(text,'2026-11-02T17:50')
  self.assertIn('missing-created',result['issues']);self.assertNotIn('created:',result['text']);self.assertTrue(result['text'].endswith(text));self.assertEqual(self.m.lint_text(result['text'],'2026-11-02T17:51')['text'],result['text'])
 def test_baseline_partial_history_is_skipped_when_completed(self):
  self.log.write_text('[2026-11-03T00:00:00Z] Downloaded old')
  cursor=self.m.read_changes(self.log,None)['cursor']
  with self.log.open('a') as f:f.write(' note.md\n[2026-11-03T00:10:00Z] Downloaded new.md\n')
  result=self.m.read_changes(self.log,cursor)
  self.assertTrue(result['complete']);self.assertEqual([e['path'] for e in result['events']],['new.md'])
 def test_new_partial_record_remains_pending(self):
  cursor=self.m.read_changes(self.log,None)['cursor']
  with self.log.open('a') as f:f.write('[2026-11-03T00:10:00Z] Downloaded new')
  result=self.m.read_changes(self.log,cursor)
  self.assertEqual(result['events'],[])
  with self.log.open('a') as f:f.write('.md\n')
  result=self.m.read_changes(self.log,result['cursor'])
  self.assertEqual([e['path'] for e in result['events']],['new.md'])
 def test_upload_is_not_a_download_arrival(self):
  cursor=self.m.read_changes(self.log,None)['cursor']
  with self.log.open('a') as f:f.write('[2026-11-03T00:10:00Z] Upload complete existing.md\n')
  result=self.m.read_changes(self.log,cursor)
  self.assertFalse(result['events'][0]['arrival'])
 def test_missing_final_newline_is_fixed_without_trimming_markdown_break(self):
  result=self.m.lint_text('---\ncreated: 2026-11-02\nmodified: 2026-11-02T17:00\n---\nHuman text  ', '2026-11-02T18:40')
  self.assertTrue(result['text'].endswith('Human text  \n'))
  self.assertIn('created: 2026-11-02',result['text'])
if __name__=='__main__':unittest.main()
