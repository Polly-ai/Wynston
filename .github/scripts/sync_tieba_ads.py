#!/usr/bin/env python3
"""Convert the complete TieBaAds QX configuration; unknown rules fail before writes."""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_URL = "https://raw.githubusercontent.com/ddgksf2013/Rewrite/refs/heads/master/AdBlock/TieBaAds.conf"
RAW = "https://raw.githubusercontent.com/Polly-ai/Wynston/main/"
ASSETS = Path("Surge/JavaScript/TieBa")
MODULE = Path("Surge/Module/TieBaAds.sgmodule")
EXPRESSIONS = {
    ".data.discover_list = []": 'if (o === null) o = {}; if (o.data == null) o.data = {}; if (typeof o.data !== "object" || Array.isArray(o.data)) throw Error("data type"); o.data.discover_list = [];',
    "del(.game_center, .tools, .vip_banner, .task_list)": 'for (const k of ["game_center", "tools", "vip_banner", "task_list"]) if (o != null) delete o[k];',
    'del(.duxiaoman, .namoaixud, .namoaixud_entry, .recom_naws_list, .duxiaoman_entry, .vip_banner) | .zone_info |= map(select(.type == "common_func" or .type == "auxiliary_func"))': 'for (const k of ["duxiaoman", "namoaixud", "namoaixud_entry", "recom_naws_list", "duxiaoman_entry", "vip_banner"]) delete o[k]; if (!Array.isArray(o.zone_info) && (o.zone_info === null || typeof o.zone_info !== "object")) throw Error("zone_info type"); o.zone_info = Object.values(o.zone_info).filter(x => { if (x === null) return false; if (typeof x !== "object" || Array.isArray(x)) throw Error("zone item type"); return x.type === "common_func" || x.type === "auxiliary_func"; });',
    ".hot_search = []": 'if (o === null) o = {}; o.hot_search = [];',
    "del(.data)": 'if (o != null) delete o.data;',
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def download(url):
    error = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Wynston-TieBa-Sync", "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=45) as r:
                data = r.read(5_000_001)
                if r.status != 200 or not data.strip() or len(data) > 5_000_000 or data.lstrip().lower().startswith((b"<html", b"<!doctype")):
                    raise ValueError("Invalid source response")
                return data
        except Exception as exc:
            error = exc
    raise ValueError(f"Download failed: {url}: {error}")

