#!/usr/bin/env python3
"""把上游 https://raw.githubusercontent.com/ddgksf2013/Rewrite/master/AdBlock/Ximalaya.conf 转换为 Surge 模块，并每日同步。

用法（仓库工作流里不带参数跑，默认抓上游、写到仓库路径）：
    python3 .github/scripts/sync_ximalaya.py
本地测试：
    python3 .github/scripts/sync_ximalaya.py --from-file /tmp/upstream --output /tmp/out.sgmodule

转换规则：
  - host/host-suffix/host-keyword/host-wildcard/ip-cidr/ip6-cidr, X, reject|direct
    -> [Rule] 对应类型，IP 规则加 no-resolve
  - ^... url reject -> [URL Rewrite] pattern _ reject
  - ^... url reject-dict / reject-200 -> [Map Local] 返回 {}（Surge [URL Rewrite]
    没有 reject-dict/reject-200，直接照搬会使规则不生效）
  - ^... url jsonjq-response-body 'jq' -> [Body Rewrite] http-response-jq
  - ^... url script-request/response-body <js> -> [Script] 脚本名按规则生成：
    单个脚本不加数字后缀，多个脚本再加 _1、_2 编号（如 ximalaya_1～5）；
    response-body 的 requires-body=true，request 脚本为 false
  - hostname = ... -> [MITM] hostname = %APPEND% ...
  - '# > ...' 注释行去掉末尾 @ddgksf2013 后保留在其后那条规则上方；其余注释行跳过。
  - 脚本一律指向自托管地址（SELF_HOSTED_JS_URL），不直接引用上游 js；
    同步时同时抓上游 js 更新自托管镜像文件。

固定不变的头部（同步时不被上游覆盖）：
  - #!name、#!desc、#!category、#!author

上游出现无法识别的行时直接失败、绝不静默丢规则；上游没变时不写文件、不产生提交。
"""

import argparse
import re
import sys
import urllib.request

UPSTREAM_URL = "https://raw.githubusercontent.com/ddgksf2013/Rewrite/master/AdBlock/Ximalaya.conf"
DEFAULT_OUTPUT = "Surge/Module/ximalaya.sgmodule"
MODULE_NAME = "喜马拉雅净化"
MODULE_DESC = '去除喜马拉雅 App 广告、推广弹窗与多余入口。'
MODULE_CATEGORY = "Polly-ai"
MODULE_AUTHOR = "ddgksf2013"
SCRIPT_PREFIX = "ximalaya"
SELF_HOSTED_JS_URL = "https://raw.githubusercontent.com/Polly-ai/Wynston/main/Surge/JavaScript/Ximalaya/ximalaya_json.js"
ASSET_PATH = "Surge/JavaScript/Ximalaya/ximalaya_json.js"
UPSTREAM_JS_URL = "https://raw.githubusercontent.com/ddgksf2013/Scripts/refs/heads/master/ximalaya_json.js"
EXTRA_NOTES = ['# 注意：上游 MITM 主机名含通配符 *.xima*.*、*.xmcdn.*，原文原样保留；Surge 对这种中间带 * 的主机名匹配方式未经真机验证。']

HOST_RULES = {"host": "DOMAIN", "host-suffix": "DOMAIN-SUFFIX",
              "host-keyword": "DOMAIN-KEYWORD", "host-wildcard": "DOMAIN-WILDCARD",
              "ip-cidr": "IP-CIDR", "ip6-cidr": "IP-CIDR6"}
MAP_LOCAL_SUFFIX = ' data-type=text data="{}" status-code=200 header="Content-Type:application/json"'


def fail(msg):
    print(f"sync_{SCRIPT_PREFIX}: error: {msg}", file=sys.stderr)
    sys.exit(2)


def clean_comment(line):
    """去掉 '# > ...' 注释行末尾的 @ddgksf2013，只去后缀，其余原样保留。"""
    return re.sub(r"@ddgksf2013\s*$", "", line)


