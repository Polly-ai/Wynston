#!/usr/bin/env python3
"""把上游 https://raw.githubusercontent.com/ddgksf2013/Scripts/master/12306.js 转换为 Surge 模块，并每日同步。

上游文档本身就是 js 文件：它的头部注释块里写着 [rewrite_local] 规则与 [mitm]
主机名，正文是脚本代码。同步时解析注释块里的规则生成模块，并把整份 js
原样镜像到自托管地址。

用法（仓库工作流里不带参数跑，默认抓上游、写到仓库路径）：
    python3 .github/scripts/sync_12306.py
本地测试：
    python3 .github/scripts/sync_12306.py --from-file /tmp/12306.js --output /tmp/out.sgmodule

转换规则：
  - 注释块里的 ^... url script-analyze-echo-response <js> -> [Script] 脚本名按规则生成：
    单个脚本不加数字后缀（如 12306），多个脚本再加 _1、_2 编号；
    analyze-echo-response 读 $request.body，对应 Surge type=http-request、
    requires-body=true
  - 注释块里的 hostname = ... -> [MITM] hostname = %APPEND% ...
  - '# > ...' 注释行去掉末尾 @ddgksf2013 后保留在其后那条规则上方；其余注释行跳过。
  - 脚本一律指向自托管地址（SELF_HOSTED_JS_URL），不直接引用上游 js；
    同步时同时抓上游 js 更新自托管镜像文件。
  - 作者注释里的“请在本地添加分流 host, ad.12306.cn, direct”是使用说明，
    不是文件里的规则，不转为 [Rule]，只作为注释保留在模块里。

固定不变的头部（同步时不被上游覆盖）：
  - #!name、#!desc、#!category、#!author

上游出现无法识别的行时直接失败、绝不静默丢规则；上游没变时不写文件、不产生提交。
"""

import argparse
import re
import sys
import urllib.request

UPSTREAM_URL = "https://raw.githubusercontent.com/ddgksf2013/Scripts/master/12306.js"
DEFAULT_OUTPUT = "Surge/Module/12306.sgmodule"
MODULE_NAME = "12306 净化"
MODULE_DESC = "全面去广告"
MODULE_CATEGORY = "Polly-ai"
MODULE_AUTHOR = "ddgksf2013"
SCRIPT_PREFIX = "12306"
SELF_HOSTED_JS_URL = "https://raw.githubusercontent.com/Polly-ai/Wynston/main/Surge/JavaScript/12306/12306.js"
ASSET_PATH = "Surge/JavaScript/12306/12306.js"
EXTRA_NOTES = ['# 注意：作者说明请在本地添加分流 host, ad.12306.cn, direct（原文注释，非模块规则，未转为 [Rule]）。']

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
    """解析上游 js 头部注释块里的 [rewrite_local] 与 [mitm]，返回规则与镜像 js 文本。"""
    # 1. 取出头部注释块（第一个 /* ... */），其余正文是脚本代码，不当规则解析。
    m = re.search(r"/\*.*?\*/", text, re.S)
    if not m:
        fail("上游 js 缺少头部注释块（/* ... */），结构可能已变，已中止")
    header = m.group(0)
    code = text[m.end():]

    # 脚本接口锚点：读 $request.body 做分流、调用 $done 返回。缺了说明脚本接口已变。
    if "$request.body" not in code:
        fail("上游 js 不再读 $request.body，脚本接口可能已变，已中止")
    if "$done" not in code:
        fail("上游 js 不再调用 $done，脚本接口可能已变，已中止")

    rules, rewrites, map_locals, body_rewrites, scripts, mitm = [], [], [], [], [], []
    upstream_js_urls = []
    pending_comment = None
    script_n = 0
    section = None
    for raw in header.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r"[/*]+", line):
            continue
        if line.startswith(">"):
            continue
        if line.startswith("#"):
            if line.startswith("# >"):
                pending_comment = clean_comment(line)
            continue
        if line.startswith("//"):
            continue
        if line.startswith("#!"):
            continue
        if line.startswith("["):
            if line == "[rewrite_local]":
                section = "rewrite_local"
                continue
            if line == "[mitm]":
                section = "mitm"
                continue
            fail(f"注释块里无法识别的段落：{raw!r}")
        if section == "mitm" and line.startswith("hostname"):
            m2 = re.fullmatch(r"hostname\s*=\s*(.+)", line)
            if not m2:
                fail(f"无法识别的 hostname 行：{raw!r}")
            mitm = [h.strip() for h in m2.group(1).split(",") if h.strip()]
            if not mitm:
                fail("hostname 行为空")
            continue
        if section == "rewrite_local" and line.startswith("^"):
            m2 = re.fullmatch(r"(\^\S+)\s+url\s+(\S+)(?:\s+(.*))?", line)
            if not m2:
                fail(f"无法识别的 url 规则：{raw!r}")
            pattern, action, rest = m2.group(1), m2.group(2), (m2.group(3) or "").strip()
            if action != "script-analyze-echo-response":
                fail(f"不支持的 url 动作 {action!r}（期望 script-analyze-echo-response）：{raw!r}")
            if not re.fullmatch(r"https?://\S+", rest or ""):
                fail(f"脚本规则缺少有效 js 地址：{raw!r}")
            if not rest.endswith("/12306.js"):
                fail(f"脚本地址不是 12306.js：{rest!r}")
            script_n += 1
            if pending_comment:
                scripts.append(pending_comment)
                pending_comment = None
            if upstream_js_urls and rest != upstream_js_urls[0]:
                fail(f"脚本地址不一致（期望唯一 js）：{rest!r}")
            upstream_js_urls.append(rest)
            scripts.append(f"{SCRIPT_PREFIX}_{script_n} = type=http-request, pattern={pattern}, requires-body=true, script-path={SELF_HOSTED_JS_URL}")
            continue
        fail(f"注释块里无法识别的行，已中止：{raw!r}")
    # 命名规则：单个脚本不加数字后缀，多个脚本再加 _1、_2 编号。
    # 上面先按 _1、_2 生成，解析完再按总数决定，单个脚本去掉 _1。
    _script_entries = [j for j, e in enumerate(scripts)
                       if re.match(rf"{re.escape(SCRIPT_PREFIX)}_\d+ =", e)]
    if len(_script_entries) == 1:
        _j = _script_entries[0]
        scripts[_j] = re.sub(rf"^{re.escape(SCRIPT_PREFIX)}_\d+ =", f"{SCRIPT_PREFIX} =", scripts[_j], count=1)
    if not scripts:
        fail("注释块里没有找到脚本规则，上游结构可能已变，已中止")
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

    # 自托管镜像同步：上游文档本身就是 js，全文原样镜像；即使模块文本不变，
    # 上游 js 变了也要更新镜像文件。
    if args.js_from_file:
        js_text = open(args.js_from_file, encoding="utf-8").read()
    else:
        js_text = text
    js_changed = False
    try:
        old_js = open(ASSET_PATH, encoding="utf-8").read()
    except FileNotFoundError:
        old_js = None
    if old_js != js_text:
        with open(ASSET_PATH, "w", encoding="utf-8") as f:
            f.write(js_text)
        js_changed = True
        print(f"sync_{SCRIPT_PREFIX}: 已更新镜像 {ASSET_PATH}（上游 {UPSTREAM_URL}）")
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
