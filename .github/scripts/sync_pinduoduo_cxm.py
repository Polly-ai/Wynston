#!/usr/bin/env python3
"""把上游 Surge 模块 https://raw.githubusercontent.com/CaoXiaoMann/XiaoMan/main/Surge/Scripts/Pinduoduo/Pinduoduo.sgmodule 同步到本仓库，并每日跟随上游更新。

上游本身已是 Surge 模块格式：头部 #! 注释、[Rule]、[Map Local]、[Body Rewrite]、
[MITM]，以及段落内的说明注释。同步时只改写头部三项和脚本地址，
其余内容原样保留：上游的 #! 头部注释（author、homepage、version、openUrl、
system、raw-url，以及上游今后新增的任何 #! 项）全部跟随上游带上，
只有 name、category 按用户指定固定不变。
（上游 v16 自 2026-11-14 起删掉了 [Script] 段，改为零 JS 机制；
 [Script] 现为可选段落：上游有则同步镜像，无则跳过。）

用法（仓库工作流里不带参数跑，默认抓上游、写到仓库路径）：
    python3 .github/scripts/sync_pinduoduo_cxm.py
本地测试：
    python3 .github/scripts/sync_pinduoduo_cxm.py --from-file /tmp/Pinduoduo.sgmodule --output /tmp/out.sgmodule

改写规则：
  - #!name 固定为“拼多多净化”（用户指定，不跟上游的“拼多多去广告”）。
  - #!desc 随上游原文，不改写（用户指定“模块备注不变”）。
  - #!category 固定为 Polly-ai（用户指定）。
  - 其余 #! 头部注释全部随上游原文带上（author、homepage、version、openUrl、
    system、raw-url，以及上游今后新增的任何 #! 项），按上游原有顺序输出。
  - [Rule]、[Map Local]、[Body Rewrite]、[MITM] 及段落内注释全文原样保留。
  - 同步时按 COMMENTS 表给 [Rule]、[Body Rewrite]、[Map Local]、[MITM] 的
    每组规则上方插入 # > 注释（用户写法）；上游新增条目时需在 COMMENTS 里
    补注释，缺失时只在日志里警告，不中断同步。
  - 若上游有 [Script]：两个 [Script] 段落合并为一个（内容不变），脚本一律指向
    自托管地址（SELF_HOSTED 列表），不直接引用第三方 js；同步时同时抓上游 js
    更新自托管镜像文件。上游无 [Script] 时跳过镜像（v16 起即如此）。
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
REQUIRED_SECTIONS = ("[Rule]", "[Map Local]", "[Body Rewrite]", "[MITM]")
# [Script] 自上游 v16（2026-11-14）起不再是必要段落：上游删掉了 [Script]，
# 同步时跳过镜像（见 main）。
# 头部注释：除 name/desc/category 外，上游的全部 #! 项都原样带上（按上游顺序输出），
# 不再用固定白名单（2026-11-15 用户要求：上游每行的注释都带上）。
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

# 段落注释：(匹配子串, 注释)。同步时把注释插到第一条匹配行的上方，
# 格式与用户写法一致：# > 说明。匹配子串取自上游原文中能唯一确定
# 该行（或该组首行）的片段；同一注释只插一次，组内其余行不再重复。
# 上游 v16 的四个段落本身没有任何注释行，这些注释是按规则实际作用
# 新写的（从规则原文直接推断，不编造）；目的不确定的域名只按组写
# 通用注释。上游新增条目时需在这里补注释；map 里的 key 在上游找
# 不到时只打印警告，不中断同步。
COMMENTS = [
    # [Rule]
    ("((25[0-5]", "拦截直连 IP 的上报请求"),
    ("PROTOCOL,QUIC", "禁用 api.pinduoduo.com 的 QUIC"),
    ("titan.pinduoduo.com,REJECT-NO-DROP", "拦截埋点、上报与广告相关域名"),
    # [Body Rewrite]
    ("irregular_banner_dy", "首页 hub：删底部视频/不规则 banner"),
    ('delpaths([["result","icon_set"]])', "首页 hub：删图标集"),
    ("search_bar_hot_query", "首页 hub：删搜索框热词"),
    ("timeline_visible", "关闭首页信息流 timeline、删 timeline 模"),
    ("最快明天达|政府补贴", "顶部入口删「最快明天达/政府补贴」"),
    ('delpaths([["expansion"]])', "搜索：删搜索扩展"),
    ("monthly_card_entrance", "个人中心：删月卡入口"),
    ("personal_center_style_v2_vo", "个人中心：删个人中心样式"),
    ('["icon_set","icons"]', "个人中心：删图标与描述文字"),
    ("entrance_text", "个人中心：清空钱包入口文字"),
    ("bottom_section_list", "订单渲染：删底部区域"),
    ("float_info", "订单渲染：删直播浮层信息"),
    ("goods_list", "订单详情：删商品推荐列表"),
    ("marketing_banner_vo", "订单页：删营销横幅"),
    ("banner_above_recommend", "订单页：删物流上方推荐"),
    ("order_growth_tip", "订单列表：删订单成长提示"),
    # [Map Local]
    ("unrated_order_for_unreceived_tab", "未收货订单评价入口，返回置空"),
    ("query_order_list_tabs_element", "订单列表 tabs 元素，返回置空"),
    ("aquarius\\/hungary\\/global\\/homepage", "全球首页接口，返回置空"),
    ("query\\/order_express_group", "订单快递信息接口，返回置空"),
    ("search_hotquery", "搜索热词接口，返回置空"),
    ("get_list_data", "聊天资源列表接口，返回置空"),
    ("new_chat_group", "新聊天组接口，返回置空"),
    ("goods\\/back_up", "商品备用接口，返回置空"),
    ("query\\/personal", "个人信息查询接口，返回置空"),
    ("bybt_guide", "商品详情引导接口，返回置空"),
    ("require\\/append", "追加评价接口，返回置空"),
    ("my_order_group", "我的订单组接口，返回置空"),
    ("query\\/likes", "喜欢列表接口，返回置空"),
    ("gbdbpdv\\/extra", "附加数据接口，返回置空"),
    ("shortcut\\/list", "跨店快捷入口列表，返回置空"),
    ("liveactivity\\/push\\/create\\/url\\/report", "直播活动推送上报接口，返回置空"),
    ("index\\/gather", "成长聚合接口，返回置空"),
    ("wait\\/receive\\/review", "待收货评价接口，返回置空"),
    ("nasus\\/recommend", "推荐接口，返回置空"),
    # [MITM]
    ("hostname = %APPEND% api.pinduoduo.com", "解密 api.pinduoduo.com（改写与映射生效的前提）"),
]


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
    for key, value in meta.items():
        if key in ("name", "desc", "category"):
            continue
        out.append(f"#!{key} = {value}")
    out += ["", f"# 同步自上游：{UPSTREAM_URL}", ""]
    used_comments = set()
    for seg in parts["segments"]:
        if seg["name"]:
            out.append(seg["name"])
        for line in seg["lines"]:
            if seg["name"] == "[Script]" and line.strip():
                out.append(rewrite_script_line(line, mirrored))
                continue
            if line.strip():
                for idx, (key, comment) in enumerate(COMMENTS):
                    if idx not in used_comments and key in line:
                        out.append(f"# > {comment}")
                        used_comments.add(idx)
                        break
            out.append(line)
    for idx, (key, comment) in enumerate(COMMENTS):
        if idx not in used_comments:
            print(
                f"sync_pinduoduo_cxm: 警告：注释未匹配到上游行（上游可能删改了这条规则），"
                f"请检查 COMMENTS：{key!r} -> {comment}",
                file=sys.stderr,
            )
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
    # v16（2026-11-14）起上游无 [Script] 段：无脚本可镜像时跳过抓取；
    # 上游若恢复 [Script]，仍按旧逻辑镜像。
    has_script = any(s["name"] == "[Script]" for s in parts["segments"])
    scripts_to_mirror = SCRIPTS if has_script else []
    if not has_script:
        print("sync_pinduoduo_cxm: 上游无 [Script] 段，跳过脚本镜像")
    for name, js_url, asset_path in scripts_to_mirror:
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
