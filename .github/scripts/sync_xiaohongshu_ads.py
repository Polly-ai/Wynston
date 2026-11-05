#!/usr/bin/env python3
"""Strict, transactional XiaoHongShuAds -> Surge sync (Python stdlib + Node 22)."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.parse
import urllib.request

CONFIG_URL = "https://ddgksf2013.top/rewrite/XiaoHongShuAds.conf"
JS_URL = "https://ddgksf2013.top/scripts/redbook.ads.js"
ROOT = Path(__file__).resolve().parents[2]
MODULE = Path("Surge/Module/XiaoHongShuAds.sgmodule")
JAVASCRIPT = Path("Surge/JavaScript/XiaoHongShu/redbook.ads.js")
MIRROR = "https://raw.githubusercontent.com/Polly-ai/Wynston/main/" + JAVASCRIPT.as_posix()
NODE_TEST = Path(__file__).with_name("test_xiaohongshu_ads.cjs")
PREFIX = r"^https?:\/\/[a-z]+\.xiaohongshu\.com\/"
SCRIPT_PATHS = (
    r"api\/sns\/v\d+\/note\/tabfeed",
    r"api\/sns\/v\d+\/note\/video\/save",
    r"api\/sns\/v\d+\/note\/live_photo\/save",
    r"api\/sns\/v\d+\/search\/notes\?",
    r"api\/sns\/v\d+\/note\/widgets",
    r"api\/sns\/v\d+\/note\/redtube\?",
    r"api\/sns\/v\d+\/note\/videofeed\?",
    r"api\/sns\/v\d+\/note\/feed\?",
    r"api\/sns\/v\d+\/note\/imagefeed",
    r"api\/sns\/v\d+\/system_service\/splash_config",
    r"api\/sns\/v\d+\/homefeed\?",
    r"api\/sns\/v\d+\/system_service\/config\?",
    r"api\/sns\/v\d+\/search\/hot_list",
    r"api\/sns\/v\d+\/search\/hint",
    r"api\/sns\/v\d+\/homefeed\/categories",
    r"api\/sns\/v\d+\/search\/trending",
)
REJECT_PATHS = (
    r"api\/sns\/v\d+\/search\/notes\/recommend_info\?",
    r"api\/sns\/v\d+\/system_service\/splash",
    r"api\/gslb", r"api\/httpdns", r"api\/sns\/v\d+\/(tag\/)?ads",
    r"v\d+\/stateReport", r"data\/native\/matrix_switches",
    r"api\/sns\/v\d+\/user\/teenager\/status",
    r"api\/sns\/v\d+\/guide\/home_guide",
)
DISABLED = PREFIX + r"api\/sns\/v\d+\/note\/comment\/list"
EXPECTED = {(PREFIX + path, "script-response-body", False) for path in SCRIPT_PATHS}
EXPECTED |= {(PREFIX + path, "reject-200", False) for path in REJECT_PATHS}
EXPECTED.add((DISABLED, "script-response-body", True))


class ReviewRequired(ValueError):
    """Fail closed on source/grammar/interface drift; leave published files intact."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class StrictRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReviewRequired("Upstream redirect requires host/path review")


