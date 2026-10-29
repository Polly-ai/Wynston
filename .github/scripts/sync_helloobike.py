#!/usr/bin/env python3
"""把 ZenmoFeiShi 的 Qx helloobike.snippet 转换为 Surge 模块，并把
配套的 easybike-ad.js 做 Surge 适配后一并同步。

用法（在仓库根目录执行）：
    python3 .github/scripts/sync_helloobike.py
    python3 .github/scripts/sync_helloobike.py --snippet-file /tmp/helloobike.snippet --js-file /tmp/easybike-ad.js --output-module /tmp/out.sgmodule --output-js /tmp/out.js

Snippet 转换规则（与手工转换保持一致）：
  - ^... url reject-200            -> [URL Rewrite] pattern _ reject-200（绝不静默丢弃）
  - ^... url script-request-body  <js> -> [Script] 唯一脚本名，type=http-request
  - ^... url script-response-body <js> -> [Script] 唯一脚本名，type=http-response
  - ^... url script-echo-response <js> -> [Script] 唯一脚本名，type=http-response
    （Surge 没有 echo 类型；该脚本对 resource json 返回 {status, headers, body}，
    用 http-response 覆盖上游响应可达到同样效果，且状态已由字符串改为数字）
  - hostname = a, b, c             -> [MITM] hostname = %APPEND% a, b, c

脚本路径规则：模块里的 script-path 一律指向本仓库的 Surge 适配版
  Surge/Script/easybike-ad_surge.js，绝不直接指向 QX 原版 easybike-ad.js，
  因为原版用了 Surge 没有的 $prefs / sessionIndex / statusCode，原文照搬
  在 Surge 下会静默失效（密钥捕获与请求/响应上下文关联都会丢）。

JS Surge 适配（每次同步都重新从上游原版生成，改动点固定，见 ADAPT 注释）：
  1. 文件头加一段兼容 shim（在原版 IIFE 之前执行）：
     - $prefs -> $persistentStore（valueForKey/read、setValueForKey/write、
       removeValueForKey/write(null, key)；QX 的 value 在前、key 在后，
       与 Surge write(data, key) 的顺序一致）
     - $notify -> $notification.post
     - $request.sessionIndex / $response.sessionIndex -> Surge 的 $request.id
       （官方手册：$request.id 在 http-request 与配对的 http-response 间稳定一致，
       正是 QX sessionIndex 在 Surge 下的对应物）
     - $response.statusCode -> $response.status（Surge 只有 status，没有 statusCode；
       不补这一项，密钥捕获那句 Number(undefined) !== 200 会永远提前返回）
  2. hbeContextKey：QX 只接受纯数字 sessionIndex（/^\\d{1,24}$/），Surge 的
     $request.id 不是纯数字，原校验会永远返回空串、上下文关联全断。
     改为用完整 $request.id 作键（仅清洗掉键名非法字符），不再哈希、不再设槽位上限，
     一个请求一个键。原因是 QX 的 sessionIndex 顺序递增、64 槽位基本不撞，
     而 Surge 的 $request.id 不是顺序数字，哈希到 64 槽位后首页多请求并发时极易撞槽，
     后一个请求会覆盖前一个的上下文，响应取到错误或失效的上下文就原样放行，
     表现为部分清理、部分漏网。
  3. echo 分支的状态：QX 返回 "HTTP/1.1 200 OK" / "HTTP/1.1 503 Service
     Unavailable" 字符串，Surge 的 $done 要求 status 为数字，改为 200 / 503。

  4. 钱包模块匹配放宽：原版 hbeMyWalletMatches 要求 5 道门全过（模块名、
     类型 2、内外 dsl 一致、金融条目类型、dsl 指纹、walletUrl），用户账号上
     某道门对不上导致钱包金融整排残留，截图无法确定是哪道门；用户已选
     直接放宽，接受余额显示若在同一模块内会一并消失的风险。改为只要模块名
     是 LEGO_MY_PAGE_MY_WALLET 且 moduleData 是字典就删。这是 Surge 侧对上游
     的偏离，同步时必须保留，否则次日同步会还原。

固定不变的头部（同步时不被上游覆盖）：
  - #!name、#!desc、#!category、#!author

防刷屏：生成内容与现有文件一致时不写文件，这样上游没变时不会
每天产生一条无意义提交；只有规则或脚本真变了才提交。
上游结构变了（新规则类型、新脚本文件、适配点对不上）时直接失败，
绝不静默丢规则或发布半适配的脚本。
"""

