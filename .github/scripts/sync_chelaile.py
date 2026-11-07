#!/usr/bin/env python3
"""把上游 Surge 模块 https://raw.githubusercontent.com/CaoXiaoMann/XiaoMan/main/Surge/Scripts/CheLaiLe/CheLaiLe.sgmodule 同步到本仓库，并每日跟随上游更新。

上游本身已是 Surge 模块格式：头部 #! 注释、[Rule]、[URL Rewrite]、[MITM]，
以及段落内的说明注释。同步时只改写头部三项，其余内容原样保留。

用法（仓库工作流里不带参数跑，默认抓上游、写到仓库路径）：
    python3 .github/scripts/sync_chelaile.py
本地测试：
    python3 .github/scripts/sync_chelaile.py --from-file /tmp/CheLaiLe.sgmodule --output /tmp/out.sgmodule

改写规则：
  - #!name 固定为“车来了净化”（用户指定，不跟上游的“车来了去广告”）。
  - #!desc 固定为“车来了去广告7.6.7 不拦截公交业务接口”（用户指定）。
  - #!category 固定为 Polly-ai（用户指定）。
  - #!author、#!homepage、#!raw-url、#!last-updated、#!date 随上游原文，不改写。
  - [Rule]、[URL Rewrite]、[MITM] 及段落内注释全文原样保留（本模块无 [Script]，
    不需要镜像 js）。

固定不变的头部（同步时不被上游覆盖）：
  - #!name、#!desc、#!category

上游出现无法识别的段落或缺少必要段落时直接失败、绝不静默丢规则；上游没变时不写文件、不产生提交。
"""

import argparse
import os
import re
import sys
import urllib.request

UPSTREAM_URL = "https://raw.githubusercontent.com/CaoXiaoMann/XiaoMan/main/Surge/Scripts/CheLaiLe/CheLaiLe.sgmodule"
DEFAULT_OUTPUT = "Surge/Module/CheLaiLe.sgmodule"
MODULE_NAME = "车来了净化"
MODULE_DESC = "车来了去广告7.6.7 不拦截公交业务接口"
MODULE_CATEGORY = "Polly-ai"
KNOWN_SECTIONS = ("[Rule]", "[URL Rewrite]", "[MITM]")
REQUIRED_SECTIONS = ("[Rule]", "[URL Rewrite]", "[MITM]")
# 同步时原样保留的上游头部（按此顺序输出）
PRESERVED_HEADERS = ("author", "homepage", "raw-url", "last-updated", "date")


def fail(msg):
    print(f"sync_chelaile: error: {msg}", file=sys.stderr)
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
    """解析上游 .sgmodule：头部 #! 注释，其余正文原样保留。"""
    meta = {}
    body = []
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
        body.append(line)
    for section in REQUIRED_SECTIONS:
        if section not in seen_sections:
            fail(f"上游缺少必要段落 {section}，结构可能已变，已中止")
    if "author" not in meta:
        fail("上游缺少 #!author，结构可能已变，已中止")
    return {"meta": meta, "body": body}


def render(parts):
    meta = parts["meta"]
    out = [
        f"#!name = {MODULE_NAME}",
        f"#!desc = {MODULE_DESC}",
        f"#!category = {MODULE_CATEGORY}",
    ]
    for key in PRESERVED_HEADERS:
        if key in meta:
            out.append(f"#!{key} = {meta[key]}")
    out += ["", f"# 同步自上游：{UPSTREAM_URL}", ""]
    out += parts["body"]
    return "\n".join(out).rstrip("\n") + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-file")
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    text = fetch_text(UPSTREAM_URL, args.from_file)
    parts = parse(text)
    new_text = render(parts)
    try:
        old_text = open(args.output, encoding="utf-8").read()
    except FileNotFoundError:
        old_text = None
    if old_text == new_text:
        print("sync_chelaile: 规则无变化，跳过写入（避免无意义提交）")
        return 0
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(new_text)
    print(f"sync_chelaile: 已写入 {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
