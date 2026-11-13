#!/usr/bin/env python3
"""Mirror the native TMDB module and its explicit scripts; no API execution."""
import argparse,re,subprocess,tempfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE='https://raw.githubusercontent.com/DemoJameson/TMDB-Proxy/main/dist/'
SOURCE=BASE+'tmdb_proxy.sgmodule'
MODULE=Path('Surge/Module/tmdb_proxy.sgmodule')
ASSETS=Path('Surge/JavaScript/TMDB')
RAW='https://raw.githubusercontent.com/Polly-ai/Wynston/main/'
NAMES={'tmdb_proxy_request.js','tmdb_proxy_response.js'}

def fetch(url):
    if url not in {SOURCE}|{BASE+n for n in NAMES}:raise ValueError('Unreviewed source')
    req=urllib.request.Request(url,headers={'User-Agent':'surge','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req,timeout=60) as r:
        if r.status!=200 or r.geturl()!=url:raise ValueError('HTTP/redirect mismatch')
        data=r.read(2000001)
    if not data.strip() or len(data)>2000000 or data.lstrip().startswith(b'<'):raise ValueError('Invalid source')
    data.decode('utf-8');return data

def references(module):
    section='';refs=[]
    for line in module.decode().splitlines():
        s=line.strip()
        if s.startswith('['):section=s
        elif section=='[Script]' and s and not s.startswith(('#',';')):
            urls=re.findall(r'script-path=([^,\s]+)',s)
            if len(urls)!=1 or urls[0] not in {BASE+n for n in NAMES}:raise ValueError('Unreviewed script dependency')
            refs.append(urls[0])
    if not refs or set(refs)!={BASE+n for n in NAMES}:raise ValueError('Missing dependencies')
    return refs

def render(module):
    refs=references(module);lines=[];category=False
    for line in module.decode().splitlines(keepends=True):
        if line.startswith('#!category='):
            line='#!category=Polly-ai\n';category=True
        elif not line.lstrip().startswith(('#',';')):
            for url in set(refs):line=line.replace('script-path='+url,'script-path='+RAW+str(ASSETS/url.rsplit('/',1)[1]))
        lines.append(line)
    return (('' if category else '#!category=Polly-ai\n')+''.join(lines)).encode()

def write_bundle(root,files):
    changed={p:b for p,b in files.items() if not (root/p).exists() or (root/p).read_bytes()!=b}
    old={p:(root/p).read_bytes() if (root/p).exists() else None for p in changed};temps={};done=[]
    try:
        for p,b in changed.items():
            t=root/p;t.parent.mkdir(parents=True,exist_ok=True);tmp=t.with_name(t.name+'.sync-tmp');tmp.write_bytes(b);temps[p]=tmp
        for p,tmp in temps.items():tmp.replace(root/p);done.append(p)
    except BaseException:
        for p in reversed(done):
            if old[p] is None:(root/p).unlink(missing_ok=True)
            else:(root/p).write_bytes(old[p])
        raise
    finally:
        for tmp in temps.values():tmp.unlink(missing_ok=True)
    return list(changed)

def main():
    p=argparse.ArgumentParser();p.add_argument('--source-dir',type=Path);p.add_argument('--root',type=Path,default=ROOT);a=p.parse_args()
    get=lambda url:(a.source_dir/url.rsplit('/',1)[1]).read_bytes() if a.source_dir else fetch(url)
    module=get(SOURCE);refs=references(module);files={MODULE:render(module)}
    with tempfile.TemporaryDirectory() as directory:
        for url in sorted(set(refs)):
            name=url.rsplit('/',1)[1];data=get(url);data.decode('utf-8');t=Path(directory)/name;t.write_bytes(data)
            subprocess.run(['node','--check',str(t)],check=True,timeout=30)
            files[ASSETS/name]=data
    changed=write_bundle(a.root,files);print('Updated:',*[str(p) for p in changed] if changed else ['no upstream changes'])
if __name__=='__main__':main()