def fetch_text(url, from_file):
    if from_file:
        with open(from_file, "r", encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": "surge-sync/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                fail(f"上游返回 HTTP {resp.status}：{url}")
            return resp.read().decode("utf-8")
    except SystemExit:
        raise
    except Exception as e:
        fail(f"抓取上游失败：{e}")


def parse(text):
    rules, rewrites, map_locals, body_rewrites, scripts, mitm = [], [], [], [], [], []
    upstream_js_urls = []
    pending_comment = None
    script_n = 0
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1
        if not line:
            continue
        if line.startswith("#"):
            if line.startswith("# >"):
                pending_comment = clean_comment(line)
            continue
        if line.startswith("//"):
            continue
        if line.startswith("#!"):
            continue
        if line.startswith("hostname"):
            m = re.fullmatch(r"hostname\s*=\s*(.+)", line)
            if not m:
                fail(f"无法识别的 hostname 行：{raw!r}")
            mitm = [h.strip() for h in m.group(1).split(",") if h.strip()]
            if not mitm:
                fail("hostname 行为空")
            continue
        m = re.fullmatch(r"(host|host-suffix|host-keyword|host-wildcard|ip-cidr|ip6-cidr)\s*,\s*([^,]+?)\s*,\s*(reject|direct)\s*", line, re.I)
        if m:
            typ, val, act = m.group(1).lower(), m.group(2).strip(), m.group(3).upper()
            entry = f"{HOST_RULES[typ]},{val},{act}"
            if HOST_RULES[typ] in ("IP-CIDR", "IP-CIDR6"):
                entry += ",no-resolve"
            if pending_comment:
                rules.append(pending_comment)
                pending_comment = None
            rules.append(entry)
            continue
        if line.startswith("^"):
            full = line
            if re.search(r"url\s+(script-(request|response)-body|script-request-header)\s*$", full):
                if i < len(lines):
                    full = full + " " + lines[i].strip()
                    i += 1
            m = re.fullmatch(r"(\^\S+)\s+url\s+(\S+)(?:\s+(.*))?", full)
            if not m:
                fail(f"无法识别的 url 规则：{raw!r}")
            pattern, action, rest = m.group(1), m.group(2), (m.group(3) or "").strip()
            if action == "reject":
                if rest:
                    fail(f"reject 带多余参数：{raw!r}")
                if pending_comment:
                    rewrites.append(pending_comment)
                    pending_comment = None
                rewrites.append(f"{pattern} _ reject")
            elif action in ("reject-dict", "reject-200"):
                if rest:
                    fail(f"{action} 带多余参数：{raw!r}")
                if pending_comment:
                    map_locals.append(pending_comment)
                    pending_comment = None
                map_locals.append(f"{pattern}{MAP_LOCAL_SUFFIX}")
            elif action == "jsonjq-response-body":
                if not (rest.startswith("'") and rest.endswith("'") and len(rest) >= 2):
                    fail(f"jsonjq 未用单引号包裹：{raw!r}")
                jq = rest[1:-1]
                if "'" in jq:
                    fail(f"jsonjq 内含单引号，无法安全转写：{raw!r}")
                if pending_comment:
                    body_rewrites.append(pending_comment)
                    pending_comment = None
                body_rewrites.append(f"http-response-jq {pattern} '{jq}'")
            elif action in ("script-response-body", "script-request-body", "script-request-header"):
                if not re.fullmatch(r"https?://\S+", rest or ""):
                    fail(f"脚本规则缺少有效 js 地址：{raw!r}")
                script_n += 1
                kind = "http-request" if action.startswith("script-request") else "http-response"
                rb = "true" if action == "script-response-body" else "false"
                if pending_comment:
                    scripts.append(pending_comment)
                    pending_comment = None
                if SELF_HOSTED_JS_URL is None:
                    fail(f"上游新增脚本规则，需人工确认自托管地址：{raw!r}")
                if upstream_js_urls and rest != upstream_js_urls[0]:
                    fail(f"脚本地址不一致（期望唯一 js）：{rest!r}")
                upstream_js_urls.append(rest)
                scripts.append(f"{SCRIPT_PREFIX}_{script_n} = type={kind}, pattern={pattern}, requires-body={rb}, script-path={SELF_HOSTED_JS_URL}")
            else:
                fail(f"不支持的 url 动作 {action!r}：{raw!r}")
            continue
        fail(f"无法识别的上游行，已中止：{raw!r}")
    # 命名规则：单个脚本不加数字后缀，多个脚本再加 _1、_2 编号。
    # parse() 里先按 _1、_2 生成，解析完再按总数决定，单个脚本去掉 _1。
    _script_entries = [j for j, e in enumerate(scripts)
                       if re.match(rf"{re.escape(SCRIPT_PREFIX)}_\d+ =", e)]
    if len(_script_entries) == 1:
        _j = _script_entries[0]
        scripts[_j] = re.sub(rf"^{re.escape(SCRIPT_PREFIX)}_\d+ =", f"{SCRIPT_PREFIX} =", scripts[_j], count=1)
    return {"rules": rules, "rewrites": rewrites, "map_locals": map_locals,
            "body_rewrites": body_rewrites, "scripts": scripts, "mitm": mitm,
            "upstream_js_url": upstream_js_urls[0] if upstream_js_urls else None}


def render(parts):
    out = [f"#!name = {MODULE_NAME}", f"#!desc = {MODULE_DESC}",
           f"#!category = {MODULE_CATEGORY}", f"#!author = {MODULE_AUTHOR}", "",
           f"# 转换自 QX 格式，上游：{UPSTREAM_URL}"]
    if EXTRA_NOTES:
        out += EXTRA_NOTES
    for section, entries in (("[Rule]", parts["rules"]), ("[URL Rewrite]", parts["rewrites"]),
                             ("[Map Local]", parts["map_locals"]), ("[Body Rewrite]", parts["body_rewrites"]),
                             ("[Script]", parts["scripts"])):
        if entries:
            out += ["", f"{section}", *entries]
    if parts["mitm"]:
        out += ["", "[MITM]", "hostname = %APPEND% " + ", ".join(parts["mitm"])]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-file")
    ap.add_argument("--js-from-file", help="本地测试用：以上游 js 文件代替网络抓取")
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    text = fetch_text(UPSTREAM_URL, args.from_file)
    parts = parse(text)

    # 自托管镜像同步：即使模块文本不变，上游 js 变了也要更新镜像文件。
    upstream_js = parts.get("upstream_js_url")
    js_changed = False
    if upstream_js:
        if args.js_from_file:
            js_text = open(args.js_from_file, encoding="utf-8").read()
        elif args.from_file:
            js_text = None  # 本地 --from-file 测试不抓上游 js
        else:
            js_text = fetch_text(upstream_js, None)
        if js_text is not None:
            try:
                old_js = open(ASSET_PATH, encoding="utf-8").read()
            except FileNotFoundError:
                old_js = None
            if old_js != js_text:
                with open(ASSET_PATH, "w", encoding="utf-8") as f:
                    f.write(js_text)
                js_changed = True
                print(f"sync_{SCRIPT_PREFIX}: 已更新镜像 {ASSET_PATH}（上游 {upstream_js}）")
    if not parts["mitm"]:
        fail("转换后无 MITM 主机名，上游结构可能已变，已中止")
    if not (parts["rules"] or parts["rewrites"] or parts["map_locals"]
            or parts["body_rewrites"] or parts["scripts"]):
        fail("转换后无任何规则，上游结构可能已变，已中止")
    new_text = render(parts)
    try:
        old_text = open(args.output, encoding="utf-8").read()
    except FileNotFoundError:
        old_text = None
    if old_text == new_text and not js_changed:
        print(f"sync_{SCRIPT_PREFIX}: 规则无变化，跳过写入（避免无意义提交）")
        return 0
    if old_text == new_text and js_changed:
        print(f"sync_{SCRIPT_PREFIX}: 模块无变化，镜像已更新")
        return 0
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(new_text)
    n = lambda e: sum(1 for x in e if not x.startswith("#"))
    print(f"sync_{SCRIPT_PREFIX}: 已写入 {args.output}（Rule {n(parts['rules'])}、"
          f"URL Rewrite {n(parts['rewrites'])}、Map Local {n(parts['map_locals'])}、"
          f"Body Rewrite {n(parts['body_rewrites'])}、Script {n(parts['scripts'])}、"
          f"MITM {len(parts['mitm'])}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
