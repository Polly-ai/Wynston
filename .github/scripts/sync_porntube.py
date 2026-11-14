#!/usr/bin/env python3
"""Mirror only approved Porntube module assets; never execute upstream JS."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
import urllib.request

SOURCE_REPO = 'Yu9191/Rewrite'
MODULE = 'porntube/modules/porntube.sgmodule'
DEST_MODULE = 'Surge/Module/porntube.sgmodule'
DEST_JS = 'Surge/JavaScript/Porntube/'
SOURCE_PREFIX = ('https://raw.githubusercontent.com/' + SOURCE_REPO
                 + '/refs/heads/main/porntube/dist/')
DEST_PREFIX = ('https://raw.githubusercontent.com/Polly-ai/Wynston/'
               'main/' + DEST_JS)
NAME = 'porntube 助手增强'
CATEGORY = 'Polly-ai'
ACTIONS = {
    'porntube-request.js': ('porntube 请求', 'http-request'),
    'porntube.js': ('porntube API', 'http-response'),
    'porntube-page-request.js': ('porntube 页面请求', 'http-request'),
    'porntube-frontend.js': ('porntube 前端', 'http-response'),
}
METADATA = {'name', 'desc', 'icon', 'author', 'homepage', 'category',
            'arguments', 'arguments-desc'}
FIELDS = {'type', 'pattern', 'requires-body', 'max-size', 'timeout',
          'script-path', 'argument'}
LIMIT = 4 * 1024 * 1024


class SourceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise SourceError(message)


def transform_module(data):
    require(0 < len(data) <= LIMIT, 'Invalid module size')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise SourceError('Module is not UTF-8') from exc
    require(not any(ord(c) < 32 and c not in '\r\n\t' for c in text),
            'Control character in module')
    section = None
    sections, metadata, seen = set(), set(), set()
    hostnames = 0
    result = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip('\r\n')
        ending = line[len(body):]
        stripped = body.strip()
        if stripped.startswith('#!'):
            require(section is None, 'Metadata must precede sections')
            match = re.fullmatch(r'#!([a-z-]+)=(.*)', body)
            require(match is not None, 'Malformed metadata')
            key, value = match.groups()
            require(key in METADATA and key not in metadata,
                    'Unknown or duplicate metadata: ' + key)
            require(bool(value.strip()), 'Empty metadata: ' + key)
            metadata.add(key)
            if key in {'name', 'category'}:
                value = NAME if key == 'name' else CATEGORY
                line = '#!' + key + '=' + value + ending
        elif not stripped or stripped.startswith(('#', ';')):
            pass
        elif stripped.startswith('['):
            require(stripped in {'[Script]', '[MITM]'}, 'Unknown section')
            require(stripped not in sections, 'Duplicate section')
            sections.add(stripped)
            section = stripped
        elif section == '[Script]':
            label, sep, attrs = body.partition('=')
            require(bool(sep), 'Malformed script rule')
            fields = {}
            for item in re.split(r',\s*(?=[A-Za-z][\w-]*\s*=)', attrs):
                key, sep, value = item.strip().partition('=')
                key, value = key.strip(), value.strip()
                require(bool(sep) and key in FIELDS and key not in fields,
                        'Unknown, malformed or duplicate script attribute')
                require(bool(value), 'Empty script attribute')
                fields[key] = value
            require({'type', 'pattern', 'timeout', 'script-path'} <= fields.keys(),
                    'Missing script attributes')
            url = fields['script-path']
            require(url.startswith(SOURCE_PREFIX), 'Unknown dependency origin')
            filename = url[len(SOURCE_PREFIX):]
            require(filename in ACTIONS and filename not in seen,
                    'Unknown or duplicate dependency')
            require((label.strip(), fields['type']) == ACTIONS[filename],
                    'Unknown script action or label')
            require(fields['pattern'].startswith('^https?'), 'Unknown rule pattern')
            require(re.fullmatch(r'[1-9][0-9]*', fields['timeout']) is not None,
                    'Invalid timeout')
            if 'requires-body' in fields:
                require(fields['requires-body'] in {'0', '1'}, 'Invalid requires-body')
            if 'max-size' in fields:
                require(re.fullmatch(r'-1|[0-9]+', fields['max-size']) is not None,
                        'Invalid max-size')
            require(body.count(url) == 1, 'Ambiguous script-path')
            # Replace only the script-path value, retaining all other characters.
            line = re.sub(r'(\bscript-path\s*=\s*)' + re.escape(url),
                          lambda m: m[1] + DEST_PREFIX + filename, body) + ending
            seen.add(filename)
        elif section == '[MITM]':
            require(re.fullmatch(r'hostname\s*=\s*%APPEND%\s+[^\r\n]+',
                                 stripped) is not None, 'Unknown MITM action')
            hosts = stripped.split('%APPEND%', 1)[1].split(',')
            require(all(re.fullmatch(r'(?:\*\.)?[A-Za-z0-9.-]+', h.strip())
                        for h in hosts), 'Malformed hostname list')
            hostnames += 1
        else:
            raise SourceError('Unexpected module content')
        result.append(line)
    require({'name', 'desc', 'category'} <= metadata, 'Missing required metadata')
    require(sections == {'[Script]', '[MITM]'} and hostnames == 1,
            'Missing or duplicate MITM configuration')
    require(seen == ACTIONS.keys(), 'Incomplete dependency set')
    return ''.join(result).encode('utf-8')


def request_bytes(url):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'Wynston-Porntube-Mirror',
        'Accept': 'application/vnd.github+json',
    })
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read(LIMIT + 1)
    require(len(data) <= LIMIT, 'Upstream response exceeds size limit')
    return data


def api_json(url):
    try:
        return json.loads(request_bytes(url))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError('Invalid GitHub API JSON') from exc


def fetch_file(path, revision):
    raw = f'https://raw.githubusercontent.com/{SOURCE_REPO}/{revision}/{path}'
    try:
        data = request_bytes(raw)
        require(bool(data), 'Empty upstream file')
        return data
    except (urllib.error.URLError, OSError):
        # TLS / transport failures use GitHub Contents API without disabling TLS.
        url = f'https://api.github.com/repos/{SOURCE_REPO}/contents/{path}?ref={revision}'
        obj = api_json(url)
        require(isinstance(obj, dict) and obj.get('type') == 'file'
                and obj.get('path') == path and obj.get('encoding') == 'base64',
                'Unexpected GitHub Contents response')
        try:
            data = base64.b64decode(''.join(obj['content'].split()), validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError('Invalid Contents payload') from exc
        require(0 < len(data) <= LIMIT and len(data) == obj.get('size'),
                'Contents size mismatch')
        blob = b'blob ' + str(len(data)).encode() + b'\0' + data
        require(hashlib.sha1(blob).hexdigest() == obj.get('sha'),
                'Contents Git blob hash mismatch')
        return data


def syntax_check(assets):
    # node --check parses files without running their code.
    with tempfile.TemporaryDirectory(prefix='porntube-check-') as temp:
        for filename in ACTIONS:
            data = assets[DEST_JS + filename]
            require(isinstance(data, bytes) and 0 < len(data) <= LIMIT,
                    'Invalid JS size: ' + filename)
            try:
                data.decode('utf-8')
            except UnicodeDecodeError as exc:
                raise SourceError('Invalid JS encoding: ' + filename) from exc
            target = Path(temp) / filename
            target.write_bytes(data)
            check = subprocess.run(['node', '--check', str(target)],
                                   capture_output=True, timeout=60)
            require(check.returncode == 0, 'JS syntax check failed: ' + filename)


def sync(root, source_dir=None, fetch=None):
    root = Path(root).resolve()
    if source_dir is not None:
        source_dir = Path(source_dir).resolve()
        fetch = lambda path: (source_dir / path).read_bytes()
    elif fetch is None:
        obj = api_json(f'https://api.github.com/repos/{SOURCE_REPO}/commits/main')
        revision = obj.get('sha', '') if isinstance(obj, dict) else ''
        require(re.fullmatch(r'[0-9a-f]{40}', revision) is not None,
                'Cannot resolve upstream main revision')
        # Pin all five files to one upstream commit to avoid mixed revisions.
        fetch = lambda path: fetch_file(path, revision)
    module = transform_module(fetch(MODULE))
    assets = {DEST_MODULE: module}
    for filename in ACTIONS:
        assets[DEST_JS + filename] = fetch('porntube/dist/' + filename)
    syntax_check(assets)
    changes = {}
    for relative, data in assets.items():
        target = root / relative
        require(all(not p.is_symlink() for p in (target, *target.parents)
                    if p != root.parent), 'Refusing symlink destination')
        require(not target.exists() or target.is_file(), 'Destination is not a file')
        if not target.exists() or target.read_bytes() != data:
            changes[target] = data
    # Every source and destination has been validated before any output is written.
    # Stage all files before replacement; each replacement is atomic individually.
    staged = {}
    try:
        for target, data in changes.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.porntube-', dir=target.parent)
            staged[target] = temporary
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
            os.chmod(temporary, 0o644)
        for target, temporary in staged.items():
            os.replace(temporary, target)
    finally:
        for temporary in staged.values():
            Path(temporary).unlink(missing_ok=True)
    return [str(path.relative_to(root)) for path in changes]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path,
                        default=Path(__file__).resolve().parents[2])
    parser.add_argument('--source-dir', type=Path,
                        help='Offline root containing porntube/modules and porntube/dist')
    args = parser.parse_args()
    try:
        changed = sync(args.root, args.source_dir)
    except (SourceError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'Sync failed: {exc}\n')
    print('Updated: ' + ', '.join(changed) if changed else 'Unchanged')


if __name__ == '__main__':
    main()
