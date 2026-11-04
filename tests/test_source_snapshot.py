from pathlib import Path
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT/'skills/source-snapshot/scripts/markdown_snapshot.py'
spec = importlib.util.spec_from_file_location('source_snapshot', SCRIPT)
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base/'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('remote', 'add', 'origin', 'https://github.com/example/source.git')
        self.put('src/app.py', 'print("committed")\n')
        self.put('docs/a space.md', '# Title\n\n```python\nprint(1)\n```\n````\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.out = self.base/'vault'/'reading'

    def git(self, *args):
        r = subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.decode().strip()

    def put(self, name, content):
        p = self.repo/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def prepare(self, **kwargs):
        return snapshot.prepare(self.repo, self.out, **kwargs)

    def test_pins_committed_content_and_ignores_worktree(self):
        self.put('src/app.py', 'print("dirty")\n')
        self.put('untracked.py', 'print("untracked")\n')
        out,pages,m = self.prepare()
        self.assertEqual(m['commit'], self.git('rev-parse', 'HEAD'))
        page = next(e['page'] for e in m['entries'] if e['path']=='src/app.py')
        self.assertIn('committed', pages[page])
        self.assertNotIn('dirty', pages[page])
        self.assertNotIn('untracked.py', [e['path'] for e in m['entries']])
        self.assertFalse(out.exists())

    def test_structure_links_metadata_and_fences(self):
        out,pages,m = self.prepare(timezone='America/Boise')
        self.assertIn('src/', pages['README.md'])
        page = next(e['page'] for e in m['entries'] if e['path']=='docs/a space.md')
        self.assertIn(page, pages['README.md'])
        self.assertIn('`````markdown', pages[page])
        self.assertIn('/docs/a%20space.md', pages[page])
        self.assertIn('https://github.com/example/source', pages['README.md'])
        self.assertTrue(all('/' not in name for name in pages))
        for name,text in pages.items():
            if name.endswith('.md'):
                self.assertTrue(text.startswith('---\nsensitivity: private\ncreated:'))
                self.assertIn('NON-AUTHORITATIVE', text)
        self.assertFalse(m['authoritative'])
        self.assertTrue(m['disposable'])
        snapshot.write_snapshot(out,pages)
        self.assertFalse((out/'INCOMPLETE').exists())
        self.assertEqual(json.loads((out/'snapshot.json').read_text())['commit'],m['commit'])

    def test_omits_sensitive_binary_symlink_and_submodule(self):
        self.put('.env', 'SENSITIVE_VALUE=do-not-copy\n')
        self.put('private.pem', 'not a real key')
        self.put('token.txt', 'ghp_' + 'A'*40)
        (self.repo/'asset.bin').write_bytes(b'\0binary')
        (self.repo/'link.py').symlink_to('src/app.py')
        self.git('add','-f','.')
        self.git('update-index','--add','--cacheinfo','160000,'+self.git('rev-parse','HEAD')+',module')
        self.git('commit','-qm','omissions')
        _,pages,m=self.prepare()
        reasons={e['path']:e['status'] for e in m['entries']}
        self.assertEqual(reasons['.env'],'credential-filename')
        self.assertEqual(reasons['private.pem'],'credential-filename')
        self.assertEqual(reasons['token.txt'],'likely-secret-content')
        self.assertEqual(reasons['asset.bin'],'binary')
        self.assertEqual(reasons['link.py'],'symlink')
        self.assertEqual(reasons['module'],'submodule-or-special')
        self.assertNotIn('do-not-copy',''.join(pages.values()))

    def test_size_count_and_include_limits_are_explicit(self):
        self.put('big.txt','x'*1000)
        self.git('add','.');self.git('commit','-qm','large')
        _,_,m=self.prepare(max_bytes=100,max_files=1)
        reasons={e['path']:e['status'] for e in m['entries']}
        self.assertEqual(reasons['big.txt'],'file-size-limit')
        self.assertEqual(sum(v=='included' for v in reasons.values()),1)
        _,_,m=self.prepare(include=['src/*'])
        self.assertEqual([e['path'] for e in m['entries'] if e['status']=='included'],['src/app.py'])
        _,_,m=self.prepare(max_total_bytes=1)
        self.assertTrue(all(e['status']=='total-size-limit' for e in m['entries']))

    def test_existing_or_source_output_is_not_overwritten(self):
        self.out.mkdir(parents=True)
        sentinel=self.out/'human.md';sentinel.write_text('keep me')
        with self.assertRaises(snapshot.SnapshotError):self.prepare()
        self.assertEqual(sentinel.read_text(),'keep me')
        with self.assertRaises(snapshot.SnapshotError):snapshot.prepare(self.repo,self.repo/'snapshot')

    def test_unsafe_ref_and_invalid_settings_do_not_write(self):
        for ref in ['missing-ref','--help']:
            with self.assertRaises(snapshot.SnapshotError):self.prepare(ref=ref)
        for options in [dict(max_bytes=0),dict(timezone='No/SuchZone')]:
            with self.assertRaises(snapshot.SnapshotError):self.prepare(**options)
        self.assertFalse(self.out.exists())

    def test_flat_names_avoid_source_suffix_collisions(self):
        self.put('a','text')
        self.put('a.md/child.py','text')
        self.git('add','.');self.git('commit','-qm','collision')
        _,pages,m=self.prepare()
        self.assertEqual(len(m['generated_files']),4+1)
        self.assertTrue(all('/' not in name for name in pages))

    def test_source_is_never_executed(self):
        marker=self.base/'executed'
        self.put('trap.py',f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
        self.git('add','.');self.git('commit','-qm','trap')
        self.prepare()
        self.assertFalse(marker.exists())

    def test_source_filenames_cannot_embed_html_in_navigation(self):
        self.put('<img src=x>.py', 'pass\n')
        self.git('add','.');self.git('commit','-qm','untrusted filename')
        _,pages,m=self.prepare()
        page=next(e['page'] for e in m['entries'] if e['path']=='<img src=x>.py')
        self.assertIn('&lt;img src=x&gt;',pages[page])
        self.assertNotIn('[<img src=x>',pages['README.md'])

    def test_origin_credentials_are_not_exported(self):
        credential = 'credential-for-fixture-only'
        self.git('remote','set-url','origin','https://user:'+credential+'@github.com/example/source.git')
        _,pages,m=self.prepare()
        self.assertEqual(m['source_url'],'https://github.com/example/source')
        self.assertNotIn(credential,''.join(pages.values()))

    def test_explicit_source_url_and_missing_origin(self):
        self.git('remote','remove','origin')
        with self.assertRaises(snapshot.SnapshotError):self.prepare()
        _,pages,m=self.prepare(source_url='https://github.com/example/another')
        self.assertEqual(m['source_url'],'https://github.com/example/another')
        with self.assertRaises(snapshot.SnapshotError):
            self.prepare(source_url='https://user:private@github.com/example/another')

    def test_standalone_skill_cli_dry_run_then_apply(self):
        copied=self.base/'copied-skill'
        shutil.copytree(SCRIPT.parents[1],copied)
        cmd=[sys.executable,str(copied/'scripts/markdown_snapshot.py'),
             '--repo',str(self.repo),'--output',str(self.out)]
        dry=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(dry.returncode,0,dry.stderr)
        self.assertEqual(json.loads(dry.stdout)['mode'],'dry-run')
        self.assertFalse(self.out.parent.exists())
        applied=subprocess.run(cmd+['--apply'],capture_output=True,text=True)
        self.assertEqual(applied.returncode,0,applied.stderr)
        self.assertTrue((self.out/'README.md').exists())
        again=subprocess.run(cmd+['--apply'],capture_output=True,text=True)
        self.assertEqual(again.returncode,2)

    def test_write_race_refuses_existing_directory(self):
        out,pages,_=self.prepare()
        out.mkdir(parents=True)
        sentinel=out/'other.md';sentinel.write_text('human')
        with self.assertRaises(FileExistsError):snapshot.write_snapshot(out,pages)
        self.assertEqual(sentinel.read_text(),'human')


if __name__ == '__main__':
    unittest.main()
