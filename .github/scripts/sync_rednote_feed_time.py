#!/usr/bin/env python3
"""把上游 meichiny/rednote-feed-time 的 Shadowrocket 模块同步为 Surge 模块。

上游本身就是 Surge/Shadowrocket 模块格式：同步时只替换头部元数据
（#!name/#!desc/#!category/#!author/#!system），[Script] 的 script-path 一律改写为
自托管地址（SELF_HOSTED_JS_URL），同时抓上游 js 更新自托管镜像文件。
（#!name/#!desc/#!category/#!author/#!system），[Rule]/[Script]/[MITM]
三段原样保留；结构或条数变化时直接失败、绝不静默丢规则。
上游没变时不写文件、不产生提交。
"""
import argparse
import re
import sys
import urllib.request

UPSTREAM_URL = "https://github.com/meichiny/rednote-feed-time/raw/rewrite-rule/modules/shadowrocket/rednote-feed-time.sgmodule"
SELF_HOSTED_JS_URL = "https://raw.githubusercontent.com/Polly-ai/Wynston/main/Surge/JavaScript/Rednote/rednote-feed-time.js"
ASSET_PATH = "Surge/JavaScript/Rednote/rednote-feed-time.js"
DEFAULT_OUTPUT = "Surge/Module/rednote-feed-time.sgmodule"


def fail(msg):
    print(f"sync_rednote_feed_time: error: {msg}", file=sys.stderr)
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


def convert(text):
    m = re.search(r"\[Rule\]\n(.*?)\n\n\[Script\]\n(.*?)\n\n\[MITM\]\n(.*?)\n?$", text, re.S)
    if not m:
        fail("上游模块结构已变（未找到 [Rule]/[Script]/[MITM] 三段），已中止")
    rule_lines = [l for l in m.group(1).splitlines() if l.strip()]
    script_lines = [l for l in m.group(2).splitlines() if l.strip()]
    mitm_line = m.group(3).strip()
    if len(rule_lines) != 1 or len(script_lines) != 1 or not mitm_line.startswith("hostname"):
        fail(f"上游条数已变（Rule {len(rule_lines)}、Script {len(script_lines)}），已中止")
    mjs = re.search(r"script-path=([^,\s]+)", script_lines[0])
    if not mjs:
        fail("上游 Script 行缺少 script-path，已中止")
    upstream_js_url = mjs.group(1)
    script_lines[0] = script_lines[0].replace(upstream_js_url, SELF_HOSTED_JS_URL)
    if "$prefs" in text or "$notify" in text:
        fail("上游脚本出现 QX 专属接口，需人工适配，已中止")
    out = ["#!name = 小红书 Feed 时间",
           "#!desc = 在首页 feed 笔记标题前显示生成时间",
           "#!category = Polly-ai",
           "#!author = rednote-feed-time",
           "#!system = ios",
           "",
           "# 转换自 Shadowrocket 模块，上游：" + UPSTREAM_URL,
           "# 如本模块的 QUIC 阻断规则未生效，请在主配置中手动添加：",
           "# 配置 → 长按当前配置 → 编辑纯文本 → 找到 [Rule] 区域 → 顶部添加：",
           "# AND,((PROTOCOL,UDP),(DST-PORT,443),(DOMAIN-SUFFIX,xiaohongshu.com)),REJECT",
           "",
           "[Rule]", rule_lines[0], "",
           "[Script]", script_lines[0], "",
           "[MITM]", mitm_line, ""]
    return "\n".join(out), upstream_js_url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-file")
    ap.add_argument("--js-from-file", help="本地测试用：以上游 js 文件代替网络抓取")
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    new_text, upstream_js_url = convert(fetch_text(UPSTREAM_URL, args.from_file))
    # 自托管镜像同步：即使模块文本不变，上游 js 变了也要更新镜像文件。
    js_changed = False
    if args.js_from_file:
        js_text = open(args.js_from_file, encoding="utf-8").read()
    elif args.from_file:
        js_text = None  # 本地 --from-file 测试不抓上游 js
    else:
        js_text = fetch_text(upstream_js_url, None)
    if js_text is not None:
        try:
            old_js = open(ASSET_PATH, encoding="utf-8").read()
        except FileNotFoundError:
            old_js = None
        if old_js != js_text:
            with open(ASSET_PATH, "w", encoding="utf-8") as f:
                f.write(js_text)
            js_changed = True
            print(f"sync_rednote_feed_time: 已更新镜像 {ASSET_PATH}（上游 {upstream_js_url}）")
    try:
        old_text = open(args.output, encoding="utf-8").read()
    except FileNotFoundError:
        old_text = None
    if old_text == new_text and not js_changed:
        print("sync_rednote_feed_time: 规则无变化，跳过写入（避免无意义提交）")
        return 0
    if old_text == new_text and js_changed:
        print("sync_rednote_feed_time: 模块无变化，镜像已更新")
        return 0
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(new_text)
    print(f"sync_rednote_feed_time: 已写入 {args.output}（Rule 1、Script 1、MITM 1）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
