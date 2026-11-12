#!/usr/bin/env python3
"""Mirror kanlixiang.app.sgmodule and the exact scripts referenced by upstream.

Keep upstream metadata, comments, rule parameters, pinned refs and behavior; only
category and script-hosting URLs are changed. Do not invoke any app endpoint.
All downloads and syntax checks finish before an atomic Git publication bundle.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'https://raw.githubusercontent.com/Aioneas/Surge/main/Module/kanlixiang.app.sgmodule'
MODULE = Path('Surge/Module/kanlixiang.app.sgmodule')
ASSETS = Path('Surge/JavaScript/Kanlixiang')
MIRROR = 'https://raw.githubusercontent.com/Polly-ai/Wynston/main/'
SCRIPT_RE = re.compile(r'(?<![\w-])script-path=(https://[^\s,]+)')
ALLOWED_SECTIONS = {'Map Local', 'Script', 'MITM'}


class ReviewRequired(ValueError):
    pass


def text(data):
    value = data.decode('utf-8-sig')
    if not value.strip() or '\x00' in value or value.lstrip().lower().startswith(('<html', '<!doctype html')):
        raise ReviewRequired('Empty, binary or HTML source')
    return value


def script_filename(url):
    parsed = urllib.parse.urlsplit(url)
    match = re.fullmatch(r'/Aioneas/Surge/(main|[0-9a-f]{40})/Script/([A-Za-z0-9_.-]+\.js)', parsed.path)
    if parsed.scheme != 'https' or parsed.netloc != 'raw.githubusercontent.com' or not match or parsed.fragment:
        raise ReviewRequired('New script source requires explicit review')
    if parsed.query and not re.fullmatch(r'v=[A-Za-z0-9_.-]+', parsed.query):
        raise ReviewRequired('Unexpected script URL query')
    return match.group(2)


def download(url):
    if url != SOURCE:
        script_filename(url)
    error = None
    for _ in range(3):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'surge', 'Cache-Control': 'no-cache'})
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.status != 200 or response.geturl() != url:
                    raise ReviewRequired('Unexpected HTTP status or redirect')
                data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ReviewRequired('Source exceeds safety size limit')
            text(data)
            return data
        except Exception as exc:
            error = exc
    raise ReviewRequired('Download failed: ' + str(error))


def parse(module):
    value = text(module)
    section = None
    sections = set()
    urls = {}
    filenames = {}
    counts = {'Script': 0, 'Map Local': 0, 'MITM': 0}
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(('#', ';', '//')):
            continue
        if stripped.startswith('['):
            match = re.fullmatch(r'\[([^\]]+)\]', stripped)
            if not match or match.group(1) not in ALLOWED_SECTIONS:
                raise ReviewRequired('New module section requires review')
            section = match.group(1)
            sections.add(section)
            continue
        if section == 'Script':
            refs = SCRIPT_RE.findall(line)
            if len(refs) != 1 or not re.search(r'\btype=http-response\b', line):
                raise ReviewRequired('Unsupported script declaration')
            if not re.search(r'\brequires-body=(1|true)(?:\s*,|\s*$)', line):
                raise ReviewRequired('Response scripts must receive their body')
            source = refs[0]
            name = script_filename(source)
            if name in filenames and filenames[name] != source:
                raise ReviewRequired('Different script references share a filename')
            filenames[name] = source
            urls[source] = name
            counts[section] += 1
        elif section == 'Map Local':
            match = re.fullmatch(r'(\S+)\s+data-type=base64\s+data="([A-Za-z0-9+/=]+)"\s+status-code=(\d+)\s+header="[^"]+"', stripped)
            if not match or not 200 <= int(match.group(3)) <= 999:
                raise ReviewRequired('New Map Local syntax requires review')
            re.compile(match.group(1))
            base64.b64decode(match.group(2), validate=True)
            counts[section] += 1
        elif section == 'MITM':
            match = re.fullmatch(r'hostname\s*=\s*%APPEND%\s+(.+)', stripped)
            if not match or set(h.strip() for h in match.group(1).split(',')) != {'api.vistopia.com.cn', 'shop.vistopia.com.cn'}:
                raise ReviewRequired('MITM scope changed; manual review required')
            counts[section] += 1
        else:
            raise ReviewRequired('Unexpected line outside module sections')
    if sections != ALLOWED_SECTIONS or not all(counts.values()):
        raise ReviewRequired('Incomplete upstream module')
    for key in ('name', 'desc', 'author'):
        if len(re.findall(r'^#!' + key + r'\s*=.+$', value, re.M)) != 1:
            raise ReviewRequired('Missing/duplicate upstream metadata: ' + key)
    return urls


def render(module):
    urls = parse(module)
    lines = text(module).splitlines(keepends=True)
    categories = 0
    output = []
    for line in lines:
        if re.match(r'^#!category\s*=', line):
            categories += 1
            newline = '\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
            line = '#!category=Polly-ai' + newline
        elif not line.lstrip().startswith(('#', ';', '//')) and SCRIPT_RE.search(line):
            source = SCRIPT_RE.search(line).group(1)
            line = line.replace(source, MIRROR + (ASSETS / urls[source]).as_posix(), 1)
        output.append(line)
    if categories > 1:
        raise ReviewRequired('Duplicate category')
    if not categories:
        output.insert(0, '#!category=Polly-ai\n')
    return ''.join(output).encode('utf-8')


def validate_javascript(sources):
    # Syntax only: never execute downloaded code with a CI token or contact app APIs.
    with tempfile.TemporaryDirectory(prefix='kanlixiang-check-') as directory:
        for name, data in sources.items():
            content = text(data)
            if '$done' not in content:
                raise ReviewRequired('Unexpected script body: ' + name)
            path = Path(directory) / name
            path.write_bytes(data)
            result = subprocess.run(['node', '--check', str(path)], capture_output=True, text=True, timeout=25)
            if result.returncode:
                raise ReviewRequired('JavaScript syntax check failed: ' + name)


def prepare(module, fetcher=download):
    refs = parse(module)
    scripts = {name: fetcher(url) for url, name in refs.items()}
    validate_javascript(scripts)
    return {MODULE: render(module), **{ASSETS / name: data for name, data in scripts.items()}}


def replace_bundle(root, files):
    changed = {path: data for path, data in files.items()
               if not (root / path).exists() or (root / path).read_bytes() != data}
    previous = {path: (root / path).read_bytes() if (root / path).exists() else None for path in changed}
    staged, replaced = {}, []
    try:
        for path, data in changed.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + '.sync-tmp')
            temp.write_bytes(data)
            staged[path] = temp
        for path, temp in staged.items():
            temp.replace(root / path)
            replaced.append(path)
    except BaseException:
        for path in reversed(replaced):
            if previous[path] is None:
                (root / path).unlink(missing_ok=True)
            else:
                (root / path).write_bytes(previous[path])
        raise
    finally:
        for temp in staged.values():
            temp.unlink(missing_ok=True)
    return [path.as_posix() for path in changed]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', type=Path, help='Local upstream module snapshot')
    parser.add_argument('--script-dir', type=Path, help='Local exact dependency snapshots')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        module = args.module.read_bytes() if args.module else download(SOURCE)
        fetcher = (lambda url: (args.script_dir / script_filename(url)).read_bytes()) if args.script_dir else download
        files = prepare(module, fetcher)
        changed = replace_bundle(args.root, files)
        print('sync_kanlixiang: ' + (', '.join(changed) if changed else 'no upstream changes'))
        return 0
    except (ReviewRequired, OSError, UnicodeError, ValueError, subprocess.SubprocessError) as exc:
        print('sync_kanlixiang: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
