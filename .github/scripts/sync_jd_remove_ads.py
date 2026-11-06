#!/usr/bin/env python3
"""把上游 Loon 插件 https://raw.githubusercontent.com/zbsdsb/loon-adblock-plugins/main/JD_remove_ads_v2.lpx 转换为 Surge 模块，并每日同步。

上游是 Loon .lpx 插件：头部 #! 注释、[Rule]、[Script]、[MitM] 四部分。
同步时重新解析上游生成模块，并把上游 js 原样镜像到自托管地址。

用法（仓库工作流里不带参数跑，默认抓上游、写到仓库路径）：
    python3 .github/scripts/sync_jd_remove_ads.py
本地测试：
    python3 .github/scripts/sync_jd_remove_ads.py --from-file /tmp/JD_remove_ads_v2.lpx --js-from-file /tmp/JD_remove_ads_v2.js --output /tmp/out.sgmodule

转换规则：
  - #!desc、#!author、#!icon、#!openUrl 随上游原文，不改写。
  - #!name 固定为“京东净化”（用户指定，不跟上游的“京东去广告 v2 (适配 15.9.50+)”）。
  - #!category 固定为 Polly-ai（用户指定）。
  - [Rule] 行原样保留（Surge 同样支持 URL-REGEX）。
  - [Script] 的 `http-response <pattern> script-path=<url>, requires-body=true, tag=<tag>`
    转为 Surge 格式 `<tag> = type=http-response, pattern=<pattern>, requires-body=true, script-path=<自托管 js>`。
  - [MitM] 的 hostname 转为 [MITM] 的 `hostname = %APPEND% ...`。
  - 脚本一律指向自托管地址（SELF_HOSTED_JS_URL），不直接引用上游 js；
    同步时同时抓上游 js 更新自托管镜像文件。

固定不变的头部（同步时不被上游覆盖）：
  - #!name、#!category

上游出现无法识别的行时直接失败、绝不静默丢规则；上游没变时不写文件、不产生提交。
"""

import argparse
import os
import re
import sys
import urllib.request

UPSTREAM_LPX_URL = "https://raw.githubusercontent.com/zbsdsb/loon-adblock-plugins/main/JD_remove_ads_v2.lpx"
UPSTREAM_JS_URL = "https://raw.githubusercontent.com/zbsdsb/loon-adblock-plugins/main/JD_remove_ads_v2.js"
DEFAULT_OUTPUT = "Surge/Module/JD_remove_ads_v2.sgmodule"
MODULE_NAME = "京东净化"
MODULE_CATEGORY = "Polly-ai"
SCRIPT_PREFIX = "JD_remove_ads_v2"
SELF_HOSTED_JS_URL = "https://raw.githubusercontent.com/Polly-ai/Wynston/main/Surge/JavaScript/JD_remove_ads_v2/JD_remove_ads_v2.js"
ASSET_PATH = "Surge/JavaScript/JD_remove_ads_v2/JD_remove_ads_v2.js"


