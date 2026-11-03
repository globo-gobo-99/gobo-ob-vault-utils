"""Conservative wiki/Markdown path rewriting; never rewrite code or choose ambiguous names."""
import posixpath
import re
from urllib.parse import quote, unquote, urlsplit

WIKI = re.compile(r'!?\[\[([^\]\n]+)\]\]')
MARKDOWN = re.compile(r'!?\[[^\]\n]*\]\((<[^>\n]+>|[^\s)\n]+)(?:\s+(?:"[^"\n]*"|\x27[^\x27\n]*\x27))?\)')
DEFINITION = re.compile(r'^ {0,3}\[[^\]\n]+\]:\s*(<[^>\n]+>|[^\s\n]+)', re.M)


def code_mask(text):
    """Keep offsets while hiding fenced and inline code from reference processing."""
    masked = list(text)
    fence = None
    offset = 0
    for line in text.splitlines(keepends=True):
        start = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence:
            masked[offset:offset + len(line)] = ' ' * len(line)
            if start and start.group(1)[0] == fence[0] and len(start.group(1)) >= len(fence):
                fence = None
        elif start:
            fence = start.group(1)
            masked[offset:offset + len(line)] = ' ' * len(line)
        offset += len(line)
    interim = ''.join(masked)
    for match in re.finditer(r'(`+)([^\n]*?)\1', interim):
        masked[match.start():match.end()] = ' ' * (match.end() - match.start())
    return ''.join(masked)


def normalize(path):
    normalized = posixpath.normpath(path)
    return None if normalized == '..' or normalized.startswith('../') else normalized.lstrip('/')


def rewrite_references(text, old_source, new_source, moves, inventory):
    """Return rewritten text and visible diagnostics; blocking diagnostics forbid moves."""
    masked = code_mask(text)
    edits, issues, covered = [], [], []
    moved_names = {posixpath.basename(p) for p in moves}
    moved_stems = {p.removesuffix('.md') for p in moved_names}

    def issue(kind, target, blocks=False):
        issues.append({'path': old_source, 'issue': kind, 'target': target, 'blocks_move': blocks})

    def resolve(target, wiki):
        decoded = unquote(target)
        if wiki and '/' not in decoded:
            candidates = {p for p in inventory if posixpath.basename(p) == decoded
                          or (p.endswith('.md') and posixpath.basename(p)[:-3] == decoded)}
        else:
            root = normalize(decoded.lstrip('/'))
            local = normalize(posixpath.join(posixpath.dirname(old_source), decoded))
            choices = {local} if not wiki or decoded.startswith(('./', '../')) else {root, local}
            if decoded.startswith('/'):
                choices = {root}
            candidates = {p for p in choices if p in inventory}
            if wiki:
                candidates |= {p + '.md' for p in choices if p and p + '.md' in inventory}
        if len(candidates) == 1:
            return next(iter(candidates))
        relevant = (old_source in moves or posixpath.basename(decoded) in moved_names
                    or posixpath.basename(decoded) in moved_stems)
        issue('ambiguous-reference' if candidates else 'missing-reference', target, relevant)
        return None

    for match in WIKI.finditer(masked):
        covered.append((match.start(), match.end()))
        raw = text[match.start(1):match.end(1)]
        target_part, sep, alias = raw.partition('|')
        target, hashmark, fragment = target_part.partition('#')
        if not target:
            continue
        resolved = resolve(target, True)
        if resolved is None:
            continue
        relative = target.startswith(('./', '../'))
        if resolved in moves or (old_source != new_source and relative):
            replacement = moves.get(resolved, resolved)
            if resolved.endswith('.md') and not target.endswith('.md'):
                replacement = replacement.removesuffix('.md')
            replacement += hashmark + fragment + sep + alias
            edits.append((match.start(1), match.end(1), replacement))

    for pattern in (MARKDOWN, DEFINITION):
        for match in pattern.finditer(masked):
            covered.append((match.start(), match.end()))
            raw = text[match.start(1):match.end(1)]
            angle = raw.startswith('<') and raw.endswith('>')
            target = raw[1:-1] if angle else raw
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or target.startswith('#'):
                continue
            pathpart, hashmark, fragment = target.partition('#')
            if not pathpart:
                continue
            if '?' in pathpart:
                issue('unsupported-local-query', target, old_source in moves)
                continue
            resolved = resolve(pathpart, False)
            if resolved is None:
                continue
            if resolved in moves or old_source != new_source:
                destination = moves.get(resolved, resolved)
                replacement = posixpath.relpath(destination, posixpath.dirname(new_source) or '.')
                replacement = quote(replacement, safe='/~.-_') + hashmark + fragment
                if angle:
                    replacement = '<' + replacement + '>'
                edits.append((match.start(1), match.end(1), replacement))

    # Do not silently leave an unsupported link spelling to a moved file.
    leftover = list(masked)
    for start, end in covered:
        leftover[start:end] = ' ' * (end - start)
    remainder = ''.join(leftover)
    for line in remainder.splitlines():
        if ('[[' in line or '](' in line or re.match(r'^\s*\[[^]]+\]:', line)) and any(
                name in unquote(line) for name in moved_names | moved_stems):
            issue('unsupported-affected-reference', line, True)
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text, issues
