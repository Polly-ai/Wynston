#!/usr/bin/env python3
"""把 ZenmoFeiShi 的 Qx Pinduoduo.snippet 转换为 Surge 模块，并每日同步。

用法（仓库工作流里不带参数跑，默认抓上游、写到仓库路径）：
    python3 .github/scripts/sync_pinduoduo.py
本地测试：
    python3 .github/scripts/sync_pinduoduo.py --snippet-file /tmp/Pinduoduo.snippet --output-module /tmp/out.sgmodule

转换规则（2026-11-04 上游 v8.29.0 改版：删掉全部 reject-dict / jsonjq，
  改为 3 条 script-response-body，走 Pinduoduo.js 做底栏与弹窗净化）：
  - ^... url script-response-body <js> -> [Script] 唯一脚本名，
    type=http-response, requires-body=true, script-path=<js>（沿用
    sync_txvideo.py / sync_meituan.py 的同款写法）
  - host, X, reject -> [Rule] DOMAIN,X,REJECT
  - ip-cidr, X, reject -> [Rule] IP-CIDR,X,REJECT,no-resolve
    （模块里的 IP 规则一律加 no-resolve，否则域名请求会先触发 DNS 解析）
  - ^... url reject-dict -> [Map Local] pattern data-type=text data="{}" status-code=200 header="Content-Type:application/json"（Surge [URL Rewrite] 没有 reject-dict，直接照搬会使规则不生效）
  - ^... url jsonjq-response-body 'jq' -> [Body Rewrite]
    http-response-jq pattern 'jq'（jq 原文不动，需 Surge iOS 5.14.0+ / Mac 5.9.0+）
  - hostname = ... -> [MITM] hostname = %APPEND% ...
  - 以 // 开头的行是上游注释，跳过；以 #! 开头的行是上游元数据，跳过。

固定不变的头部（同步时不被上游覆盖）：
  - #!name、#!desc、#!category、#!author
  - 上游 #!author 是“怎么肥事 walala”（文件托管在 ZenmoFeiShi/Qx 仓库里）

上游出现无法识别的行时直接失败、绝不静默丢规则；上游没变时不写文件、不产生提交。
"""

import argparse
import re
import sys
import urllib.request

UPSTREAM_SNIPPET_URL = "https://raw.githubusercontent.com/ZenmoFeiShi/Qx/refs/heads/main/Pinduoduo.snippet"
DEFAULT_MODULE_OUTPUT = "Surge/Module/pinduoduo.sgmodule"

MODULE_NAME = "拼多多净化底栏与弹窗"
MODULE_DESC = "净化拼多多底栏与弹窗，屏蔽广告与推广入口。（2026-11-04 上游改版后范围）"
MODULE_CATEGORY = "Polly-ai"
MODULE_AUTHOR = "怎么肥事"

# 脚本规则可能被换行拆开，因此用 \s+ 横跨空白（含换行）匹配（同 sync_txvideo.py）。
SCRIPT_RE = re.compile(r"(\^\S+)\s+url\s+script-(request|response)-body\s+(https?://\S+)")


def fail(msg):
    print(f"sync_pinduoduo: error: {msg}", file=sys.stderr)
    sys.exit(2)


