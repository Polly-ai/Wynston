#!/usr/bin/env python3
"""把上游 Surge 模块 https://raw.githubusercontent.com/CaoXiaoMann/XiaoMan/main/Surge/Scripts/Pinduoduo/Pinduoduo.sgmodule 同步到本仓库，并每日跟随上游更新。

上游本身已是 Surge 模块格式：头部 #! 注释、[Rule]、[Map Local]、[Body Rewrite]、
[Script]、[MITM]，以及段落内的说明注释。同步时只改写头部三项和脚本地址，
其余内容原样保留。

用法（仓库工作流里不带参数跑，默认抓上游、写到仓库路径）：
    python3 .github/scripts/sync_pinduoduo_cxm.py
本地测试：
    python3 .github/scripts/sync_pinduoduo_cxm.py --from-file /tmp/Pinduoduo.sgmodule --output /tmp/out.sgmodule

改写规则：
  - #!name 固定为“拼多多净化”（用户指定，不跟上游的“拼多多去广告”）。
  - #!desc 随上游原文，不改写（用户指定“模块备注不变”）。
  - #!category 固定为 Polly-ai（用户指定）。
  - #!system、#!raw-url 随上游原文，不改写。
  - [Rule]、[Map Local]、[Body Rewrite]、[MITM] 及段落内注释全文原样保留。
  - 上游有两个 [Script] 段落，合并为一个（内容不变）。
  - [Script] 的脚本一律指向自托管地址（SELF_HOSTED 列表），不直接引用第三方 js；
    同步时同时抓上游 js 更新自托管镜像文件。
  - 例外：PDD-HOME-DEBUG 脚本 pdd_top_capture.js 在上游仓库里不存在（404），
    无法镜像；该条 script-path 保持上游原地址不变，等上游补上文件后，
    下次同步会自动改为自托管镜像。

固定不变的头部（同步时不被上游覆盖）：
  - #!name、#!category

上游出现无法识别的段落或缺少必要段落时直接失败、绝不静默丢规则；上游没变时不写文件、不产生提交。
"""

import argparse
import os
import re
import sys
import urllib.request

UPSTREAM_URL = "https://raw.githubusercontent.com/CaoXiaoMann/XiaoMan/main/Surge/Scripts/Pinduoduo/Pinduoduo.sgmodule"
DEFAULT_OUTPUT = "Surge/Module/pdd.sgmodule"
MODULE_NAME = "拼多多净化"
MODULE_CATEGORY = "Polly-ai"
KNOWN_SECTIONS = ("[Rule]", "[Map Local]", "[Body Rewrite]", "[Script]", "[MITM]")
REQUIRED_SECTIONS = ("[Rule]", "[Map Local]", "[Body Rewrite]", "[Script]", "[MITM]")
# 同步时原样保留的上游头部（按此顺序输出）
PRESERVED_HEADERS = ("system", "raw-url")
# 脚本镜像：(模块内脚本名, 上游 js 地址, 自托管路径)
# 自托管地址统一为 https://raw.githubusercontent.com/Polly-ai/Wynston/main/<自托管路径>
SCRIPTS = [
    (
        "移除扫码取件页面商品推荐及弹窗",
        "https://raw.githubusercontent.com/fkingikelee/fkikelee/main/Resource/kelee/JavaScript/PinDuoDuo/PinDuoDuo_remove_ads.js",
        "Surge/JavaScript/PinDuoDuo/PinDuoDuo_remove_ads.js",
    ),
    (
        "精简评价页",
        "https://raw.githubusercontent.com/Yi-r8/Surge/refs/heads/main/Js/pinduoduo.js",
        "Surge/JavaScript/PinDuoDuo/pinduoduo.js",
    ),
    (
        "PDD-HOME-DEBUG",
        "https://raw.githubusercontent.com/CaoXiaoMann/XiaoMan/main/Surge/Scripts/Pinduoduo/pdd_top_capture.js",
        "Surge/JavaScript/PinDuoDuo/pdd_top_capture.js",
    ),
]
SELF_HOSTED_BASE = "https://raw.githubusercontent.com/Polly-ai/Wynston/main/"


def fail(msg):
    print(f"sync_pinduoduo_cxm: error: {msg}", file=sys.stderr)
    sys.exit(2)


def fetch_text(url, from_file=None):
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


