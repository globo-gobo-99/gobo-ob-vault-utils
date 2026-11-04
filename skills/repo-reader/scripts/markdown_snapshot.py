#!/usr/bin/env python3
"""Make a disposable, non-authoritative Markdown view of committed Git source."""
import argparse
from datetime import datetime
import fnmatch
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA = 1
DENIED_DIRS = {'.git', '.ssh', '.aws', '.gnupg', '.venv', 'venv', 'node_modules',
               '__pycache__', 'vendor', 'dist', 'build', '.cache'}
SECRET_NAMES = ('.env', '.env.*', '.npmrc', '.pypirc', '.netrc', 'id_rsa*', 'id_ed25519*',
                '*.pem', '*.key', '*.p12', '*.pfx', 'credentials', 'credentials.*', 'secrets.*')
CI_DIRS = {'.github', '.gitlab', '.circleci', '.buildkite', '.ci', '.cicd',
           '.tekton', '.azure-pipelines', '.teamcity', '.wercker'}
CI_FILES = ('jenkinsfile*', '.gitlab-ci*.yml', '.gitlab-ci*.yaml', '.travis.yml',
            'azure-pipelines*.yml', 'azure-pipelines*.yaml', 'bitbucket-pipelines*.yml',
            'bitbucket-pipelines*.yaml', '.drone*.yml', '.drone*.yaml',
            '.woodpecker*.yml', '.woodpecker*.yaml', 'appveyor.yml', '.appveyor.yml',
            'wercker.yml', 'cloudbuild*.yaml', 'cloudbuild*.yml', 'buildspec*.yml',
            'buildspec*.yaml')
TOKEN = re.compile(rb'-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----|'
                   rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|'
                   rb'tskey-[a-z]+-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{24,})')
LANGUAGES = {'.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.tsx': 'tsx',
             '.jsx': 'jsx', '.sh': 'bash', '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml',
             '.toml': 'toml', '.md': 'markdown', '.html': 'html', '.css': 'css',
             '.rs': 'rust', '.go': 'go', '.sql': 'sql', '.c': 'c', '.h': 'c', '.cpp': 'cpp'}


class SnapshotError(Exception):
    pass


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True)
    if result.returncode:
        # Don't echo Git diagnostics: remote/config paths may contain credentials.
        raise SnapshotError('Git could not read the requested repository/revision.')
    return result.stdout


