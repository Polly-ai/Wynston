#!/usr/bin/env python3
"""Sync the complete WeiboEnhanced config and native multi-client JavaScript.

Source is fetched directly with User-Agent:surge, without depending on the local
script.hub converter. Preserve all six rule patterns and the interactive settings
page/save/reset APIs. The upstream JS already provides Surge-native response and
persistent-store adapters, so keep it byte-for-byte. Unknown syntax/download or
regression failures stop before writing any output. Name/category remain fixed.
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

UPSTREAM_URL = 'https://ddgksf2013.top/rewrite/WeiboEnhanced.conf'
SCRIPT_URL = 'https://ddgksf2013.top/scripts/weibo_json.js'
MODULE_PATH = Path('Surge/Module/WeiboEnhanced.sgmodule')
SCRIPT_PATH = Path('Surge/JavaScript/Weibo/weibo_json.js')
RAW_ROOT = 'https://raw.githubusercontent.com/Polly-ai/Wynston/main'
NAME = '微博 增强助手'
CATEGORY = 'Polly-ai'
VALID_ACTIONS = {'script-echo-response', 'script-analyze-echo-response', 'script-response-body'}
ALLOWED_HOSTS = {'api.weibo.cn', 'bootpreload.uve.weibo.com',
                 'bootrealtime.uve.weibo.com', 'wbapp.uve.weibo.com'}


class SyncError(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str) -> bytes:
    if url not in {UPSTREAM_URL, SCRIPT_URL}:
        raise SyncError('Unreviewed upstream URL')
    error = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'surge', 'Cache-Control': 'no-cache'})
            with urllib.request.urlopen(req, timeout=60) as response:
                if response.status != 200:
                    raise SyncError('Unexpected HTTP status')
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise SyncError('Upstream exceeds 2 MB safety limit')
                text = raw.decode('utf-8-sig')
                if not text.strip() or text.lstrip().lower().startswith(('<html', '<!doctype html')):
                    raise SyncError('Unexpected empty or HTML source')
                return raw
        except Exception as exc:
            error = exc
    raise SyncError(f'Upstream download failed: {url}: {error}')


def parse(text: str):
    hosts, rules, notes = [], [], []
    patterns = set()
    pending = ''
    comment = ''
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(('//', '#', ';')):
            if line.startswith('# >'):
                comment = line
            elif line.startswith(';^'):
                notes.append('# 上游默认停用（保持停用）：' + line[1:])
            continue
        if pending:
            line = pending + ' ' + line
            pending = ''
        if (line.startswith('hostname') and line.endswith(',')) or re.search(
                r'\burl\s+script-(?:response-body|echo-response|analyze-echo-response)$', line):
            pending = line
            continue
        match = re.fullmatch(r'hostname\s*=\s*(.+)', line)
        if match:
            for host in match.group(1).split(','):
                host = host.strip()
                if host not in ALLOWED_HOSTS:
                    raise SyncError(f'Line {number}: new MITM host requires review')
                if host not in hosts:
                    hosts.append(host)
            continue
        match = re.fullmatch(r'(\^\S+)\s+url\s+(\S+)\s+(https://\S+)', line)
        if not match:
            raise SyncError(f'Line {number}: unsupported upstream directive')
        pattern, action, source = match.groups()
        if action not in VALID_ACTIONS or source != SCRIPT_URL or ',' in pattern:
            raise SyncError(f'Line {number}: unsupported action, source or regex separator')
        if pattern in patterns:
            raise SyncError('Duplicate URL regex')
        try:
            re.compile(pattern)
        except re.error as exc:
            raise SyncError('Invalid upstream regular expression') from exc
        if action != 'script-response-body' and '__qx_weibo_settings__' not in pattern:
            raise SyncError('New local echo endpoint requires review')
        patterns.add(pattern)
        rules.append((pattern, action, comment))
        comment = ''
    if pending:
        raise SyncError('Incomplete upstream continuation')
    if not hosts or not rules or not any(action == 'script-response-body' for _,action,_ in rules):
        raise SyncError('Missing Weibo MITM hosts or response rules')
    return hosts, rules, notes


def metadata(text: str, key: str) -> str:
    match = re.search(r'^\s*//\s*@' + re.escape(key) + r'\s+(.+?)\s*$', text, re.M)
    return match.group(1) if match else '未标注'


def render(config: bytes, javascript: bytes) -> str:
    text = config.decode('utf-8-sig')
    hosts, rules, notes = parse(text)
    out = [
        '#!name = ' + NAME,
        '#!desc = 微博广告净化与全面自定义，保留上游设置页面、保存/重置和全部功能；每日同步上游配置及JS。',
        '#!category = ' + CATEGORY,
        '#!author = ddgksf2013 / zmqcherish',
        '# 上游配置：' + UPSTREAM_URL,
        '# 配置版本：' + metadata(text, 'Version') + '；原作者更新：' + metadata(text, 'UpdateTime'),
        '# 配置 SHA256：' + sha(config),
        '# 原始 weibo_json.js SHA256：' + sha(javascript),
        '# 转换与维护：Polly-ai/Wynston。保留上游JS原文，不依赖 script.hub 本地转换。',
        '# 自定义入口：https://api.weibo.cn/__qx_weibo_settings__/',
        '# 安装并启用后，用Safari打开上面的设置页面；选项保存在Surge本机，跟随上游更新不清空。',
        '# 设置页及配置API由请求脚本本地回应；保存/重置读取请求体，不发送到微博服务端。',
        '# 需启用重写与MITM并信任证书；勿与其他同接口的微博响应脚本重复启用。',
        '# 上游没有静态 reject/Map Local 规则；两个动态设置接口不能用固定空体映射代替。',
        '# QX兼容性增强开关的原注意事项不适用于Surge；这里使用上游原生Surge适配。',
        '# 响应脚本最多缓存1MiB，超限透传；无变化不提交，下载或验证失败不发布。',
        '', '[Script]',
    ]
    for pattern, action, comment in rules:
        if comment:
            out.append(comment)
        identifier = 'weibo_' + hashlib.sha256(pattern.encode()).hexdigest()[:12]
        script_type = 'http-response' if action == 'script-response-body' else 'http-request'
        if action == 'script-echo-response':
            options = 'requires-body=false, '
        elif action == 'script-analyze-echo-response':
            options = 'requires-body=true, max-size=262144, '
        else:
            options = 'requires-body=true, max-size=1048576, '
        out.append(f'{identifier} = type={script_type}, pattern={pattern}, {options}'
                   f'script-path={RAW_ROOT}/{SCRIPT_PATH.as_posix()}, '
                   'script-update-interval=86400, timeout=15')
    if notes:
        out.extend(['', *notes])
    out.extend(['', '[MITM]', 'hostname = %APPEND% ' + ', '.join(hosts), ''])
    return '\n'.join(out)


def validate_script(javascript: bytes, test_path: Path):
    """Parse and regression-test a downloaded script before making any changes."""
    text = javascript.decode('utf-8-sig')
    if (not text.strip() or '$done' not in text or
            'createWeiboClientRuntime' not in text or 'createSettingsHandler' not in text):
        raise SyncError('Incomplete or unexpected Weibo JavaScript')
    if not test_path.is_file():
        raise SyncError('Missing Weibo runtime regression test')
    with tempfile.TemporaryDirectory(prefix='weibo-sync-') as directory:
        path = Path(directory) / 'weibo_json.js'
        path.write_bytes(javascript)
        syntax = subprocess.run(['node', '--check', str(path)],
                                capture_output=True, text=True, timeout=20)
        if syntax.returncode:
            raise SyncError('JavaScript syntax check failed: ' + syntax.stderr[:1000])
        runtime = subprocess.run(['node', str(test_path), str(path), '15000'],
                                 capture_output=True, text=True, timeout=180)
        if runtime.returncode:
            raise SyncError('Weibo settings/response regression failed: ' + runtime.stderr[:2000])
        print(runtime.stdout.strip())


def prepare(config: bytes, javascript: bytes, test_path: Path):
    parse(config.decode('utf-8-sig'))
    validate_script(javascript, test_path)
    return {SCRIPT_PATH: javascript, MODULE_PATH: render(config, javascript).encode('utf-8')}


def write_changed(path: Path, data: bytes) -> bool:
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.sync-tmp')
    temporary.write_bytes(data)
    temporary.replace(path)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-file', type=Path)
    parser.add_argument('--script-file', type=Path)
    parser.add_argument('--root', type=Path, default=Path('.'))
    args = parser.parse_args(argv)
    try:
        config = args.from_file.read_bytes() if args.from_file else download(UPSTREAM_URL)
        parse(config.decode('utf-8-sig'))
        javascript = args.script_file.read_bytes() if args.script_file else download(SCRIPT_URL)
        tests = Path(__file__).with_name('test_weibo_runtime.cjs')
        files = prepare(config, javascript, tests)
        changed = [str(path) for path, data in files.items() if write_changed(args.root / path, data)]
        print('sync_weibo_enhanced: ' + ('updated ' + ', '.join(changed) if changed else 'no upstream changes'))
        return 0
    except (SyncError, OSError, UnicodeError, subprocess.SubprocessError) as exc:
        print('sync_weibo_enhanced: error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