def fetch_optional(url):
    """抓脚本用：404 时返回 None（不致命），其他失败直接中止。"""
    req = urllib.request.Request(url, headers={"User-Agent": "surge-sync/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                return None
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        fail(f"抓取脚本失败 HTTP {e.code}：{url}")
    except Exception as e:
        fail(f"抓取脚本失败：{e}")


def parse(text):
    """解析上游 .sgmodule：头部 #! 注释；正文按段落收集，重复的 [Script] 合并。"""
    meta = {}
    segments = []  # [{name, lines}]，name 为 None 表示段落前的说明文字
    current = None
    seen_sections = set()
    in_header = True
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if in_header:
            if not stripped:
                continue
            if stripped.startswith("#!"):
                m = re.fullmatch(r"#!(\S+?)\s*=\s*(.+)", stripped)
                if not m:
                    fail(f"无法识别的头部行：{raw!r}")
                meta[m.group(1)] = m.group(2).strip()
                continue
            in_header = False
        if stripped.startswith("[") and stripped.endswith("]"):
            if stripped not in KNOWN_SECTIONS:
                fail(f"无法识别的段落：{raw!r}")
            seen_sections.add(stripped)
            if stripped == "[Script]" and any(s["name"] == "[Script]" for s in segments):
                current = next(s for s in segments if s["name"] == "[Script]")
                continue
            current = {"name": stripped, "lines": []}
            segments.append(current)
            continue
        if current is None:
            current = {"name": None, "lines": []}
            segments.append(current)
        current["lines"].append(line)
    for section in REQUIRED_SECTIONS:
        if section not in seen_sections:
            fail(f"上游缺少必要段落 {section}，结构可能已变，已中止")
    if "desc" not in meta:
        fail("上游缺少 #!desc，结构可能已变，已中止")
    return {"meta": meta, "segments": segments}


def rewrite_script_line(line, mirrored):
    """把 [Script] 行的 script-path 改为自托管地址（未镜像的保持原地址）。"""
    m = re.fullmatch(
        r"(.+?)\s*=\s*type=(http-response|http-request)\s*,\s*pattern=(.+?)\s*,\s*"
        r"script-path=(\S+?)\s*,\s*requires-body=(true|false)\s*,\s*max-size=(\d+)\s*",
        line,
    )
    if not m:
        fail(f"无法识别的 Script 行：{line!r}")
    name, req_type, pattern, js_url, requires_body, max_size = m.groups()
    if req_type != "http-response":
        fail(f"不支持的脚本类型 {req_type!r}（期望 http-response）：{line!r}")
    if requires_body != "true":
        fail(f"脚本 requires-body 不是 true：{line!r}")
    new_url = mirrored.get(name.strip(), js_url)
    return (
        f"{name.strip()} = type=http-response,pattern={pattern},"
        f"script-path={new_url},requires-body=true,max-size={max_size}"
    )


def render(parts, mirrored):
    meta = parts["meta"]
    out = [
        f"#!name = {MODULE_NAME}",
        f"#!desc = {meta['desc']}",
        f"#!category = {MODULE_CATEGORY}",
    ]
    for key in PRESERVED_HEADERS:
        if key in meta:
            out.append(f"#!{key} = {meta[key]}")
    out += ["", f"# 同步自上游：{UPSTREAM_URL}", ""]
    for seg in parts["segments"]:
        if seg["name"]:
            out.append(seg["name"])
        for line in seg["lines"]:
            if seg["name"] == "[Script]" and line.strip():
                out.append(rewrite_script_line(line, mirrored))
            else:
                out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-file")
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    text = fetch_text(UPSTREAM_URL, args.from_file)
    parts = parse(text)

    # 自托管镜像同步：上游 js 全文原样镜像；抓不到（404）的脚本保持原地址，
    # 等上游补上文件后下次同步自动改为镜像。
    mirrored = {}
    js_changed = False
    for name, js_url, asset_path in SCRIPTS:
        js_text = fetch_optional(js_url)
        if js_text is None:
            print(f"sync_pinduoduo_cxm: 注意：脚本 {name} 上游不存在（{js_url}），保持原地址")
            continue
        try:
            old_js = open(asset_path, encoding="utf-8").read()
        except FileNotFoundError:
            old_js = None
        if old_js != js_text:
            os.makedirs(os.path.dirname(asset_path), exist_ok=True)
            with open(asset_path, "w", encoding="utf-8") as f:
                f.write(js_text)
            js_changed = True
            print(f"sync_pinduoduo_cxm: 已更新镜像 {asset_path}")
        mirrored[name] = SELF_HOSTED_BASE + asset_path

    new_text = render(parts, mirrored)
    try:
        old_text = open(args.output, encoding="utf-8").read()
    except FileNotFoundError:
        old_text = None
    if old_text == new_text and not js_changed:
        print("sync_pinduoduo_cxm: 规则无变化，跳过写入（避免无意义提交）")
        return 0
    if old_text == new_text and js_changed:
        print("sync_pinduoduo_cxm: 模块无变化，镜像已更新")
        return 0
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(new_text)
    print(f"sync_pinduoduo_cxm: 已写入 {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