def fail(msg):
    print(f"sync_{SCRIPT_PREFIX}: error: {msg}", file=sys.stderr)
    sys.exit(2)


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
    """解析上游 .lpx：头部 #! 注释、[Rule]、[Script]、[MitM]。"""
    meta = {}
    rules, scripts, mitm = [], [], []
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#!"):
            m = re.fullmatch(r"#!(\w+)\s*=\s*(.+)", line)
            if not m:
                fail(f"无法识别的头部行：{raw!r}")
            meta[m.group(1)] = m.group(2).strip()
            continue
        if line.startswith("[") and line.endswith("]"):
            if line == "[Rule]":
                section = "rule"
                continue
            if line == "[Script]":
                section = "script"
                continue
            if line == "[MitM]":
                section = "mitm"
                continue
            fail(f"无法识别的段落：{raw!r}")
        if section == "rule":
            if not re.match(r"(?i)^(URL-REGEX|DOMAIN|DOMAIN-SUFFIX|DOMAIN-KEYWORD|IP-CIDR|GEOIP|USER-AGENT|URL-REGEX|FINAL)\b", line):
                fail(f"无法识别的 Rule 行：{raw!r}")
            rules.append(line)
            continue
        if section == "script":
            m = re.fullmatch(
                r"(http-response|http-request)\s+(\S+)\s+script-path=(\S+?),\s*requires-body=(true|false)(?:,\s*tag=(.+))?",
                line,
            )
            if not m:
                fail(f"无法识别的 Script 行：{raw!r}")
            req_type, pattern, js_url, requires_body, tag = m.groups()
            if req_type != "http-response":
                fail(f"不支持的脚本类型 {req_type!r}（期望 http-response）：{raw!r}")
            if requires_body != "true":
                fail(f"脚本 requires-body 不是 true：{raw!r}")
            if not js_url.endswith("/JD_remove_ads_v2.js"):
                fail(f"脚本地址不是 JD_remove_ads_v2.js：{js_url!r}")
            if not tag:
                fail(f"脚本缺少 tag：{raw!r}")
            scripts.append(
                f"{tag} = type=http-response, pattern={pattern}, "
                f"requires-body=true, script-path={SELF_HOSTED_JS_URL}"
            )
            continue
        if section == "mitm":
            m = re.fullmatch(r"hostname\s*=\s*(.+)", line)
            if not m:
                fail(f"无法识别的 MitM 行：{raw!r}")
            mitm = [h.strip() for h in m.group(1).split(",") if h.strip()]
            if not mitm:
                fail("hostname 行为空")
            continue
        fail(f"无法识别的行，已中止：{raw!r}")
    if "desc" not in meta:
        fail("上游缺少 #!desc，结构可能已变，已中止")
    if "author" not in meta:
        fail("上游缺少 #!author，结构可能已变，已中止")
    if not rules:
        fail("上游 [Rule] 为空，结构可能已变，已中止")
    if not scripts:
        fail("上游 [Script] 为空，结构可能已变，已中止")
    if not mitm:
        fail("上游 [MitM] 为空，结构可能已变，已中止")
    return {"meta": meta, "rules": rules, "scripts": scripts, "mitm": mitm}


def render(parts):
    meta = parts["meta"]
    out = [
        f"#!name = {MODULE_NAME}",
        f"#!desc = {meta['desc']}",
        f"#!category = {MODULE_CATEGORY}",
        f"#!author = {meta['author']}",
    ]
    if "icon" in meta:
        out.append(f"#!icon = {meta['icon']}")
    if "openUrl" in meta:
        out.append(f"#!openUrl = {meta['openUrl']}")
    out += ["", f"# 转换自 Loon 插件格式，上游：{UPSTREAM_LPX_URL}", ""]
    out += ["[Rule]", *parts["rules"], ""]
    out += ["[Script]", *parts["scripts"], ""]
    out += ["[MITM]", "hostname = %APPEND% " + ", ".join(parts["mitm"])]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-file")
    ap.add_argument("--js-from-file", help="本地测试用：以上游 js 文件代替网络抓取")
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    text = fetch_text(UPSTREAM_LPX_URL, args.from_file)
    parts = parse(text)

    # 自托管镜像同步：上游 js 全文原样镜像；即使模块文本不变，
    # 上游 js 变了也要更新镜像文件。
    if args.js_from_file:
        js_text = open(args.js_from_file, encoding="utf-8").read()
    else:
        js_text = fetch_text(UPSTREAM_JS_URL, None)
    if "$request" not in js_text or "$response" not in js_text or "$done" not in js_text:
        fail("上游 js 不再使用 $request/$response/$done，脚本接口可能已变，已中止")
    js_changed = False
    try:
        old_js = open(ASSET_PATH, encoding="utf-8").read()
    except FileNotFoundError:
        old_js = None
    if old_js != js_text:
        os.makedirs(os.path.dirname(ASSET_PATH), exist_ok=True)
        with open(ASSET_PATH, "w", encoding="utf-8") as f:
            f.write(js_text)
        js_changed = True
        print(f"sync_{SCRIPT_PREFIX}: 已更新镜像 {ASSET_PATH}（上游 {UPSTREAM_JS_URL}）")
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
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(new_text)
    print(f"sync_{SCRIPT_PREFIX}: 已写入 {args.output}（Rule {len(parts['rules'])}、"
          f"Script {len(parts['scripts'])}、MITM {len(parts['mitm'])}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
