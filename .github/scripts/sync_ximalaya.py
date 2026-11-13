#!/usr/bin/env python3
"""Sync the reviewed Ximalaya upstream JavaScript into the Surge bundle."""
from pathlib import Path
import hashlib, subprocess, tempfile, urllib.request

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'https://raw.githubusercontent.com/WeiGiegie/666/main/ximalaya.js'
MODULE = ROOT / 'Surge/Module/ximalaya_enhanced.sgmodule'
SCRIPT = ROOT / 'Surge/JavaScript/Ximalaya/ximalaya.js'


def fetch(url):
    if url != SOURCE:
        raise ValueError('unreviewed source')
    req = urllib.request.Request(url, headers={'User-Agent': 'surge', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=90) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('unexpected HTTP response')
        data = response.read(1000001)
    if not data or len(data) > 1000000 or data.lstrip().startswith(b'<'):
        raise ValueError('invalid source')
    data.decode('utf-8')
    return data


def bundle(source):
    text = source.decode('utf-8')
    marker = 'https://raw.githubusercontent.com/WeiGiegie/666/main/ximalaya.js'
    if marker not in text:
        raise ValueError('source identity marker missing')
    if '[rewrite_local]' not in text or '[mitm]' not in text.lower():
        raise ValueError('expected source sections missing')
    return source


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-dir', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    source = (args.source_dir / 'ximalaya.js').read_bytes() if args.source_dir else fetch(SOURCE)
    source = bundle(source)
    script = args.root / SCRIPT.relative_to(ROOT)
    module = args.root / MODULE.relative_to(ROOT)
    script.parent.mkdir(parents=True, exist_ok=True)
    module.parent.mkdir(parents=True, exist_ok=True)
    old = script.read_bytes() if script.exists() else None
    script.write_bytes(source)
    try:
        subprocess.run(['node', '--check', str(script)], check=True, timeout=60)
    except BaseException:
        if old is None: script.unlink(missing_ok=True)
        else: script.write_bytes(old)
        raise
    print('source sha256:', hashlib.sha256(source).hexdigest())
    print('Updated:', script if old != source else 'no upstream changes')


if __name__ == '__main__':
    main()