def fetch_text(url, from_file):
    if from_file:
        with open(from_file, "r", encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": "pinduoduo-sync/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                fail(f"上游返回 HTTP {resp.status}：{url}")
            return resp.read().decode("utf-8")
    except SystemExit:
        raise
    except Exception as e:  # 抓取失败时绝不写空文件
        fail(f"抓取上游失败：{e}")


def convert_snippet(text):
    rules = []
    map_locals = []
    body_rewrites = []
    mitm_hosts = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#!"):
            continue
        if line.startswith("//"):
            continue
        if line.startswith("#"):
            fail(f"无法识别的上游行，已中止：{raw_line}")
        if SCRIPT_RE.match(line):
            continue  # 脚本行由后面的 SCRIPT_RE.finditer 统一提取
        if line.startswith("host,"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 3 or parts[2] != "reject" or not parts[1]:
                fail(f"无法识别的 host 行，已中止：{raw_line}")
            rules.append(f"DOMAIN,{parts[1]},REJECT")
        elif line.startswith("ip-cidr,"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 3 or parts[2] != "reject" or not parts[1]:
                fail(f"无法识别的 ip-cidr 行，已中止：{raw_line}")
            rules.append(f"IP-CIDR,{parts[1]},REJECT,no-resolve")
        elif line.startswith("^") and line.endswith(" url reject-dict"):
            pattern = line[: -len(" url reject-dict")]
            if not pattern:
                fail(f"无法识别的 reject-dict 行，已中止：{raw_line}")
            map_locals.append(f'{pattern} data-type=text data="{{}}" status-code=200 header="Content-Type:application/json"')
        elif line.startswith("^") and " url jsonjq-response-body " in line:
            pattern, jq_quoted = line.split(" url jsonjq-response-body ", 1)
            jq_quoted = jq_quoted.strip()
            if len(jq_quoted) < 2 or not jq_quoted.startswith("'") or not jq_quoted.endswith("'"):
                fail(f"无法识别的 jsonjq 行（jq 未用单引号包裹），已中止：{raw_line}")
            jq = jq_quoted[1:-1]
            if "'" in jq:
                fail(f"无法识别的 jsonjq 行（jq 内含单引号，无法安全转写），已中止：{raw_line}")
            if not pattern or not jq:
                fail(f"无法识别的 jsonjq 行，已中止：{raw_line}")
            body_rewrites.append(f"http-response-jq {pattern} '{jq}'")
        elif line.startswith("hostname"):
            if "=" not in line:
                fail(f"无法识别的 hostname 行，已中止：{raw_line}")
            hosts = [h.strip() for h in line.split("=", 1)[1].split(",")]
            hosts = [h for h in hosts if h]
            if not hosts:
                fail(f"hostname 行为空，已中止：{raw_line}")
            mitm_hosts = hosts
        else:
            fail(f"无法识别的上游行，已中止：{raw_line}")

    scripts = []
    for i, m in enumerate(SCRIPT_RE.finditer(text), start=1):
        pattern, kind, js_url = m.group(1), m.group(2), m.group(3)
        req_type = "http-request" if kind == "request" else "http-response"
        scripts.append(
            f"pinduoduo_{i} = type={req_type}, pattern={pattern}, "
            f"requires-body=true, script-path={js_url}"
        )

    # 上游 v8.29.0 起 Map Local / Body Rewrite 为空是正常的（规则已并入脚本），
    # 只要求 Rule、Script、MITM 三段非空；任一段为空仍直接失败、不静默丢规则。
    if not rules or not scripts or not mitm_hosts:
        fail("转换后某一段为空（Rule/Script/MITM 至少一段为空），上游结构可能已变，已中止")

    out = []
    out.append(f"#!name = {MODULE_NAME}")
    out.append(f"#!desc = {MODULE_DESC}")
    out.append(f"#!category = {MODULE_CATEGORY}")
    out.append(f"#!author = {MODULE_AUTHOR}")
    out.append("")
    out.append("# 转换自 QX 格式，上游：https://raw.githubusercontent.com/ZenmoFeiShi/Qx/refs/heads/main/Pinduoduo.snippet")
    out.append("# 注意：净化逻辑在 Pinduoduo.js 里（上游脚本直链）；[Script] 需 Surge 开 MITM，脚本本身须兼容 Surge 的 $response / $done 写法。")
    out.append("# MITM 仅 api.pinduoduo.com 一个域名；[Rule] 的域名/IP 屏蔽不依赖 MITM。")
    out.append("")
    out.append("[Rule]")
    out.extend(rules)
    out.append("")
    out.append("[Script]")
    out.extend(scripts)
    out.append("")
    if map_locals:
        out.append("[Map Local]")
        out.extend(map_locals)
        out.append("")
    if body_rewrites:
        out.append("[Body Rewrite]")
        out.extend(body_rewrites)
        out.append("")
    out.append("[MITM]")
    out.append("hostname = %APPEND% " + ", ".join(mitm_hosts))
    out.append("")
    return "\n".join(out), len(rules), len(scripts), len(map_locals), len(body_rewrites), len(mitm_hosts)


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--snippet-file", default=None)
    parser.add_argument("--output-module", default=DEFAULT_MODULE_OUTPUT)
    args = parser.parse_args(argv)

    text = fetch_text(UPSTREAM_SNIPPET_URL, args.snippet_file)
    module_text, n_rule, n_script, n_map, n_body, n_mitm = convert_snippet(text)

    try:
        with open(args.output_module, "r", encoding="utf-8") as f:
            existing = f.read()
    except FileNotFoundError:
        existing = None
    if existing == module_text:
        print("sync_pinduoduo: 模块无变化，跳过写入")
        return 0
    with open(args.output_module, "w", encoding="utf-8") as f:
        f.write(module_text)
    print(f"sync_pinduoduo: 已写入 {args.output_module}（Rule {n_rule}、Script {n_script}、Map Local {n_map}、Body Rewrite {n_body}、MITM {n_mitm}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
