#!/usr/bin/env python3
"""把 kokoryh/Sparkle 上游的 bilibili.sgmodule 镜像到本仓库。

用法（在仓库根目录执行）：
    python3 .github/scripts/sync_bilibili.py
    python3 .github/scripts/sync_bilibili.py --from-file /tmp/bilibili.sgmodule --output /tmp/out.sgmodule

同步方式（与 TxvideoAD 的 QX 转 Surge 不同，上游本身已是 Surge 模块）：
  - 上游内容原样保留，只固定两行，不跟随上游变化：
      #!desc     -> 固定为下面的 FIXED_DESC
      #!category -> 固定为 Polly-ai
  - 其余所有行（包括 #!name、#!arguments、[Rule]、[Map Local]、
    [Body Rewrite]、[Script]、[MITM]）一律以上游为准。

防刷屏：生成内容与现有文件一致时不写文件，这样上游没变时不会
每天产生一条无意义提交；只有上游真变了才提交。
"""

import re
import sys
import urllib.request

UPSTREAM_URL = "https://raw.githubusercontent.com/kokoryh/Sparkle/refs/heads/master/release/surge/module/bilibili.sgmodule"
DEFAULT_OUTPUT = "Surge/Module/bilibili-enhance.sgmodule"

# 固定头部：同步时始终以这里为准，不跟随上游变化。
FIXED_DESC = "哔哩哔哩去广告与界面净化，支持空降助手与 P2P 屏蔽"
FIXED_CATEGORY = "Polly-ai"

SECTION_RE = re.compile(r"^\[.+\]$")


def fail(msg):
    print(f"sync_bilibili: error: {msg}", file=sys.stderr)
    sys.exit(2)


def fetch_text(from_file):
    if from_file:
        with open(from_file, "r", encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(UPSTREAM_URL, headers={"User-Agent": "bilibili-sync/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                fail(f"上游返回 HTTP {resp.status}")
            return resp.read().decode("utf-8")
    except Exception as e:  # 抓取失败时绝不写空文件
        fail(f"抓取上游失败：{e}")


def convert(text):
    if not text.strip():
        fail("上游内容为空")
    lines = text.splitlines()
    if not any(SECTION_RE.match(ln.strip()) for ln in lines):
        fail("上游内容里没有 [Rule]/[Script] 之类的段标题，不像个模块，已中止")

    out = []
    found_desc = False
    found_category = False
    name_idx = None
    for ln in lines:
        if ln.startswith("#!desc="):
            out.append(f"#!desc={FIXED_DESC}")
            found_desc = True
        elif ln.startswith("#!category="):
            out.append(f"#!category={FIXED_CATEGORY}")
            found_category = True
        else:
            out.append(ln)
        if ln.startswith("#!name=") and name_idx is None:
            name_idx = len(out) - 1

    # 上游万一删了描述/分类行，在 #!name 后补上，而不是静默丢掉固定值。
    insert_at = (name_idx + 1) if name_idx is not None else 0
    if not found_category:
        out.insert(insert_at, f"#!category={FIXED_CATEGORY}")
        insert_at += 1
    if not found_desc:
        out.insert(insert_at, f"#!desc={FIXED_DESC}")

    return "\n".join(out) + "\n"


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

    if old_text is not None and old_text == new_text:
        print("sync_bilibili: 上游无变化，跳过写入（避免无意义提交）")
        return 0

    with open(output, "w", encoding="utf-8") as f:
        f.write(new_text)
    print(f"sync_bilibili: 已写入 {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