import re
import sys
import urllib.request

UPSTREAM_SNIPPET_URL = "https://raw.githubusercontent.com/ZenmoFeiShi/Qx/refs/heads/main/helloobike.snippet"
UPSTREAM_JS_URL = "https://raw.githubusercontent.com/ZenmoFeiShi/Qx/refs/heads/main/easybike-ad.js"
DEFAULT_MODULE_OUTPUT = "Surge/Module/helloobike.sgmodule"
DEFAULT_JS_OUTPUT = "Surge/Script/easybike-ad_surge.js"
ADAPTED_JS_URL = "https://raw.githubusercontent.com/Polly-ai/Wynston/refs/heads/main/Surge/Script/easybike-ad_surge.js"

# 固定头部：同步时始终以这里为准，不跟随上游变化。
HEADER_NAME = "哈啰净化"
HEADER_DESC = "净化弹窗、首页推荐流、借钱入口与会员领券横条，隐藏我的页推广宫格、推荐、奖励金、接单券提醒及钱包金融整排。"
HEADER_CATEGORY = "Polly-ai"
HEADER_AUTHOR = "TG@ZenMoFiShi"

REJECT200_RE = re.compile(r"^(\^\S+)\s+url\s+reject-200\s*$")
SCRIPT_RE = re.compile(
    r"(\^\S+)\s+url\s+script-(echo-response|request-body|response-body)\s+(https?://\S+)"
)
HOSTNAME_RE = re.compile(r"^hostname\s*=\s*(.+)$", re.MULTILINE)

SHIM = """// easybike-ad_surge.js - Surge 适配版
// 源自 ZenmoFeiShi/Qx 的 easybike-ad.js（QX 版），除以下 Surge 适配外逻辑原样保留：
// - $prefs -> $persistentStore，$notify -> $notification.post（见下方 shim）
// - $request.sessionIndex / $response.sessionIndex -> Surge 的 $request.id
// - $response.statusCode -> $response.status
// - hbeContextKey 改为用完整 $request.id 作键，不再哈希到 64 槽位（并发易撞槽，见同步脚本注释）
// - 钱包模块匹配放宽：只要模块名是 LEGO_MY_PAGE_MY_WALLET 就删（原版 5 道门在用户账号上对不上，见同步脚本注释）
// - echo 分支的 HTTP 状态字符串改为 Surge 要求的数字（200 / 503）
if (typeof $prefs === "undefined" && typeof $persistentStore !== "undefined") {
  var $prefs = {
    valueForKey: function (k) { return $persistentStore.read(k); },
    setValueForKey: function (v, k) { return $persistentStore.write(v, k); },
    removeValueForKey: function (k) { return $persistentStore.write(null, k); }
  };
}
if (typeof $notify === "undefined" && typeof $notification !== "undefined") {
  var $notify = function (t, s, b) { $notification.post(t, s, b); };
}
if (typeof $request !== "undefined" && $request && typeof $request.id !== "undefined") {
  try { $request.sessionIndex = $request.id; } catch (e) {}
  if (typeof $response !== "undefined" && $response) {
    try { $response.sessionIndex = $request.id; } catch (e) {}
    try { if (typeof $response.statusCode === "undefined" && typeof $response.status !== "undefined") $response.statusCode = $response.status; } catch (e) {}
  }
}

"""


def fail(msg):
    print(f"sync_helloobike: error: {msg}", file=sys.stderr)
    sys.exit(2)


