#!/usr/bin/env python3
"""Mirror ddgksf2013 RedditAds to a validated Surge module.

Run at repository root, or use --from-file/--script-dir for offline validation.
Only documented response-script syntax is accepted; new unknown directives
fail closed. Network, parse and JS validation failures occur before any writes.
Module metadata/category are fixed, and source hashes avoid no-op daily commits.
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
from urllib.parse import urlparse

UPSTREAM_URL = "https://raw.githubusercontent.com/ddgksf2013/Rewrite/refs/heads/master/AdBlock/RedditAds.conf"
MODULE_PATH = Path("Surge/Module/RedditAds.sgmodule")
ASSET_PATH = Path("Surge/JavaScript/Reddit")
RAW_ROOT = "https://raw.githubusercontent.com/Polly-ai/Wynston/main"
CATEGORY = "Polly-ai"
MAX_DOWNLOAD = 2_000_000


class SyncError(ValueError):
    pass


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def download(url: str) -> str:
    if urlparse(url).scheme != "https":
        raise SyncError("Only verified HTTPS sources are allowed")
    error = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Wynston-RedditAds-Sync/1.0", "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=45) as response:
                if response.status != 200:
                    raise SyncError(f"HTTP {response.status}")
                raw = response.read(MAX_DOWNLOAD + 1)
                if len(raw) > MAX_DOWNLOAD:
                    raise SyncError("Unexpected upstream size greater than 2 MB")
                text = raw.decode("utf-8-sig")
                if not text.strip() or text.lstrip().lower().startswith(("<!doctype html", "<html")):
                    raise SyncError("Empty or HTML source instead of config/JavaScript")
                return text
        except Exception as exc:
            error = exc
    raise SyncError(f"Download failed: {url}: {error}")


def logical_lines(text: str):
    pending = ""
    comment = ""
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("//", "#", ";")):
            if line.startswith("# >"):
                comment = line
            continue
        if pending:
            line = pending + " " + line
            pending = ""
        if ((line.startswith("hostname") and line.endswith(",")) or
                re.search(r"\burl\s+script-response-body$", line)):
            pending = line
            continue
        yield number, line, comment
        comment = ""
    if pending:
        raise SyncError("Incomplete upstream continuation line")


def parse(text: str) -> tuple[list[str], list[tuple[str, str, str]]]:
    hosts = []
    entries = []
    patterns = set()
    filenames = {}
    for number, line, comment in logical_lines(text):
        hostname = re.fullmatch(r"hostname\s*=\s*(.+)", line)
        if hostname:
            for host in hostname.group(1).split(","):
                host = host.strip()
                if not re.fullmatch(r"(?:\*\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", host):
                    raise SyncError(f"Line {number}: invalid MITM hostname: {host!r}")
                if not (host == "reddit.com" or host.endswith(".reddit.com")):
                    raise SyncError(f"Line {number}: new non-Reddit MITM host requires review")
                if host not in hosts:
                    hosts.append(host)
            continue
        match = re.fullmatch(r"(\^\S+)\s+url\s+script-response-body\s+(https://\S+)", line)
        if not match:
            raise SyncError(f"Line {number}: unsupported upstream directive: {line!r}")
        pattern, source = match.groups()
        if pattern in patterns:
            raise SyncError(f"Line {number}: duplicate URL pattern")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise SyncError(f"Line {number}: invalid URL regex") from exc
        if "," in pattern:
            raise SyncError(f"Line {number}: regex comma requires manual review")
        parsed = urlparse(source)
        filename = Path(parsed.path).name
        if (parsed.scheme != "https" or parsed.netloc != "raw.githubusercontent.com" or
                not parsed.path.startswith("/ddgksf2013/Scripts/") or parsed.query or parsed.fragment or
                not re.fullmatch(r"[A-Za-z0-9_-]+\.js", filename)):
            raise SyncError(f"Line {number}: unsafe or unexpected script source")
        if filename in filenames and filenames[filename] != source:
            raise SyncError(f"Line {number}: script filename collision")
        filenames[filename] = source
        patterns.add(pattern)
        entries.append((pattern, source, comment))
    if not hosts or not entries:
        raise SyncError("Missing MITM hostname or response script rules")
    return hosts, entries


def metadata(text: str, key: str) -> str:
    match = re.search(r"^\s*//\s*@" + re.escape(key) + r"\s+(.+?)\s*$", text, re.M)
    return match.group(1) if match else "未标注"


def adapter_name(filename: str) -> str:
    return Path(filename).stem + "-surge.js"


def build_adapter(source: str, filename: str) -> str:
    """Keep source untouched inside a synchronous, fail-open Surge bridge."""
    prefix = '''// Surge compatibility bridge for @ddgksf2013's Reddit enhancement.
// Original source is retained verbatim below; generated by sync_reddit_ads.py.
// Normalize operation-name headers locally and reject non-string body results.
(function (surgeRequest, surgeResponse, surgeDone) {
  let result, calls = 0;
  const captureDone = value => { if (calls === 0) result = value; calls++; };
  const headers = {};
  const original = (surgeRequest && surgeRequest.headers) || {};
  if (Array.isArray(original)) {
    for (const item of original) {
      if (!item || typeof item.field !== "string") continue;
      headers[item.field] = item.value;
      if (item.field.toLowerCase() === "x-apollo-operation-name")
        headers["X-APOLLO-OPERATION-NAME"] = item.value;
    }
  } else {
    for (const key of Object.keys(original)) {
      headers[key] = original[key];
      if (key.toLowerCase() === "x-apollo-operation-name")
        headers["X-APOLLO-OPERATION-NAME"] = original[key];
    }
  }
  const request = Object.assign({}, surgeRequest, {headers: headers});
  try {
    (function ($request, $response, $done) {
'''
    suffix = '''
    })(request, surgeResponse, captureDone);
  } catch (_) {
    surgeDone({});
    return;
  }
  const valid = calls === 1 && result && typeof result === "object" &&
    !Array.isArray(result) &&
    (!Object.prototype.hasOwnProperty.call(result, "body") || typeof result.body === "string");
  surgeDone(valid ? result : {});
})($request, $response, $done);
'''
    return prefix + "// BEGIN upstream " + filename + " SHA256 " + digest(source) + "\n" + source + suffix


def module_comment(comment: str) -> str:
    """Remove only the requested attribution token from rendered module comments."""
    return comment.replace("@ddgksf2013", "")


def render(text: str, sources: dict[str, str]) -> str:
    hosts, entries = parse(text)
    expected = {Path(urlparse(source).path).name for _, source, _ in entries}
    if expected != set(sources):
        raise SyncError("JavaScript snapshot does not match parsed upstream references")
    out = [
        "#!name = Reddit 增强",
        "#!desc = 去除 Reddit 信息流、帖子及社区广告；保留上游 NSFW 展示及本地 Premium 标记增强，每日同步。",
        f"#!category = {CATEGORY}",
        "#!author = ",
        f"# 上游来源：{UPSTREAM_URL}",
        f"# 上游配置版本：{metadata(text, 'Version')}；原作者更新：{metadata(text, 'UpdateTime')}",
        f"# 上游配置 SHA256：{digest(text)}",
        "# 转换与维护：Polly-ai/Wynston；上游 JavaScript 原样镜像，保留原作者署名。",
        "# Surge 桥接脚本统一 GraphQL 操作名请求头大小写；异常或非法正文类型安全透传。",
        "# 注意：Premium/Employee 等仅修改客户端响应标记，不授予真实订阅或服务端权益。",
        "# 需启用 MITM 并信任证书；请勿同时启用其他匹配该接口的响应体脚本。",
        "# 可与 Reddit 请求头自动翻译模块配合：两者分别处理请求和响应。",
        "# 响应体缓存上限 1 MiB；超限时 Surge 跳过脚本并透传响应。",
    ]
    for filename, source_text in sorted(sources.items()):
        out.append(f"# 上游 {filename} SHA256：{digest(source_text)}")
    out.extend(["", "[Script]"])
    for pattern, source, comment in entries:
        filename = Path(urlparse(source).path).name
        if comment:
            out.append(module_comment(comment))
        name = "reddit_ads_" + digest(pattern)[:12]
        out.append(f"{name} = type=http-response, pattern={pattern}, "
                   f"requires-body=true, max-size=1048576, "
                   f"script-path={RAW_ROOT}/{ASSET_PATH.as_posix()}/{adapter_name(filename)}, "
                   "script-update-interval=86400, timeout=10")
    out.extend(["", "[MITM]", "hostname = %APPEND% " + ", ".join(hosts), ""])
    return "\n".join(out)


def validate_js(sources: dict[str, str]):
    """No-network syntax and Surge-global VM checks before publishing scripts."""
    with tempfile.TemporaryDirectory(prefix="reddit-ads-sync-") as directory:
        for filename, text in sources.items():
            if not text.strip() or "$done" not in text:
                raise SyncError(f"Empty or invalid script: {filename}")
            path = Path(directory) / filename
            path.write_bytes(text.encode("utf-8"))
            check = subprocess.run(["node", "--check", str(path)],
                                   capture_output=True, text=True, timeout=15)
            if check.returncode:
                raise SyncError(f"Invalid JavaScript {filename}: {check.stderr[:1000]}")
        harness = r'''
const fs = require('fs');
const vm = require('vm');
const dir = process.argv[1];
function run(name, body, headers = {}) {
  let result, calls = 0;
  const sandbox = {$request: {url: 'https://gql-fed.reddit.com/', method: 'POST', headers},
    $response: {status: 200, headers: {'Content-Type': 'application/json'}, body},
    $done: value => {result = value; calls++;}, console: {log() {}, warn() {}, error() {}}};
  vm.runInNewContext(fs.readFileSync(dir + '/' + name, 'utf8'), sandbox,
    {timeout: 2000, contextCodeGeneration: {strings: false, wasm: false}});
  if (calls !== 1 || !result || typeof result !== 'object')
    throw new Error(name + ': expected exactly one $done object');
  if (result.body !== undefined && typeof result.body !== 'string')
    throw new Error(name + ': incompatible non-string response body');
  return result;
}
for (const name of fs.readdirSync(dir)) {
  if (!name.endsWith('.js')) continue;
  const input = JSON.stringify({data: {}, unrelated: {keep: 'unchanged'}});
  const result = run(name, input);
  if (result.body !== undefined && JSON.parse(result.body).unrelated.keep !== 'unchanged')
    throw new Error(name + ': unrelated fields were not preserved');
}
if (fs.existsSync(dir + '/reddit.js')) {
  const input = JSON.stringify({data: {feed: {elements: {edges: [
    {node: {__typename: 'Post', id: 'normal', title: 'Keep this post'}},
    {node: {__typename: 'AdPost', id: 'ad'}},
    {node: {__typename: 'Post', adPayload: {id: 'ad-payload'}}}
  ]}}}, unrelated: {keep: 'unchanged'},
    flags: {isObfuscated: true, obfuscatedPath: 'hidden', isNsfw: true,
      isPremiumMember: false, isEmployee: false}});
  const result = run('reddit.js', input);
  const parsed = JSON.parse(result.body);
  if (parsed.unrelated.keep !== 'unchanged' || parsed.flags.isObfuscated !== false ||
      parsed.flags.obfuscatedPath !== null || parsed.flags.isNsfw !== false ||
      parsed.flags.isPremiumMember !== true || parsed.data.feed.elements.edges.length !== 1 ||
      parsed.data.feed.elements.edges[0].node.id !== 'normal')
    throw new Error('reddit.js: current enhancement fixture failed');
  for (const invalid of ['', '<html>upstream error</html>', '{invalid']) {
    const pass = run('reddit.js', invalid);
    if (Object.keys(pass).length) throw new Error('reddit.js: invalid JSON must pass through');
  }
}
if (fs.existsSync(dir + '/reddit-surge.js')) {
  for (const key of ['X-APOLLO-OPERATION-NAME', 'x-apollo-operation-name', 'X-Apollo-Operation-Name']) {
    const reply = run('reddit-surge.js', 'not JSON', {[key]: 'FetchAds'});
    if (reply.body !== '{}') throw new Error('Surge adapter did not normalize header ' + key);
  }
  const inputs = [
    JSON.stringify({data: {feed: {elements: {edges: [null]}}}}),
    '', undefined, 'null', '<html>error</html>'
  ];
  for (const bad of inputs) {
    const reply = run('reddit-surge.js', bad);
    if (Object.keys(reply).length) throw new Error('Surge adapter failed to pass through malformed response');
  }
  const normal = JSON.stringify({data: {feed: {elements: {edges: [
    {node: {__typename: 'Post', id: 'keep'}}, {node: {__typename: 'AdPost'}},
    {node: {adPayload: {}}}, {node: {cells: [{__typename: 'AdMetadataCell'}]}}
  ]}}}});
  const reply = JSON.parse(run('reddit-surge.js', normal).body);
  if (reply.data.feed.elements.edges.length !== 1 || reply.data.feed.elements.edges[0].node.id !== 'keep')
    throw new Error('Surge adapter changed the upstream advertisement filter');
}
'''
        try:
            check = subprocess.run(["node", "-e", harness, directory],
                                   capture_output=True, text=True, timeout=30)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise SyncError("Node.js is required for bounded script validation") from exc
        if check.returncode:
            raise SyncError(f"Surge VM smoke test failed: {check.stderr[:1500]}")


def prepare(text: str, script_dir: Path | None = None) -> dict[Path, str]:
    _, entries = parse(text)
    sources = {}
    for _, url, _ in entries:
        filename = Path(urlparse(url).path).name
        if filename not in sources:
            sources[filename] = (script_dir.joinpath(filename).read_bytes().decode("utf-8-sig")
                                 if script_dir else download(url))
    adapters = {adapter_name(name): build_adapter(data, name) for name, data in sources.items()}
    if set(sources) & set(adapters):
        raise SyncError("Upstream filename conflicts with generated Surge adapter")
    validate_js({**sources, **adapters})
    module = render(text, sources)
    return {**{ASSET_PATH / name: data for name, data in {**sources, **adapters}.items()}, MODULE_PATH: module}


def write_changed(path: Path, text: str) -> bool:
    data = text.encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".sync-tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-file", type=Path, help="Use local upstream config")
    parser.add_argument("--script-dir", type=Path, help="Use local upstream JavaScript snapshots")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    args = parser.parse_args(argv)
    try:
        text = (args.from_file.read_bytes().decode("utf-8-sig")
                if args.from_file else download(UPSTREAM_URL))
        files = prepare(text, args.script_dir)
        changed = [str(path) for path, content in files.items()
                   if write_changed(args.root / path, content)]
        print("sync_reddit_ads: " + ("updated " + ", ".join(changed)
                                    if changed else "no upstream changes"))
        return 0
    except (SyncError, OSError, UnicodeError, subprocess.SubprocessError) as exc:
        print(f"sync_reddit_ads: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
