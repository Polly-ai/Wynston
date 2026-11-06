#!/usr/bin/env python3
"""Daily FULL conversion of embedded QX rules in ddgksf2013 BaiduPan scripts.

Both modules retain all original patterns, comments, MIME/status semantics and
JavaScript snapshots. Static replies use native Map Local; the single jq rewrite
is implemented locally. Unknown syntax or failed fixtures retain the old bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = 'https://raw.githubusercontent.com/Polly-ai/Wynston/main'
ASSETS = Path('Surge/JavaScript/BaiduPan')
PROJECTS = {
 'ads': {'source':'https://ddgksf2013.top/scripts/bdpan.ads.js',
         'filename':'bdpan.ads.js', 'module':'Surge/Module/bdpan.ads.sgmodule',
         'name':'百度网盘净化'},
 'unlock': {'source':'https://ddgksf2013.top/scripts/bdpan.unlock.js',
            'filename':'bdpan.unlock.js', 'module':'Surge/Module/bdpan.unlock.sgmodule',
            'name':'百度网盘 功能增强'},
}
ACTIONS = {'reject-200','reject-dict','script-response-body','script-request-header',
           'jsonjq-response-body'}
HOSTS = {'pan.baidu.com','afd.baidu.com'}


class ReviewRequired(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str) -> bytes:
    if url not in {project['source'] for project in PROJECTS.values()}:
        raise ReviewRequired('Unapproved upstream source URL')
    error = None
    for _ in range(3):
        try:
            request = urllib.request.Request(url, headers={
                'User-Agent':'surge','Cache-Control':'no-cache','Accept-Encoding':'identity'})
            with urllib.request.urlopen(request,timeout=60) as response:
                if response.status != 200 or response.geturl() != url:
                    raise ReviewRequired('Redirect or HTTP failure requires review')
                data = response.read(2_000_001)
            if not data.strip() or len(data) > 2_000_000:
                raise ReviewRequired('Empty or oversized JavaScript')
            text = data.decode('utf-8-sig')
            if text.lstrip().lower().startswith(('<html','<!doctype html')):
                raise ReviewRequired('HTML response instead of JavaScript')
            return data
        except Exception as exc:
            error = exc
    raise ReviewRequired('Upstream fetch failed: ' + str(error))


def parse(data: bytes, kind: str):
    text = data.decode('utf-8-sig')
    if '\x00' in text:
        raise ReviewRequired('Null byte in upstream source')
    opening = re.match(r'\s*/\*',text)
    if not opening or '*/' not in text:
        raise ReviewRequired('Missing embedded QX configuration comment')
    comment = text[opening.end():text.index('*/',opening.end())]
    project = PROJECTS[kind]
    rules, hosts, notes = [], [], []
    description = ''
    seen = set()
    for number, raw in enumerate(comment.splitlines(),1):
        line = raw.strip()
        if not line or re.fullmatch(r'\*+',line):
            continue
        if line.lower() in ('[rewrite_local]','[mitm]'):
            continue
        if line.startswith(('#','//')):
            description = '# ' + line[2:].strip() if line.startswith('//') else line
            notes.append(description)
            continue
        if re.fullmatch(r'https?://\S+',line):
            notes.append('# 上游说明链接：' + line)
            continue
        match = re.fullmatch(r'hostname\s*=\s*(.+)',line,re.I)
        if match:
            for host in match.group(1).split(','):
                host = host.strip()
                if host not in HOSTS:
                    raise ReviewRequired('New MITM hostname requires review')
                if host not in hosts:
                    hosts.append(host)
            continue
        disabled = line.startswith(';')
        if disabled:
            line = line[1:].strip()
        match = re.fullmatch(r'(\^\S+)\s+url\s+(\S+)(?:\s+(.+))?',line)
        if not match:
            if 'url ' not in line and not line.startswith(('^','[','hostname')):
                notes.append('# 上游说明：' + line)
                continue
            raise ReviewRequired(f'Unknown embedded configuration at line {number}')
        pattern,action,argument = match.groups()
        if action not in ACTIONS or pattern in seen or ',' in pattern:
            raise ReviewRequired('Unknown action, duplicate regex or separator')
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ReviewRequired('Invalid upstream URL pattern') from exc
        if action.startswith('script-') and argument != project['source']:
            raise ReviewRequired('Unreviewed script dependency')
        if action == 'jsonjq-response-body' and argument != "'.result.list=[]'":
            raise ReviewRequired('New jq operation requires equivalent offline tests')
        if action.startswith('reject-') and argument:
            raise ReviewRequired('Unexpected rejection options')
        seen.add(pattern)
        rules.append((pattern,action,argument,description,disabled))
        description = ''
    if not hosts or not rules:
        raise ReviewRequired('Missing embedded rules or MITM hosts')
    if kind == 'ads' and not any(action=='jsonjq-response-body' for _,action,_,_,_ in rules):
        raise ReviewRequired('Upstream removed jq rule; compatibility review required')
    if kind == 'unlock' and not all(any(action==want for _,action,_,_,_ in rules)
                                 for want in ('script-request-header','script-response-body')):
        raise ReviewRequired('Missing enhancement request/response rule')
    version = re.search(r'const\s+version\s*=\s*[\"\x27]([^\"\x27]+)',text)
    return hosts,rules,notes,(version.group(1) if version else '未标注')


JQ_SCRIPT = '''// Surge equivalent of QX jsonjq-response-body: .result.list=[]
// Preserve all unrelated fields; jq accepts null/missing intermediate objects.
(function () {
  try {
    var value = JSON.parse($response.body);
    if (value === null) value = {};
    if (typeof value !== "object" || Array.isArray(value)) throw new Error("invalid root");
    if (value.result == null) value.result = {};
    if (typeof value.result !== "object" || Array.isArray(value.result)) throw new Error("invalid result");
    value.result.list = [];
    $done({body: JSON.stringify(value)});
  } catch (_) { $done({}); }
})();
'''


def adapter_name(kind: str) -> str:
    return f'bdpan.{kind}.surge.js'


def build_adapter(source: bytes, kind: str) -> bytes:
    """Retain the entire original script in a result-type/exception adapter."""
    prefix = '''// Surge compatibility guard; original script is embedded unchanged.
// Sources and authorship: ddgksf2013. Generated by Polly-ai/Wynston.
(function (request, response, finish) {
  let result, calls = 0;
  function capture(value) { if (calls === 0) result = value; calls++; }
  try {
    (function ($request, $response, $done) {
'''
    suffix = '''
    })(request, response, capture);
  } catch (_) { finish({}); return; }
  const valid = calls === 1 && result && typeof result === "object" && !Array.isArray(result) &&
    (!Object.prototype.hasOwnProperty.call(result, "body") || typeof result.body === "string") &&
    (!Object.prototype.hasOwnProperty.call(result, "url") || typeof result.url === "string");
  finish(valid ? result : {});
})(typeof $request === "undefined" ? {} : $request,
   typeof $response === "undefined" ? undefined : $response, $done);
'''
    stamp = '// BEGIN original ' + PROJECTS[kind]['filename'] + ' SHA256 ' + digest(source) + '\n'
    return prefix.encode() + stamp.encode() + source + suffix.encode()


def render(source: bytes, kind: str) -> bytes:
    project = PROJECTS[kind]
    hosts,rules,notes,version = parse(source,kind)
    description = ('完整保留上游开屏、推广、首页信息流及任务页净化；原生Map Local空体/空对象与jq等价处理，每日更新。'
                   if kind == 'ads' else
                   '完整保留上游视频播放URL调整和会员界面标记功能；使用WebView原生URL接口，每日更新；不保证服务端会员权益。')
    lines = [
        '#!name = ' + project['name'], '#!desc = ' + description,
        '#!category = Polly-ai', '#!author = ddgksf2013',
        '# 上游：' + project['source'], '# 上游脚本版本：' + version,
        '# 原始文件 SHA256：' + digest(source),
        '# 由原JS头部内嵌QX配置完整转换；原JS按字节镜像，兼容脚本仅处理异常和返回类型。',
        '# 需启用重写、MITM并信任证书；Map Local需Surge iOS5.9.1+/Mac5.5.1+。',
        '# 两模块的membership/user游戏中心接口有重叠；同用时请让“功能增强”的响应规则优先。',
        '# 净化原脚本对正常gamecenter接口无操作，按原逻辑保留，不擅自启用其中潜藏会员分支。',
        '# 上游部分正则也覆盖其他baidu.com/zhangyuyidong.cn主机；MITM仅原列出的两主机，不擅自扩大。',
        '# 请求/响应规则保持上游范围；1MiB以上响应跳过脚本透传；无变化不提交，验证失败保留旧版。',
    ]
    if kind == 'unlock':
        lines.extend([
            '# 倍速请求把匹配的M3U8_HQ_1080调整为M3U8_AUTO_1080；仅修改客户端请求，不提供真实会员。',
            '# 会员接口按上游响应字段形状改写，可能整体替换会员展示对象；不代表真实配额、下载权限或到期日。',
            '# engine=webview用于原脚本的URL/searchParams和动态Function；无需修改系统JS全局。',
        ])
    scripts, mappings = [], []
    for pattern, action, argument, comment, disabled in rules:
        target = mappings if action.startswith('reject-') else scripts
        if comment:
            target.append(comment)
        identifier = 'bdpan_' + kind + '_' + hashlib.sha256(pattern.encode()).hexdigest()[:12]
        prefix = '# ' if disabled else ''
        if action in ('reject-200','reject-dict'):
            body = '' if action=='reject-200' else '{}'
            mime = 'text/plain' if action=='reject-200' else 'application/json'
            target.append(prefix + f'{pattern} data-type=text data="{body}" status-code=200 '
                          f'header="Content-Type:{mime}; charset=utf-8|Cache-Control:no-store"')
        else:
            if action == 'jsonjq-response-body':
                filename = 'bdpan.taskscore.js'
                options = 'requires-body=true, max-size=1048576, '
                script_type = 'http-response'
            else:
                filename = adapter_name(kind)
                script_type = 'http-request' if action=='script-request-header' else 'http-response'
                options = ('requires-body=false, ' if script_type=='http-request' else
                           'requires-body=true, max-size=1048576, ') + 'engine=webview, '
            target.append(prefix + f'{identifier} = type={script_type}, pattern={pattern}, {options}'
                          f'script-path={RAW}/{ASSETS.as_posix()}/{filename}, '
                          'script-update-interval=86400, timeout=15')
    for section, entries in (('Script',scripts),('Map Local',mappings)):
        if entries:
            lines.extend(['','['+section+']',*entries])
    lines.extend(['','[MITM]','hostname = %APPEND% ' + ', '.join(hosts),''])
    return '\n'.join(lines).encode('utf-8')


def validate(source: bytes, adapter: bytes, kind: str):
    tests = Path(__file__).with_name('test_bdpan_runtime.cjs')
    if not tests.is_file():
        raise ReviewRequired('Missing runtime regression tests')
    with tempfile.TemporaryDirectory(prefix='bdpan-validation-') as directory:
        path = Path(directory)
        original = path / PROJECTS[kind]['filename']
        compatible = path / adapter_name(kind)
        jq = path / 'bdpan.taskscore.js'
        original.write_bytes(source); compatible.write_bytes(adapter); jq.write_text(JQ_SCRIPT)
        for script in (original,compatible,jq):
            check = subprocess.run(['node','--check',str(script)],capture_output=True,text=True,timeout=20)
            if check.returncode:
                raise ReviewRequired('Invalid script syntax: ' + script.name)
        result = subprocess.run(['node',str(tests),kind,str(original),str(compatible),str(jq)],
                                capture_output=True,text=True,timeout=180)
        if result.returncode:
            raise ReviewRequired('Runtime regression failed: ' + result.stderr[-2500:])
        print(result.stdout.strip())


def prepare(source: bytes, kind: str):
    parse(source,kind)
    adapter = build_adapter(source,kind)
    validate(source,adapter,kind)
    files = {ASSETS / PROJECTS[kind]['filename']: source, ASSETS / adapter_name(kind): adapter,
             Path(PROJECTS[kind]['module']): render(source,kind)}
    if kind=='ads':
        files[ASSETS / 'bdpan.taskscore.js'] = JQ_SCRIPT.encode()
    return files


def write_bundle(root: Path, files: dict[Path,bytes]) -> list[str]:
    changed = {p:b for p,b in files.items() if not (root/p).exists() or (root/p).read_bytes()!=b}
    old = {p:(root/p).read_bytes() if (root/p).exists() else None for p in changed}
    staged,completed = {},[]
    try:
        for path,data in changed.items():
            final = root/path; final.parent.mkdir(parents=True,exist_ok=True)
            temp = final.with_name(final.name+'.sync-tmp'); temp.write_bytes(data); staged[path]=temp
        for path,temp in staged.items():
            temp.replace(root/path); completed.append(path)
    except BaseException:
        for path in reversed(completed):
            if old[path] is None:
                (root/path).unlink(missing_ok=True)
            else:
                (root/path).write_bytes(old[path])
        raise
    finally:
        for temp in staged.values():
            temp.unlink(missing_ok=True)
    return [str(path) for path in changed]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind',choices=PROJECTS,required=True)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args(argv)
    try:
        source=args.source.read_bytes() if args.source else download(PROJECTS[args.kind]['source'])
        files=prepare(source,args.kind)
        changed=write_bundle(args.root,files)
        print('sync_bdpan '+args.kind+': '+(', '.join(changed) if changed else 'no upstream changes'))
        return 0
    except (ReviewRequired,OSError,UnicodeError,subprocess.SubprocessError) as exc:
        print('sync_bdpan: '+str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())
