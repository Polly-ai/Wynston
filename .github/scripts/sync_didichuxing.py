#!/usr/bin/env python3
"""把 ZenmoFeiShi 的 Qx Didichuxing.snippet 转换为 Surge 模块，并每日同步。

用法（仓库工作流里不带参数跑，默认抓上游、写到仓库路径）：
    python3 .github/scripts/sync_didichuxing.py
本地测试：
    python3 .github/scripts/sync_didichuxing.py --snippet-file /tmp/Didichuxing.snippet --output-module /tmp/out.sgmodule

转换规则（上游是纯规则文件，没有外部脚本）：
  - host, X, reject -> [Rule] DOMAIN,X,REJECT
  - ip-cidr, X, reject -> [Rule] IP-CIDR,X,REJECT,no-resolve
    （模块里的 IP 规则一律加 no-resolve，否则域名请求会先触发 DNS 解析）
  - ^... url reject-dict -> [Map Local] pattern data-type=text data="{}" status-code=200 header="Content-Type:application/json"
    （Surge 的 [URL Rewrite] 只有 header/302/307/reject，没有 reject-dict，直接照搬动作名会使规则不生效）
  - ^... url jsonjq-response-body 'jq' -> [Body Rewrite]
    http-response-jq pattern 'jq'（jq 原文不动，需 Surge iOS 5.14.0+ / Mac 5.9.0+）
  - hostname = ... -> [MITM] hostname = %APPEND% ...

固定不变的头部（同步时不被上游覆盖）：
  - #!name、#!desc、#!category、#!author
  - 上游 #!author 是“怎么肥事”（文件托管在 ZenmoFeiShi/Qx 仓库里，作者不是 ZenmoFeiShi）

上游出现无法识别的行时直接失败、绝不静默丢规则；上游没变时不写文件、不产生提交。
"""

import argparse
import sys
import urllib.request

UPSTREAM_SNIPPET_URL = "https://raw.githubusercontent.com/ZenmoFeiShi/Qx/refs/heads/main/Didichuxing.snippet"
DEFAULT_MODULE_OUTPUT = "Surge/Module/didichuxing.sgmodule"

MODULE_NAME = "滴滴出行"
MODULE_DESC = "净化滴滴出行首页与我的页推广、金融与会员入口，屏蔽活动、信息流与开屏类广告请求。"
MODULE_CATEGORY = "Polly-ai"
MODULE_AUTHOR = "怎么肥事"


def fail(msg):
    print(f"sync_didichuxing: error: {msg}", file=sys.stderr)
    sys.exit(2)


def fetch_text(url, from_file):
    if from_file:
        with open(from_file, "r", encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": "didichuxing-sync/1.0"})
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
        if line.startswith("#"):
            fail(f"无法识别的上游行，已中止：{raw_line}")
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

    if not rules or not map_locals or not body_rewrites or not mitm_hosts:
        fail("转换后某一段为空（Rule/Map Local/Body Rewrite/MITM 至少一段为空），上游结构可能已变，已中止")

    out = []
    out.append(f"#!name = {MODULE_NAME}")
    out.append(f"#!desc = {MODULE_DESC}")
    out.append(f"#!category = {MODULE_CATEGORY}")
    out.append(f"#!author = {MODULE_AUTHOR}")
    out.append("")
    out.append("# 转换自 QX 格式，上游：https://raw.githubusercontent.com/ZenmoFeiShi/Qx/refs/heads/main/Didichuxing.snippet")
    out.append("# 注意：[Body Rewrite] 的 http-response-jq 需 Surge iOS 5.14.0+ / Mac 5.9.0+，低版本 Surge 上这部分规则不生效；[Rule] 与 [Map Local] 不受此限制。")
    out.append("# [Map Local] 的 {} 返回即 QX reject-dict 的等价写法；Surge [URL Rewrite] 没有 reject-dict 模式，直接照搬会使规则不生效。")
    out.append("# MITM 中的 IP 通配（如 117.51.168.*）按上游原样保留；URL 规则所用的域名均已在 MITM 列表中。")
    out.append("")
    out.append("[Rule]")
    out.extend(rules)
    out.append("")
    out.append("[Map Local]")
    out.extend(map_locals)
    out.append("")
    out.append("[Body Rewrite]")
    out.extend(body_rewrites)
    out.append("")
    out.append("[MITM]")
    out.append("hostname = %APPEND% " + ", ".join(mitm_hosts))
    out.append("")
    return "\n".join(out), len(rules), len(map_locals), len(body_rewrites), len(mitm_hosts)


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--snippet-file", default=None)
    parser.add_argument("--output-module", default=DEFAULT_MODULE_OUTPUT)
    args = parser.parse_args(argv)

    text = fetch_text(UPSTREAM_SNIPPET_URL, args.snippet_file)
    module_text, n_rule, n_map, n_body, n_mitm = convert_snippet(text)

    try:
        with open(args.output_module, "r", encoding="utf-8") as f:
            existing = f.read()
    except FileNotFoundError:
        existing = None
    if existing == module_text:
        print("sync_didichuxing: 模块无变化，跳过写入")
        return 0
    with open(args.output_module, "w", encoding="utf-8") as f:
        f.write(module_text)
    print(f"sync_didichuxing: 已写入 {args.output_module}（Rule {n_rule}、Map Local {n_map}、Body Rewrite {n_body}、MITM {n_mitm}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