def download(url: str, limit: int) -> bytes:
    if url not in {CONFIG_URL, JS_URL}:
        raise ReviewRequired("Unapproved upstream URL")
    if urllib.parse.urlsplit(url).hostname != "ddgksf2013.top":
        raise ReviewRequired("Unapproved source host")
    opener = urllib.request.build_opener(
        StrictRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    request = urllib.request.Request(url, headers={
        "User-Agent": "surge", "Accept": "*/*", "Accept-Encoding": "identity"})
    with opener.open(request, timeout=45) as response:
        if response.status != 200 or response.geturl() != url:
            raise ReviewRequired("Unexpected upstream response")
        content = response.read(limit + 1)
    if not content or len(content) > limit:
        raise ReviewRequired("Empty or oversized upstream response")
    return content


def parse_config(data: bytes) -> tuple[list[str], list[tuple[str, str, bool]]]:
    text = data.decode("utf-8", errors="strict")
    if "\x00" in text or text.startswith("\ufeff"):
        raise ReviewRequired("Invalid source encoding")
    comments, rules = [], []
    hostname_seen = False
    for number, original in enumerate(text.splitlines(), 1):
        line = original.strip()
        if not line:
            continue
        if line.startswith("//"):
            comments.append("#" + original[original.index("//") + 2:])
            continue
        if line == "hostname = *.xiaohongshu.com":
            if hostname_seen:
                raise ReviewRequired("Duplicate hostname directive")
            hostname_seen = True
            continue
        disabled = line.startswith(";")
        if disabled:
            line = line[1:]
        parts = line.split()
        if len(parts) not in (3, 4) or parts[1] != "url":
            raise ReviewRequired(f"Unknown config syntax at line {number}")
        pattern, _, action = parts[:3]
        if action == "script-response-body":
            if len(parts) != 4 or parts[3] != JS_URL:
                raise ReviewRequired(f"Script URL requires review at line {number}")
        elif action == "reject-200":
            if len(parts) != 3:
                raise ReviewRequired(f"Invalid reject at line {number}")
        else:
            raise ReviewRequired(f"Unknown action at line {number}")
        entry = (pattern, action, disabled)
        if entry not in EXPECTED:
            raise ReviewRequired(f"New pattern/action/enablement requires offline fixture review (line {number})")
        if entry in rules:
            raise ReviewRequired(f"Duplicate rule at line {number}")
        rules.append(entry)
    if not hostname_seen or set(rules) != EXPECTED:
        raise ReviewRequired("Hostname/rule deletion/count drift requires review")
    return comments, rules


def render(config: bytes, javascript: bytes) -> bytes:
    comments, rules = parse_config(config)
    javascript.decode("utf-8", errors="strict")
    if not javascript.strip() or b"function Env(" not in javascript:
        raise ReviewRequired("Unexpected/empty upstream JavaScript; review native Surge support")
    lines = [
        "#!name = 小红书净化",
        "#!desc = 墨鱼版完整净化与功能增强：开屏/信息流等去广告、隐私与青少年请求屏蔽、图片/Live 图片/短视频去水印。需启用重写与 MITM；仅阻断小红书域 UDP/443 QUIC；与 Feed 时间模块互斥。",
        "#!category = Polly-ai", "#!author = @ddgksf2013 (上游) / Polly-ai (Surge 转换)",
        "#!system = ios", "",
        "# 上游配置：" + CONFIG_URL, "# 上游脚本：" + JS_URL,
        "# 配置 SHA256：" + digest(config), "# 原始脚本 SHA256：" + digest(javascript),
        "# 完整转换：16 条活动响应脚本 + 9 条原生 HTTP 200 空体映射；1 条评论脚本保持禁用。",
        "# JavaScript 原样镜像，Env 原生支持 Surge；不改持久化键或去水印流程。",
        "# [Map Local] 需 Surge iOS 5.9.1+ / Mac 5.5.1+；启用重写并信任 MITM 证书。",
        "# QX udp_drop_list=443 -> [Rule] 仅 UDP 且目标端口 443 且 xiaohongshu.com 域；绝不全局阻断 UDP/443。",
        "# 规则需在其他可命中的放行规则之前；若模块规则顺序未生效，将相同 AND 规则放到主配置 [Rule] 顶部。",
        "# 与 rednote-feed-time 的 homefeed 响应脚本重叠；启用本模块时禁用旧 Feed 时间模块。",
        "# 同一请求只运行一个匹配响应脚本；未集成时间脚本，不承诺同时净化并显示时间。",
        "# 原始 splash 正则也匹配 splash_config；保留该重叠，不擅自收窄或改动作。",
        "", "# 上游说明（保留原文，Quantumult X 专用注意事项不是本模块的全局设置）：",
        *comments, "", "[Rule]",
        "AND,((PROTOCOL,UDP),(DST-PORT,443),(DOMAIN-SUFFIX,xiaohongshu.com)),REJECT",
        "", "[Script]",
    ]
    index = 0
    for pattern, action, disabled in rules:
        if action != "script-response-body":
            continue
        index += 1
        prefix = "# " if disabled else ""
        if disabled:
            lines.append("# 上游以分号 ; 禁用的 comment/list：保持禁用，未知原因不自动开启。")
            lines.append("# 上游原行：;" + pattern + " url " + action + " " + JS_URL)
        lines.append(prefix + f"xiaohongshu-ads-{index:02d} = type=http-response, pattern={pattern}, "
                     f"requires-body=true, max-size=1048576, timeout=10, script-update-interval=86400, script-path={MIRROR}")
    lines += ["", "[Map Local]", "# QX reject-200 -> 原生 HTTP 200、空正文、文本 Content-Type、禁止缓存；不是 404。"]
    for pattern, action, disabled in rules:
        if action == "reject-200":
            lines.append(("# " if disabled else "") + pattern + ' data-type=text data="" status-code=200 '
                         'header="Content-Type:text/plain; charset=utf-8|Cache-Control:no-store"')
    lines += ["", "[MITM]", "hostname = %APPEND% *.xiaohongshu.com", ""]
    return "\n".join(lines).encode("utf-8")


def validate_javascript(javascript: bytes, config: bytes) -> None:
    """No network/process/storage capability inside VM; every endpoint is tested offline."""
    with tempfile.TemporaryDirectory(prefix="xiaohongshu-validation-") as directory:
        js = Path(directory) / "redbook.ads.js"
        conf = Path(directory) / "XiaoHongShuAds.conf"
        js.write_bytes(javascript)
        conf.write_bytes(config)
        subprocess.run(["node", "--check", str(js)], check=True, timeout=30)
        subprocess.run(["node", str(NODE_TEST), str(js), str(conf)], check=True, timeout=90)


def replace_bundle(root: Path, files: dict[Path, bytes]) -> bool:
    """Validate before this call. Stage ALL bytes, then replace; rollback on errors.

    Publication atomicity is the single Git commit. A process crash before that
    cannot publish a partial bundle; ordinary local write failures are rolled back.
    """
    changed = {path: data for path, data in files.items()
               if not (root / path).exists() or (root / path).read_bytes() != data}
    if not changed:
        return False
    originals = {path: (root / path).read_bytes() if (root / path).exists() else None
                 for path in changed}
    staged, replaced = {}, []
    try:
        for path, data in changed.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                staged[path] = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(staged[path], 0o644)
        for path in changed:
            os.replace(staged[path], root / path)
            replaced.append(path)
    except BaseException:
        for path in reversed(replaced):
            target = root / path
            if originals[path] is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(originals[path])
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
    return True


def synchronize(root: Path = ROOT, config: bytes | None = None,
                javascript: bytes | None = None, check: bool = False) -> bool:
    if (config is None) != (javascript is None):
        raise ReviewRequired("Config and JavaScript must be supplied as a pair")
    if config is None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            cf = executor.submit(download, CONFIG_URL, 131072)
            jf = executor.submit(download, JS_URL, 1048576)
            config, javascript = cf.result(), jf.result()
    module = render(config, javascript)
    validate_javascript(javascript, config)
    files = {MODULE: module, JAVASCRIPT: javascript}
    changed = any(not (root / path).exists() or (root / path).read_bytes() != data
                  for path, data in files.items())
    if not check and changed:
        replace_bundle(root, files)
    print("Validated XiaoHongShuAds: 16 active scripts, 9 HTTP-200 maps, 1 disabled script")
    print("Source SHA256 config=" + digest(config) + " js=" + digest(javascript))
    print("Changes: " + ("yes" if changed else "no (deterministic no-op)"))
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Offline source config (requires --javascript)")
    parser.add_argument("--javascript", type=Path, help="Offline ORIGINAL JavaScript")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="Validate without writing")
    args = parser.parse_args()
    if bool(args.config) != bool(args.javascript):
        parser.error("--config and --javascript must be supplied together")
    synchronize(args.root, args.config.read_bytes() if args.config else None,
                args.javascript.read_bytes() if args.javascript else None, args.check)


if __name__ == "__main__":
    main()
