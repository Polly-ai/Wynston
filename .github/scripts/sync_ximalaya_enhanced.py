#!/usr/bin/env python3
"""Mirror the reviewed Ximalaya script for ximalaya_enhanced.sgmodule."""
from pathlib import Path
import hashlib, subprocess, urllib.request
ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'https://raw.githubusercontent.com/WeiGiegie/666/main/ximalaya.js'
SCRIPT = ROOT / 'Surge/JavaScript/Ximalaya/ximalaya.js'
MODULE = ROOT / 'Surge/Module/ximalaya_enhanced.sgmodule'
def fetch():
    req = urllib.request.Request(SOURCE, headers={'User-Agent':'surge','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req, timeout=90) as r:
        if r.status != 200 or r.geturl() != SOURCE: raise ValueError('unexpected upstream response')
        data = r.read(1000001)
    if not data or len(data) > 1000000: raise ValueError('invalid upstream data')
    data.decode('utf-8')
    if b'[rewrite_local]' not in data or b'[mitm]' not in data.lower(): raise ValueError('unexpected source')
    return data
def main():
    data = fetch(); old = SCRIPT.read_bytes() if SCRIPT.exists() else None
    SCRIPT.parent.mkdir(parents=True, exist_ok=True); SCRIPT.write_bytes(data)
    try: subprocess.run(['node','--check',str(SCRIPT)], check=True, timeout=60)
    except BaseException:
        if old is None: SCRIPT.unlink(missing_ok=True)
        else: SCRIPT.write_bytes(old)
        raise
    print('sha256:', hashlib.sha256(data).hexdigest())
    print('changed:', old != data)
if __name__ == '__main__': main()
