#!/usr/bin/env python3
"""Synchronize the complete YouTube snippet and native binary-response script.

The module name/category are fixed; the original description is retained exactly.
Per user decision, upstream's broken 302 rule remains commented out, not silently
repaired. Four reject-200 rules use native Map Local. Protobuf JS is mirrored
byte-for-byte with binary-body-mode, without modifying its internal feature set.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_URL = 'https://raw.githubusercontent.com/ZenmoFeiShi/Qx/refs/heads/main/Youtube.snippet'
JS_URL = 'https://raw.githubusercontent.com/ZenmoFeiShi/Qx/refs/heads/main/youtube.response.js'
MODULE = Path('Surge/Module/YouTube.sgmodule')
JAVASCRIPT = Path('Surge/JavaScript/YouTube/youtube.response.js')
MIRROR = 'https://raw.githubusercontent.com/Polly-ai/Wynston/main/' + JAVASCRIPT.as_posix()
NAME = 'YouTube 净化'
CATEGORY = 'Polly-ai'
ALLOWED_HOSTS = {'*.googlevideo.com','redirector*.googlevideo.com','www.youtube.com',
                 's.youtube.com','youtubei.googleapis.com'}
RESPONSE_PATTERN = r'^https?:\/\/youtubei\.googleapis\.com\/youtubei\/v1\/(browse|next|player|search|reel\/reel_watch_sequence|guide|account\/get_setting|get_watch)'
REJECT_PATTERNS = {
 r'^https?:\/\/[\w-]+\.googlevideo\.com\/(?!(dclk_video_ads|videoplayback\?)).+&oad',
 r'^https?:\/\/(www|s)\.youtube\.com\/api\/stats\/ads',
 r'^https?:\/\/(www|s)\.youtube\.com\/(pagead|ptracking)',
 r'^https?:\/\/s\.youtube\.com\/api\/stats\/qoe\?adcontext',
}


class ReviewRequired(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str) -> bytes:
    if url not in {CONFIG_URL,JS_URL}:
        raise ReviewRequired('Unreviewed source URL')
    error = None
    for _ in range(3):
        try:
            request = urllib.request.Request(url,headers={
                'User-Agent':'surge','Accept-Encoding':'identity','Cache-Control':'no-cache'})
            with urllib.request.urlopen(request,timeout=60) as response:
                if response.status != 200 or response.geturl() != url:
                    raise ReviewRequired('HTTP or source redirect requires review')
                raw = response.read(2_000_001)
            if not raw.strip() or len(raw)>2_000_000:
                raise ReviewRequired('Empty or oversized source')
            text = raw.decode('utf-8-sig')
            if text.lstrip().lower().startswith(('<html','<!doctype html')):
                raise ReviewRequired('HTML returned instead of source')
            return raw
        except Exception as exc:
            error = exc
    raise ReviewRequired(f'Upstream fetch failed: {url}: {error}')


def parse(data: bytes):
    text = data.decode('utf-8-sig')
    if '\x00' in text:
        raise ReviewRequired('Null byte in upstream config')
    metadata,hosts,rules,comments = {},[],[],[]
    seen = set()
    for number,original in enumerate(text.splitlines(),1):
        line = original.strip()
        if not line:
            continue
        meta = re.fullmatch(r'#!([A-Za-z0-9_-]+)\s*=(.*)',line)
        if meta:
            key,value = meta.groups()
            if key in metadata:
                raise ReviewRequired('Duplicate metadata key')
            metadata[key] = value.lstrip()
            continue
        if line.startswith(('#','//')):
            comments.append('#' + line[2:] if line.startswith('//') else line)
            continue
        host = re.fullmatch(r'hostname\s*=\s*(.+)',line,re.I)
        if host:
            for name in host.group(1).split(','):
                name = name.strip()
                if name not in ALLOWED_HOSTS:
                    raise ReviewRequired('New MITM hostname requires review')
                if name not in hosts:
                    hosts.append(name)
            continue
        disabled = line.startswith(';')
        if disabled:
            line = line[1:].strip()
        match = re.fullmatch(r'(\^\S+)\s+url\s+(\S+)(?:\s+(\S+))?',line)
        if not match:
            raise ReviewRequired(f'Unknown source directive at line {number}')
        pattern,action,argument = match.groups()
        if pattern in seen:
            raise ReviewRequired('Duplicate URL pattern')
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ReviewRequired('Invalid upstream regex') from exc
        if action=='script-response-body':
            if pattern!=RESPONSE_PATTERN or argument!=JS_URL or disabled:
                raise ReviewRequired('Response path/source/enablement drift requires review')
        elif action=='reject-200':
            if pattern not in REJECT_PATTERNS or argument or disabled:
                raise ReviewRequired('Reject pattern or action drift requires review')
        elif action=='302':
            if not argument or not argument.startswith('https://'):
                raise ReviewRequired('Unreviewed redirect replacement')
            # Kept disabled even if the source changes: re-enablement is a user decision.
        else:
            raise ReviewRequired('Unsupported upstream action')
        seen.add(pattern)
        rules.append((pattern,action,argument,disabled,line))
    active = {(p,a) for p,a,_,_,_ in rules if a!='302'}
    expected = {(RESPONSE_PATTERN,'script-response-body')} | {(p,'reject-200') for p in REJECT_PATTERNS}
    if not hosts or active!=expected or sum(a=='302' for _,a,_,_,_ in rules)!=1:
        raise ReviewRequired('Missing/changed full upstream rules or MITM hostnames')
    if 'desc' not in metadata or not metadata['desc']:
        raise ReviewRequired('Missing original module description')
    return metadata,hosts,rules,comments


def render(config: bytes,javascript: bytes) -> bytes:
    meta,hosts,rules,comments = parse(config)
    lines = [
        '#!name = ' + NAME,
        '#!desc=' + meta['desc'],
        '#!category = ' + CATEGORY,
        '#!author=' + meta.get('author','ZenmoFeiShi'),
        '# 上游配置：' + CONFIG_URL,
        '# 上游脚本：' + JS_URL,
        '# 原配置 SHA256：' + digest(config),
        '# 原 JavaScript SHA256：' + digest(javascript),
        '# 名称固定，描述逐字保留上游原文；配置与原JS每日同时同步。',
        '# 原JS原生支持Surge：binary-body-mode=true传入/返回Uint8Array，不转成文本或ArrayBuffer。',
        '# 保留上游全部广告、Shorts和购物卡清理逻辑；本机脚本缓存设置和默认开关不改。',
        '# 需启用重写、MITM并信任证书；Map Local需Surge iOS5.9.1+/Mac5.5.1+。',
        '# Protobuf响应缓存上限4MiB；超限跳过脚本透传。不得与其他同接口的YouTube响应脚本重叠。',
        '# 客户端播放能力标记不代表真实订阅或服务器端授权；未在用户设备进行端到端测试。',
        '# 按用户选择暂时停用上游302规则：源仅有2个捕获组却引用$3，且含,ctier,字面量。',
        '# 不静默修复或重新开启302；未来如需启用，应先审查修正规则。',
    ]
    lines.extend(comments)
    lines.extend(['','[URL Rewrite]'])
    for pattern,action,argument,disabled,original in rules:
        if action=='302':
            lines.extend(['# 上游原行（保留但不启用）：' + original,
                          '# ' + pattern + ' ' + argument + ' 302'])
    lines.extend(['','[Map Local]','# QX reject-200：原生HTTP 200空体，保留原URL匹配范围。'])
    for pattern,action,_,_,_ in rules:
        if action=='reject-200':
            lines.append(pattern + ' data-type=text data="" status-code=200 '
                         'header="Content-Type:text/plain; charset=utf-8|Cache-Control:no-store"')
    lines.extend(['','[Script]'])
    for pattern,action,_,_,_ in rules:
        if action=='script-response-body':
            lines.append('youtube-cleanup = type=http-response, pattern=' + pattern +
                         ', requires-body=true, binary-body-mode=true, max-size=4194304, '
                         'script-path=' + MIRROR + ', script-update-interval=86400, timeout=15')
    lines.extend(['','[MITM]','hostname = %APPEND% ' + ', '.join(hosts),''])
    return '\n'.join(lines).encode('utf-8')


def validate(config: bytes,javascript: bytes):
    parse(config)
    javascript.decode('utf-8-sig')
    if not javascript.strip() or b'bodyBytes' not in javascript or b'$done' not in javascript:
        raise ReviewRequired('Unexpected binary-response JavaScript')
    tests = Path(__file__).with_name('test_youtube_behavior.cjs')
    support = Path(__file__).with_name('youtube_test_runtime.cjs')
    if not tests.is_file() or not support.is_file():
        raise ReviewRequired('Missing binary regression test files')
    with tempfile.TemporaryDirectory(prefix='youtube-sync-') as directory:
        path = Path(directory)/'youtube.response.js'
        path.write_bytes(javascript)
        syntax = subprocess.run(['node','--check',str(path)],capture_output=True,text=True,timeout=30)
        if syntax.returncode:
            raise ReviewRequired('Downloaded JavaScript syntax is invalid')
        result = subprocess.run(['node',str(tests),str(path)],capture_output=True,text=True,timeout=180)
        if result.returncode:
            raise ReviewRequired('YouTube binary regression failed: '+result.stderr[-2000:]+' '+result.stdout[-2500:])
        # Detailed individual results are kept by the tests; keep CI logs concise.
        import json
        summary = json.loads(result.stdout)
        if summary.get('fail') != 0:
            raise ReviewRequired('YouTube binary fixtures did not all pass')
        print('YouTube runtime: '+str(summary.get('pass'))+' passed, '+
              str(summary.get('known'))+' documented upstream limits, no failures')


def prepare(config: bytes,javascript: bytes):
    validate(config,javascript)
    return {JAVASCRIPT:javascript,MODULE:render(config,javascript)}


def replace_bundle(root: Path,files: dict[Path,bytes]) -> bool:
    changed = {p:data for p,data in files.items()
               if not (root/p).exists() or (root/p).read_bytes()!=data}
    if not changed:
        return False
    old = {p:(root/p).read_bytes() if (root/p).exists() else None for p in changed}
    staged,done = {},[]
    try:
        for path,data in changed.items():
            target = root/path
            target.parent.mkdir(parents=True,exist_ok=True)
            temporary = target.with_name(target.name+'.sync-tmp')
            temporary.write_bytes(data)
            staged[path] = temporary
        for path,temporary in staged.items():
            temporary.replace(root/path)
            done.append(path)
    except BaseException:
        for path in reversed(done):
            if old[path] is None:
                (root/path).unlink(missing_ok=True)
            else:
                (root/path).write_bytes(old[path])
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--javascript',type=Path)
    parser.add_argument('--root',type=Path,default=ROOT)
    args = parser.parse_args(argv)
    try:
        config = args.config.read_bytes() if args.config else download(CONFIG_URL)
        parse(config)
        javascript = args.javascript.read_bytes() if args.javascript else download(JS_URL)
        files = prepare(config,javascript)
        changed = replace_bundle(args.root,files)
        print('sync_youtube: '+('module and original JS updated' if changed else 'no upstream changes'))
        return 0
    except (ReviewRequired,OSError,UnicodeError,subprocess.SubprocessError) as exc:
        print('sync_youtube: '+str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())