def fetch_text(url, from_file):
    if from_file:
        with open(from_file, "r", encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": "helloobike-sync/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                fail(f"上游返回 HTTP {resp.status}：{url}")
            return resp.read().decode("utf-8")
    except Exception as e:  # 抓取失败时绝不写空文件
        fail(f"抓取上游失败：{e}")


def convert_snippet(text):
    # hostname 可能被换行拆开（上一行以逗号结尾、下一行是裸域名），先拼回一行。
    _lines = text.splitlines()
    _joined = []
    for _ln in _lines:
        if (_joined and _joined[-1].strip().startswith("hostname") and _joined[-1].strip().endswith(",")
                and re.match(r"^[\w\.\-]+$", _ln.strip())):
            _joined[-1] = _joined[-1].rstrip() + " " + _ln.strip()
        else:
            _joined.append(_ln)
    text = "\n".join(_joined)

    url_rewrites = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = REJECT200_RE.match(line)
        if m:
            url_rewrites.append(f"{m.group(1)} _ reject-200")
            continue
        if line.startswith("^") and "script-" in line:
            continue  # 脚本规则由 SCRIPT_RE 统一处理（含换行拆开的情况）
        if HOSTNAME_RE.match(line):
            continue  # hostname 由后面的 HOSTNAME_RE 统一提取
        fail(f"无法识别的上游行（为避免静默丢规则，已中止）：{line!r}")

    scripts = []
    for i, m in enumerate(SCRIPT_RE.finditer(text), start=1):
        pattern, kind, js_url = m.group(1), m.group(2), m.group(3)
        if js_url != UPSTREAM_JS_URL:
            fail(f"上游出现未预期的脚本文件（需先确认其 Surge 适配方式，已中止）：{js_url}")
        if kind == "request-body":
            req_type = "http-request"
        else:  # response-body 与 echo-response 在 Surge 下均为 http-response
            req_type = "http-response"
        extra = ""
        # /api 响应脚本的上游自查上限是 4MB，Surge 默认只缓冲 1MB，
        # 超过会直接跳过脚本；把上限放宽到与上游一致。
        # 注意：secretkey 规则的域名里也含 api，不能只凭 "/api" 判断，
        # 必须认准三域名轮换的 /api 路径规则本身。
        if req_type == "http-response" and "(?:api|marketingapi|entertainment)" in pattern:
            extra = ", max-size=4194304"
        scripts.append(
            f"helloobike_{i} = type={req_type}, pattern={pattern}, "
            f"requires-body=true, script-path={ADAPTED_JS_URL}{extra}"
        )

    mitm_hosts = None
    m = HOSTNAME_RE.search(text)
    if m:
        mitm_hosts = ", ".join(h.strip() for h in m.group(1).split(",") if h.strip())

    if not url_rewrites:
        fail("上游没有解析出任何 reject-200 规则")
    if not scripts:
        fail("上游没有解析出任何脚本规则")
    if not mitm_hosts:
        fail("上游没有 hostname 行")

    out = []
    out.append(f"#!name = {HEADER_NAME}")
    out.append(f"#!desc = {HEADER_DESC}")
    out.append(f"#!category = {HEADER_CATEGORY}")
    out.append(f"#!author = {HEADER_AUTHOR}")
    out.append("")
    out.append(f"# 转换自 QX 格式，上游：{UPSTREAM_SNIPPET_URL}")
    out.append(f"# 脚本：上游 easybike-ad.js 经 Surge 适配后存于本仓库 Surge/Script/easybike-ad_surge.js，模块不直接指向 QX 原版；")
    out.append("# 其中 script-echo-response 在 Surge 下以 http-response 实现（覆盖上游响应，状态已改为数字）。")
    out.append("")
    out.append("[Script]")
    out.extend(scripts)
    out.append("")
    out.append("[URL Rewrite]")
    out.extend(url_rewrites)
    out.append("")
    out.append("[MITM]")
    out.append(f"hostname = %APPEND% {mitm_hosts}")
    return "\n".join(out) + "\n"


def adapt_js(js_text):
    # 先确认上游结构未变，否则适配点对不上时直接失败，不发布半适配脚本。
    for marker in ("HelloBikeQXKeyCacheV1", "hbeContextKey", "HelloBikeQXRequestV2_",
                   '"HTTP/1.1 200 OK"', '"HTTP/1.1 503 Service Unavailable"'):
        if marker not in js_text:
            fail(f"上游 JS 缺少预期标记（结构可能已变，已中止）：{marker}")

    # 1. hbeContextKey：用完整请求 ID 作键，不再哈希到 64 槽位。
    # QX 的 64 槽位设计依赖 sessionIndex 顺序递增；Surge 的 $request.id
    # 不是顺序数字，哈希后并发请求极易撞槽，导致部分响应取错上下文。
    _hbe_new = ("function hbeContextKey(hbeID) {\n"
                "    var hbeIDStr = String(hbeID || \"\");\n"
                "    if (!hbeIDStr || hbeIDStr === \"undefined\" || hbeIDStr.length > 256) return \"\";\n"
                "    return \"HelloBikeQXRequestV2_\" + hbeIDStr.replace(/[^A-Za-z0-9_.-]/g, \"_\");\n"
                "}")
    js_text, _hbe_n = re.subn(r'function hbeContextKey\(hbeID\) \{.*?\n\}', lambda m: _hbe_new, js_text, count=1, flags=re.DOTALL)
    if _hbe_n != 1:
        fail("hbeContextKey 函数未匹配到恰好 1 处，上游可能已改写该函数")

    # 钱包模块匹配放宽：只要模块名是 LEGO_MY_PAGE_MY_WALLET 就删。
    # 原版 5 道门全过才删，用户账号上某道门对不上导致钱包金融整排残留，
    # 用户已选直接放宽（接受同模块内余额显示一并消失的风险）。
    _hbe_wallet_new = ("function hbeMyWalletMatches(hbeModule, hbeNumbers) {\n"
                       "    return !!(hbeModule && typeof hbeModule === \"object\" && !Array.isArray(hbeModule) && hbeModule.moduleKey === \"LEGO_MY_PAGE_MY_WALLET\" && hbeModule.moduleData && typeof hbeModule.moduleData === \"object\" && !Array.isArray(hbeModule.moduleData));\n"
                       "}")
    js_text, _hbe_wallet_n = re.subn(r'function hbeMyWalletMatches\(hbeModule, hbeNumbers\) \{.*?\n\}', lambda m: _hbe_wallet_new, js_text, count=1, flags=re.DOTALL)
    if _hbe_wallet_n != 1:
        fail("hbeMyWalletMatches 函数未匹配到恰好 1 处，上游可能已改写该函数")

    # 2. echo 分支状态字符串 -> 数字。
    for old, new in (('"HTTP/1.1 200 OK"', "200"),
                     ('"HTTP/1.1 503 Service Unavailable"', "503")):
        if js_text.count(old) != 1:
            fail(f"echo 状态 {old} 在上游出现次数不是 1（实际 {js_text.count(old)}），已中止")
        js_text = js_text.replace(old, new)

    if '"HTTP/1.1' in js_text:
        fail("适配后仍残留 HTTP/1.1 状态字符串，已中止")

    return SHIM + js_text


def write_if_changed(path, new_text, label):
    try:
        with open(path, "r", encoding="utf-8") as f:
            old_text = f.read()
    except FileNotFoundError:
        old_text = None
    if old_text is not None and old_text == new_text:
        print(f"sync_helloobike: {label}无变化，跳过写入")
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
    print(f"sync_helloobike: 已写入 {path}")
    return True


def main(argv):
    snippet_file = None
    js_file = None
    output_module = DEFAULT_MODULE_OUTPUT
    output_js = DEFAULT_JS_OUTPUT
    i = 0
    while i < len(argv):
        if argv[i] == "--snippet-file":
            i += 1
            snippet_file = argv[i]
        elif argv[i] == "--js-file":
            i += 1
            js_file = argv[i]
        elif argv[i] == "--output-module":
            i += 1
            output_module = argv[i]
        elif argv[i] == "--output-js":
            i += 1
            output_js = argv[i]
        else:
            fail(f"未知参数：{argv[i]}")
        i += 1

    snippet_text = fetch_text(UPSTREAM_SNIPPET_URL, snippet_file)
    js_text = fetch_text(UPSTREAM_JS_URL, js_file)
    module_text = convert_snippet(snippet_text)
    adapted_js = adapt_js(js_text)

    write_if_changed(output_module, module_text, "模块")
    write_if_changed(output_js, adapted_js, "适配脚本")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
