#!/usr/bin/env python3
"""Mirror JD Helper and its explicit dependency without changing behavior."""
import argparse
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
MODULE_URL='https://raw.githubusercontent.com/githubdulong/Script/master/Surge/JD_Helper.sgmodule'
SCRIPT_URL='https://raw.githubusercontent.com/githubdulong/Script/master/jd_price1.js'
MODULE=Path('Surge/Module/JD_Helper.sgmodule')
SCRIPT=Path('Surge/JavaScript/JD_Helper/jd_price1.js')
RAW='https://raw.githubusercontent.com/Polly-ai/Wynston/main/'
class ReviewRequired(ValueError): pass

def fetch(url):
    if url not in (MODULE_URL,SCRIPT_URL): raise ReviewRequired('Unreviewed source')
    req=urllib.request.Request(url,headers={'User-Agent':'surge','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req,timeout=60) as response:
        if response.status!=200 or response.geturl()!=url: raise ReviewRequired('Unexpected HTTP response')
        data=response.read(2000001)
    if not data.strip() or len(data)>2000000: raise ReviewRequired('Empty or oversized source')
    if data.lstrip().lower().startswith((b'<html',b'<!doctype html')): raise ReviewRequired('HTML instead of source')
    data.decode('utf-8')
    return data

def render(module,script):
    text=module.decode('utf-8')
    section=''; declarations=[]
    for line in text.splitlines():
        stripped=line.strip()
        if stripped.startswith('['): section=stripped
        elif section=='[Script]' and stripped and not stripped.startswith(('#',';')):
            declarations.append(stripped)
    if len(declarations)!=2: raise ReviewRequired('Expected two script declarations')
    for line in declarations:
        if 'script-path=' not in line: raise ReviewRequired('Missing script URL')
        url=line.split('script-path=',1)[1].split(',',1)[0].strip()
        if url!=SCRIPT_URL: raise ReviewRequired('Unreviewed script source')
        if not any('type='+kind+',' in line for kind in ('http-request','http-response')):
            raise ReviewRequired('Unreviewed script type')
    if '[MITM]' not in text or '#!arguments=' not in text: raise ReviewRequired('Incomplete module')
    if not script.strip() or b'$done' not in script: raise ReviewRequired('Invalid script')
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'original.js';path.write_bytes(script)
        subprocess.run(['node','--check',str(path)],check=True,capture_output=True,timeout=30)
    text=text.replace('script-path='+SCRIPT_URL,'script-path='+RAW+SCRIPT.as_posix())
    if re.search(r'(?m)^#!category=',text):
        text=re.sub(r'(?m)^#!category=.*$','#!category=Polly-ai',text)
    else: text='#!category=Polly-ai\n'+text
    return text.encode('utf-8')

def write(root,files):
    changed={p:b for p,b in files.items() if not (root/p).exists() or (root/p).read_bytes()!=b}
    old={p:(root/p).read_bytes() if (root/p).exists() else None for p in changed}
    staged={};done=[]
    try:
        for path,data in changed.items():
            target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
            temp=target.with_name(target.name+'.sync-tmp');temp.write_bytes(data);staged[path]=temp
        for path,temp in staged.items():temp.replace(root/path);done.append(path)
    except BaseException:
        for path in reversed(done):
            if old[path] is None:(root/path).unlink(missing_ok=True)
            else:(root/path).write_bytes(old[path])
        raise
    finally:
        for temp in staged.values():temp.unlink(missing_ok=True)
    return [str(p) for p in changed]

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--module',type=Path);parser.add_argument('--script',type=Path);parser.add_argument('--root',type=Path,default=ROOT);args=parser.parse_args(argv)
    try:
        module=args.module.read_bytes() if args.module else fetch(MODULE_URL)
        script=args.script.read_bytes() if args.script else fetch(SCRIPT_URL)
        changed=write(args.root,{MODULE:render(module,script),SCRIPT:script})
        print('sync_jd_helper:',', '.join(changed) if changed else 'no upstream changes');return 0
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        print('sync_jd_helper:',error,file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