def fenced(text, language=''):
    longest = max((len(x) for x in re.findall(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return fence + language + '\n' + text + ('' if text.endswith('\n') else '\n') + fence + '\n'


def safe_label(value):
    value = html.escape(re.sub(r'[\r\n\t]', ' ', value), quote=False)
    return re.sub(r'([\\`*_\[\]#!|])', r'\\\1', value)


def page_name(path, ordinal):
    basename = re.sub(r'[^\w.-]+', '_', PurePosixPath(path).name)[:80] or 'source'
    return f'{ordinal:04d}-{basename}.md'


def is_ci_content(parts):
    lowered = tuple(p.lower() for p in parts)
    return (any(p in CI_DIRS for p in lowered[:-1])
            or (len(lowered) > 1 and lowered[0] in {'ci', 'cicd', 'ci-cd'})
            or any(fnmatch.fnmatchcase(lowered[-1], p) for p in CI_FILES))


def github_source(repo, explicit=None):
    if explicit:
        raw = explicit
    else:
        result = subprocess.run(['git', '-C', str(repo), 'remote', 'get-url', 'origin'], capture_output=True)
        if result.returncode:
            raise SnapshotError('Supply --source-url https://github.com/OWNER/REPO or configure a GitHub origin.')
        raw = result.stdout.decode().strip()
    ssh = re.fullmatch(r'git@github\.com:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?', raw)
    if ssh:
        owner, name = ssh.groups()
    else:
        url = urlsplit(raw)
        if url.scheme != 'https' or url.hostname != 'github.com' or url.query or url.fragment:
            raise SnapshotError('Source must be a GitHub repository URL; supply --source-url explicitly.')
        if explicit and (url.username or url.password):
            raise SnapshotError('Do not put credentials in --source-url.')
        parts = url.path.strip('/').removesuffix('.git').split('/')
        if len(parts) != 2 or not all(re.fullmatch(r'[A-Za-z0-9_.-]+', p) for p in parts):
            raise SnapshotError('Source must identify one GitHub owner/repository.')
        owner, name = parts
    # Remote URLs may contain credentials; emit only canonical public identifiers.
    return f'https://github.com/{owner}/{name}'


def frontmatter(level, now):
    return f'---\nsensitivity: {level}\ncreated: {now:%Y-%m-%d}\nmodified: "{now:%Y-%m-%dT%H:%M}"\n---\n'


def directory_tree(entries):
    tree = {}
    for entry in entries:
        node = tree
        parts = PurePosixPath(entry['path']).parts
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = entry['status']
    lines = []
    def walk(node, prefix=''):
        pairs = sorted(node.items())
        for i, (name, value) in enumerate(pairs):
            last = i == len(pairs)-1
            connector = '└── ' if last else '├── '
            name = name.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
            lines.append(prefix + connector + name + ('/' if isinstance(value, dict) else
                         ('' if value == 'included' else ' [omitted: ' + value + ']')))
            if isinstance(value, dict):walk(value, prefix + ('    ' if last else '│   '))
    walk(tree)
    return '\n'.join(lines)


def prepare(repo, output, *, ref='HEAD', source_url=None, sensitivity='private', timezone='UTC',
            include=(), exclude=(), max_bytes=262144, max_total_bytes=5242880, max_files=500):
    repo = Path(repo).resolve()
    # Refuse output symlinks as well as existing directories.
    raw_output = Path(output).absolute()
    if raw_output.exists() or raw_output.is_symlink():
        raise SnapshotError('Output already exists; choose a new disposable snapshot directory.')
    output = raw_output.resolve()
    if output == repo or repo in output.parents:
        raise SnapshotError('Output must be outside the source repository.')
    if min(max_bytes, max_total_bytes, max_files) < 1:
        raise SnapshotError('Size and file-count limits must be positive.')
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise SnapshotError('Unknown timezone.') from None
    if sensitivity not in {'public', 'private', 'confidential'}:
        raise SnapshotError('Unsupported sensitivity.')
    commit = git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()
    source_url = github_source(repo, source_url)
    raw = git(repo, 'ls-tree', '-r', '-l', '-z', '--full-tree', commit)
    records = raw.split(b'\0')
    if len(records) > 10001:
        raise SnapshotError('Repository has more than 10,000 entries; use a smaller source repository.')
    entries = []
    pages = {}
    total = 0
    now = datetime.now(tz)
    for record in records:
        if not record:continue
        header, rawpath = record.split(b'\t', 1)
        mode, kind, oid, size = header.split()
        try:
            path = rawpath.decode('utf-8')
        except UnicodeDecodeError:
            raise SnapshotError('A source path is not UTF-8; no snapshot was written.') from None
        parts = PurePosixPath(path).parts
        if not parts or any(p in {'.', '..'} for p in parts) or path.startswith('/'):
            raise SnapshotError('Unsafe source path; no snapshot was written.')
        entry = dict(path=path, git_object=oid.decode(), status='included')
        entries.append(entry)
        reason = None
        if mode == b'120000':reason = 'symlink'
        elif kind != b'blob' or mode not in {b'100644', b'100755'}:reason = 'submodule-or-special'
        elif is_ci_content(parts):reason = 'ci-cd'
        elif any(p in DENIED_DIRS for p in parts[:-1]):reason = 'dependency-or-private-directory'
        elif any(fnmatch.fnmatchcase(parts[-1].lower(), p) for p in SECRET_NAMES):reason = 'credential-filename'
        elif include and not any(fnmatch.fnmatchcase(path, p) for p in include):reason = 'outside-include'
        elif any(fnmatch.fnmatchcase(path, p) for p in exclude):reason = 'explicit-exclude'
        elif int(size) > max_bytes:reason = 'file-size-limit'
        elif len(pages) >= max_files:reason = 'file-count-limit'
        elif total + int(size) > max_total_bytes:reason = 'total-size-limit'
        if reason:
            entry['status'] = reason
            continue
        data = git(repo, 'cat-file', 'blob', oid.decode())
        if b'\0' in data:
            entry['status'] = 'binary'
            continue
        try:
            source = data.decode('utf-8')
        except UnicodeDecodeError:
            entry['status'] = 'non-utf8'
            continue
        if TOKEN.search(data):
            entry['status'] = 'likely-secret-content'
            continue
        page = page_name(path, len(pages) + 1)
        entry.update(page=page, source_sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        meta = frontmatter(sensitivity, now)
        pages[page] = (meta + '# ' + safe_label(path) + '\n// Disposable source view; the Git repository is authoritative.\n\n'
                       + '**NON-AUTHORITATIVE SNAPSHOT — do not edit here to change the project.**\n\n'
                       + '[Original source](' + source_url + '/blob/' + commit + '/' + quote(path, safe='/') + ')\n\n'
                       + 'Source commit: `' + commit + '`\n\n'
                       + '[Snapshot index](' + '../' * (len(PurePosixPath(page).parts)-1) + 'README.md)\n\n'
                       + fenced(source, LANGUAGES.get(PurePosixPath(path).suffix.lower(), 'text')))
        total += len(data)
    # All source pages are flat and numbered, independent of original path spelling.
    for page in pages:
        if any(str(parent) in pages for parent in PurePosixPath(page).parents):
            raise SnapshotError('Source names collide after Markdown mapping; narrow the selected files.')
    included = [e for e in entries if e['status'] == 'included']
    links = '\n'.join('- [' + safe_label(e['path']) + '](' + quote(e['page'], safe='/') + ')' for e in included)
    omitted = [e for e in entries if e['status'] != 'included']
    pages['README.md'] = (frontmatter(sensitivity, now) + '# ' + safe_label(repo.name) + ' — source snapshot\n'
        + '// A temporary reading copy pinned to a Git commit.\n\n'
        + '**NON-AUTHORITATIVE / DISPOSABLE.** Source changes belong in Git. Keep review findings outside this folder.\n\n'
        + '[Original GitHub repository](' + source_url + ') · [Pinned tree](' + source_url + '/tree/' + commit + ')\n\n'
        + 'Commit: `' + commit + '`\n\nScope: committed tree only; uncommitted and untracked work is not included.\n\n'
        + f'Included: {len(included)} files / {total} source bytes. Omitted: {len(omitted)} entries.\n\n'
        + '## Directory structure\n// Original paths, with explicit omissions.\n\n'
        + fenced(directory_tree(entries), 'text') + '\n'
        + '## Browse source\n// Follow a file into its fenced Markdown reading copy.\n\n'
        + (links or 'No source files selected.') + '\n\n'
        + '## End-of-session disposition\n// Distill findings into durable notes, then remove the disposable copy when wanted.\n\n'
        + 'No automatic expiry, deletion or reverse synchronization. If annotations were added here, preserve them before removing this folder. '
        + 'The source repository remains authoritative. The manifest records omissions and generated-file hashes; secret screening is conservative, not a completeness guarantee.\n')
    manifest = dict(schema=SCHEMA, authoritative=False, disposable=True, repository=repo.name, source_url=source_url,
                    layout='flat-numbered-pages',
                    commit=commit, captured_at=now.isoformat(), sensitivity=sensitivity,
                    scope='committed-tree-only', entries=entries,
                    policy=dict(include=list(include), exclude=list(exclude), ci_cd_excluded=True, max_bytes=max_bytes,
                                max_total_bytes=max_total_bytes, max_files=max_files),
                    generated_files={p:hashlib.sha256(s.encode()).hexdigest() for p,s in pages.items()})
    pages['snapshot.json'] = json.dumps(manifest, indent=2, ensure_ascii=False) + '\n'
    return output, pages, manifest


def write_snapshot(output, pages):
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive reservation avoids overwriting another session's snapshot.
    output.mkdir(exist_ok=False)
    marker = output / 'INCOMPLETE'
    marker.write_text('Snapshot generation in progress. Do not treat this folder as complete.\n')
    try:
        # Index last, so a failed generation cannot advertise a complete snapshot.
        for name in sorted(pages, key=lambda name: name == 'README.md'):
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8', newline='') as stream:
                stream.write(pages[name])
        marker.unlink()
    except Exception:
        raise SnapshotError('Snapshot write interrupted; reserved output retains an INCOMPLETE marker. Use a new output directory.') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--source-url', help='Original https://github.com/OWNER/REPO; otherwise derive safely from origin')
    parser.add_argument('--sensitivity', choices=['public','private','confidential'], default='private')
    parser.add_argument('--timezone', default='UTC')
    parser.add_argument('--include', action='append', default=[])
    parser.add_argument('--exclude', action='append', default=[])
    parser.add_argument('--max-bytes', type=int, default=262144)
    parser.add_argument('--max-total-bytes', type=int, default=5242880)
    parser.add_argument('--max-files', type=int, default=500)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        output, pages, manifest = prepare(args.repo, args.output, ref=args.ref, source_url=args.source_url,
            sensitivity=args.sensitivity, timezone=args.timezone, include=args.include,
            exclude=args.exclude, max_bytes=args.max_bytes,
            max_total_bytes=args.max_total_bytes, max_files=args.max_files)
        if args.apply:write_snapshot(output, pages)
        print(json.dumps(dict(mode='applied' if args.apply else 'dry-run', output=str(output),
            commit=manifest['commit'], included=sum(e['status']=='included' for e in manifest['entries']),
            omitted=[dict(path=e['path'],reason=e['status']) for e in manifest['entries'] if e['status']!='included'],
            authoritative=False),indent=2,ensure_ascii=False))
        return 0
    except (SnapshotError, OSError) as error:
        print(json.dumps(dict(error=str(error) if isinstance(error,SnapshotError) else
                             'Filesystem operation failed; inspect paths/permissions and any INCOMPLETE marker.')),
              file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
