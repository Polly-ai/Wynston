#!/usr/bin/env python3
"""把 ZenmoFeiShi 的 Qx MT.snippet 转换为 Surge 模块。

用法（在仓库根目录执行）：
    python3 .github/scripts/sync_meituan.py
    python3 .github/scripts/sync_meituan.py --from-file /tmp/MT.snippet --output /tmp/out.sgmodule

转换规则（与手工转换保持一致）：
  - host, X, reject            -> DOMAIN,X,REJECT
  - host-wildcard, X, reject    -> DOMAIN-WILDCARD,X,REJECT
  - ip-cidr, X, reject          -> IP-CIDR,X,REJECT,no-resolve
  - ip6-cidr, X, reject         -> IP-CIDR6,X,REJECT,no-resolve
  - ^... url script-response-body <js> -> [Script] 唯一脚本名，type=http-response
  - hostname = a, b, c          -> [MITM] hostname = %APPEND%a, b, c

固定不变的头部（同步时不被上游覆盖）：
  - #!name、#!desc、#!category、#!author
  - no-resolve：模块规则插于配置最前，无 no-resolve 的 IP 规则会迫使
    域名请求先 DNS 解析，DNS 失败还会 abort 规则测试，故必须保留。

防刷屏：生成内容除“更新时间”行外与现有文件一致时，不写文件，
这样上游没变时不会每天产生一条无意义提交；只有规则真变了才提交。
"""

import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

UPSTREAM_URL = "https://raw.githubusercontent.com/ZenmoFeiShi/Qx/refs/heads/main/MT.snippet"
DEFAULT_OUTPUT = "Surge/Module/meituan.sgmodule"

# 固定头部：同步时始终以这里为准，不跟随上游变化。
HEADER_NAME = "美团app净化"
HEADER_DESC = "美团 App 精简：拦截 shark/httpdns 相关域名与 IP；脚本处理首页 Tab、Feed、我的页、搜索热词、购物车入口与开屏图"
HEADER_CATEGORY = "Polly-ai"
HEADER_AUTHOR = "TG@ZenMoFiShi"
HEADER_NOTE = "# 原作者标注更新：2026.10.25（转换自 QX/Loon 格式，未在真机验证）"

RULE_PATTERNS = [
    (re.compile(r"^host,\s*(.+?),\s*reject$"), "DOMAIN"),
    (re.compile(r"^host-wildcard,\s*(.+?),\s*reject$"), "DOMAIN-WILDCARD"),
    (re.compile(r"^host-suffix,\s*(.+?),\s*reject$"), "DOMAIN-SUFFIX"),
    (re.compile(r"^host-keyword,\s*(.+?),\s*reject$"), "DOMAIN-KEYWORD"),
    (re.compile(r"^ip-cidr,\s*(.+?),\s*reject$"), "IP-CIDR"),
    (re.compile(r"^ip6-cidr,\s*(.+?),\s*reject$"), "IP-CIDR6"),
]
# 脚本规则可能被换行拆开（上一行以 script-response-body 结尾、URL 在下一行），
# 因此用 \s+ 横跨空白（含换行）匹配，而不是按行解析。
SCRIPT_RE = re.compile(r"(\^\S+)\s+url\s+script-response-body\s+(https?://\S+)")
HOSTNAME_RE = re.compile(r"^hostname\s*=\s*(.+)$", re.MULTILINE)


def fail(msg):
    print(f"sync_meituan: error: {msg}", file=sys.stderr)
    sys.exit(2)


def fetch_text(from_file):
    if from_file:
        with open(from_file, "r", encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(UPSTREAM_URL, headers={"User-Agent": "meituan-sync/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                fail(f"上游返回 HTTP {resp.status}")
            return resp.read().decode("utf-8")
    except Exception as e:  # 抓取失败时绝不写空文件
        fail(f"抓取上游失败：{e}")


def convert(text):
    rules = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("^") or re.match(r"^https?://\S+$", line):
            continue  # 脚本规则由 SCRIPT_RE 统一处理（含换行拆开的情况）
        if HOSTNAME_RE.match(line):
            continue  # hostname 由后面的 HOSTNAME_RE 统一提取
        for pattern, surge_type in RULE_PATTERNS:
            m = pattern.match(line)
            if m:
                value = m.group(1).strip()
                if surge_type in ("IP-CIDR", "IP-CIDR6"):
                    rules.append(f"{surge_type},{value},REJECT,no-resolve")
                else:
                    rules.append(f"{surge_type},{value},REJECT")
                break
        else:
            fail(f"无法识别的上游行（为避免静默丢规则，已中止）：{line!r}")

    scripts = []
    for i, m in enumerate(SCRIPT_RE.finditer(text), start=1):
        pattern, js_url = m.group(1), m.group(2)
        scripts.append(
            f"meituan_{i} = type=http-response, pattern={pattern}, "
            f"requires-body=true, script-path={js_url}"
        )

    mitm_hosts = None
    m = HOSTNAME_RE.search(text)
    if m:
        mitm_hosts = ", ".join(h.strip() for h in m.group(1).split(",") if h.strip())

    if not rules:
        fail("上游没有解析出任何规则")
    if not scripts:
        fail("上游没有解析出任何脚本规则")
    if not mitm_hosts:
        fail("上游没有 hostname 行")

    beijing = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    out = []
    out.append(f"# 上游来源：{UPSTREAM_URL}")
    out.append(f"# 更新时间：{beijing}（北京时间）")
    out.append(f"#!name = {HEADER_NAME}")
    out.append(f"#!desc = {HEADER_DESC}")
    out.append(f"#!category={HEADER_CATEGORY}")
    out.append(f"#!author = {HEADER_AUTHOR}")
    out.append(HEADER_NOTE)
    out.append("")
    out.append("[Rule]")
    out.extend(rules)
    out.append("")
    out.append("[Script]")
    out.extend(scripts)
    out.append("")
    out.append("[MITM]")
    out.append(f"hostname = %APPEND%{mitm_hosts}")
    return "\n".join(out) + "\n"


def normalize(text):
    """去掉更新时间行，用于判断规则本身是否变化。"""
    return "\n".join(
        line for line in text.splitlines() if not line.startswith("# 更新时间：")
    )


def main(argv):
    from_file = None
    output = DEFAULT_OUTPUT
    i = 0
    while i < len(argv):
        if argv[i] == "--from-file":
            i += 1
            from_file = argv[i]
        elif argv[i] == "--output":
            i += 1
            output = argv[i]
        else:
            fail(f"未知参数：{argv[i]}")
        i += 1

    new_text = convert(fetch_text(from_file))

    try:
        with open(output, "r", encoding="utf-8") as f:
            old_text = f.read()
    except FileNotFoundError:
        old_text = None

    if old_text is not None and normalize(old_text) == normalize(new_text):
        print("sync_meituan: 规则无变化，跳过写入（避免无意义提交）")
        return 0

    with open(output, "w", encoding="utf-8") as f:
        f.write(new_text)
    print(f"sync_meituan: 已写入 {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
