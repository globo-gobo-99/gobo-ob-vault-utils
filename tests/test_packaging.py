from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).parents[1]


class PackagingTests(unittest.TestCase):
    def test_skill_folder_runs_when_copied_without_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = ROOT / 'skills' / 'vault-maintenance'
            self.assertTrue(skill.is_dir())
            destination = Path(directory) / 'standalone-skill'
            shutil.copytree(skill, destination)
            result = subprocess.run([sys.executable, str(destination / 'scripts' / 'maintain_vault.py'),
                '--help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--checkpoint', result.stdout)
            self.assertIn('recover', result.stdout)

    def test_standalone_baseline_dry_run_apply_and_journal_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            copied = base / 'skill'
            shutil.copytree(ROOT / 'skills/vault-maintenance', copied)
            engine = copied / 'scripts/maintain_vault.py'
            vault = base / 'vault'
            vault.mkdir()
            log = base / 'sync.log'
            log.write_text('old history\n')
            checkpoint = base / 'state/cursor.json'
            def run(command, *extra):
                result = subprocess.run([sys.executable, str(engine), command,
                    '--vault', str(vault), '--sync-log', str(log), '--checkpoint', str(checkpoint), *extra],
                    cwd=base, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result
            run('baseline')
            for name in ('one.md', 'two.md'):
                (vault/name).write_text('# Fixture '+name+'\n')
            log.write_text(log.read_text()+'[2026-11-03T00:10:00Z] Downloaded one.md\n')
            run('run')
            self.assertTrue((vault/'one.md').exists())
            run('run', '--apply')
            self.assertTrue((vault/'Sessions/2026-11-02/one.md').is_file())
            log.write_text(log.read_text()+'[2026-11-03T00:11:00Z] Downloaded two.md\n')
            code = """import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from maintain_vault import read_changes,build_plan,apply_plan
vault,log,cp=map(Path,sys.argv[2:])
saved=json.loads(cp.read_text())
changes=read_changes(log,saved['cursor'])
plan=build_plan(vault,changes,'2026-11-02T18:50')
try:
 apply_plan(vault,plan,journal=cp.with_name(cp.name+'.journal.json'),interrupt_after=1)
except InterruptedError:
 print('INTERRUPTION_PROVED')
"""
            result = subprocess.run([sys.executable, '-c', code, str(engine.parent), str(vault), str(log), str(checkpoint)],
                cwd=base, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('INTERRUPTION_PROVED', result.stdout)
            run('recover', '--apply')
            run('run', '--apply')
            self.assertTrue((vault/'Sessions/2026-11-02/two.md').is_file())


if __name__ == '__main__':
    unittest.main()