def pinned(url):
    m = re.fullmatch(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/(?:refs/heads/)?([^/]+)/(.+)", url)
    if not m:
        raise ValueError("Unsupported source URL")
    owner, repo, ref, path = m.groups()
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        ref = json.loads(download(f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}"))["sha"]
    return download(f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}")

def parse(data):
    text = data.decode("utf-8-sig")
    hosts, rules, ips, seen = [], [], [], set()
    comment = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("//", "#", ";")):
            if line.startswith("# >"):
                comment = line.replace("@@ddgksf2013", "").replace("@ddgksf2013", "")
            continue
        if line.startswith("hostname"):
            m = re.fullmatch(r"hostname\s*=\s*(.+)", line)
            if not m: raise ValueError("Invalid hostname")
            hosts = [h.strip() for h in m[1].split(",")]
            if not all(re.fullmatch(r"[A-Za-z0-9.-]+\.baidu\.com", h) for h in hosts):
                raise ValueError("Unexpected MITM host")
            continue
        if re.fullmatch(r"IP-CIDR,(?:[0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]+,reject", line):
            ips.append(line.rsplit(",", 1)[0] + ",REJECT")
            continue
        m = re.fullmatch(r"(\^\S+)\s+url\s+(jsonjq-response-body|reject-200|script-response-body)(?:\s+(.+))?", line)
        if not m: raise ValueError("Unknown directive: " + line)
        pattern, kind, arg = m.groups()
        re.compile(pattern)
        if pattern in seen or "," in pattern: raise ValueError("Duplicate/unsupported pattern")
        seen.add(pattern)
        if kind == "jsonjq-response-body":
            if not arg or arg[0] != "'" or arg[-1] != "'" or arg[1:-1] not in EXPRESSIONS:
                raise ValueError("Unsupported jq expression")
            arg = arg[1:-1]
        elif kind == "script-response-body":
            if arg != "https://raw.githubusercontent.com/app2smile/rules/master/js/tieba-proto.js":
                raise ValueError("New script dependency requires review")
        elif arg:
            raise ValueError("Unexpected reject arguments")
        rules.append((pattern, kind, arg, comment))
        comment = ""
    if not hosts or not rules or not any(r[1] == "script-response-body" for r in rules):
        raise ValueError("Incomplete config")
    return hosts, rules, ips

def render(config, proto):
    hosts, rules, ips = parse(config)
    cases = []
    for pattern, kind, expr, _ in rules:
        if kind == "jsonjq-response-body":
            cases.append("if (new RegExp(" + json.dumps(pattern) + ").test($request.url)) { " + EXPRESSIONS[expr] + " matched = true; }")
    json_js = ("// Generated jq-equivalent transformations from TieBaAds.conf.\n"
        "try { let o = JSON.parse($response.body); let matched = false;\n"
        "if (o !== null && (typeof o !== 'object' || Array.isArray(o))) throw Error('root type');\n"
        + "\n".join(cases) + "\n$done(matched ? {body: JSON.stringify(o)} : {});\n} catch (_) { $done({}); }\n").encode()
    text = config.decode("utf-8-sig")
    version = re.search(r"@Version\s+([^\r\n]+)", text)
    lines = ["#!name = 百度贴吧净化", "#!desc = 净化贴吧首页搜索、侧边栏、我的页面、进吧推荐与信息流广告；保留上游 Protobuf 处理。", "#!category = Polly-ai", "#!author = app2smile, ddgksf2013", "# 上游：" + CONFIG_URL, "# 上游版本：" + (version[1] if version else "未标注"), "# 配置 SHA256：" + sha(config), "# tieba-proto.js SHA256：" + sha(proto), "# JSON 规则异常时透传；Protobuf 脚本原样镜像。需启用 MITM 并信任证书。", "", "[Rule]", *ips, "", "[Map Local]"]
    for pattern, kind, _, comment in rules:
        if kind == "reject-200":
            lines.extend([comment, pattern + ' data-type=text data="" status-code=200'])
    lines.extend(["", "[Script]"])
    for pattern, kind, _, comment in rules:
        if kind == "reject-200": continue
        filename = "tieba-json.js" if kind == "jsonjq-response-body" else "tieba-proto.js"
        binary = "binary-body-mode=true, max-size=-1, " if kind == "script-response-body" else "max-size=1048576, "
        lines.extend([comment, "tieba_" + sha(pattern.encode())[:12] + " = type=http-response, pattern=" + pattern + ", requires-body=true, " + binary + "script-path=" + RAW + str(ASSETS / filename) + ", script-update-interval=86400, timeout=60"])
    lines.extend(["", "[MITM]", "hostname = %APPEND% " + ", ".join(hosts), ""])
    return {MODULE: "\n".join(lines).encode(), ASSETS / "tieba-json.js": json_js, ASSETS / "tieba-proto.js": proto, ASSETS / "TieBaAds.conf": config}

def prepare(config, proto):
    files = render(config, proto)
    with tempfile.TemporaryDirectory() as tmp:
        for path, data in files.items():
            if path.suffix == ".js":
                target = Path(tmp) / path.name
                target.write_bytes(data)
                subprocess.run(["node", "--check", str(target)], check=True, capture_output=True, timeout=30)
    return files

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", type=Path)
    args = ap.parse_args()
    config = (args.offline / "TieBaAds.conf").read_bytes() if args.offline else pinned(CONFIG_URL)
    _, rules, _ = parse(config)
    url = next(r[2] for r in rules if r[1] == "script-response-body")
    proto = (args.offline / "tieba-proto.js").read_bytes() if args.offline else pinned(url)
    files = prepare(config, proto)
    changed = []
    for path, data in files.items():
        target = ROOT / path
        if target.exists() and target.read_bytes() == data: continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        changed.append(str(path))
    print("Updated: " + ", ".join(changed) if changed else "No upstream changes")

if __name__ == "__main__":
    main()
