#!/usr/bin/env python3
"""Offline converter tests; no credentials and no network access required."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import sync_xiaohongshu_ads as sync


def fixture_config():
    header = (
        "// @ScriptName 小红书净化+功能增强[墨鱼版]\n"
        "// @Author @ddgksf2013\n"
        "// @MainFunction 去广告，图片、Live 图片及视频去水印\n"
        "// @Attention udp_drop_list=443\n"
        "hostname = *.xiaohongshu.com\n"
    )
    lines = [sync.PREFIX + path + " url script-response-body " + sync.JS_URL
             for path in sync.SCRIPT_PATHS]
    lines += [sync.PREFIX + path + " url reject-200" for path in sync.REJECT_PATHS]
    lines += [";" + sync.DISABLED + " url script-response-body " + sync.JS_URL]
    return (header + "\n".join(lines) + "\n").encode()


CONFIG = fixture_config()
MINIMAL_JS = b"function Env() {}\n// Synthetic converter fixture; never published.\n"


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.module = sync.render(CONFIG, MINIMAL_JS).decode()

    def test_fixed_identity_hashes_and_attribution(self):
        self.assertIn("#!name = 小红书净化\n", self.module)
        self.assertIn("#!category = Polly-ai\n", self.module)
        self.assertIn("# @Author @ddgksf2013", self.module)
        self.assertIn("# @MainFunction 去广告，图片、Live 图片及视频去水印", self.module)
        self.assertIn(sync.digest(CONFIG), self.module)
        self.assertIn(sync.digest(MINIMAL_JS), self.module)
        self.assertEqual(sync.render(CONFIG, MINIMAL_JS), sync.render(CONFIG, MINIMAL_JS))
        self.assertNotIn("sync time", self.module)

    def test_exact_counts_and_native_action(self):
        active = [line for line in self.module.splitlines() if line and not line.startswith("#")]
        scripts = [line for line in active if "type=http-response" in line]
        maps = [line for line in active if "data-type=" in line]
        self.assertEqual(len(scripts), 16)
        self.assertEqual(len(maps), 9)
        self.assertEqual([line.split("pattern=", 1)[1].split(", requires-body", 1)[0]
                          for line in scripts], [sync.PREFIX + p for p in sync.SCRIPT_PATHS])
        self.assertEqual([line.split(" data-type", 1)[0] for line in maps],
                         [sync.PREFIX + p for p in sync.REJECT_PATHS])
        for line in scripts:
            for option in ("requires-body=true", "max-size=1048576", "timeout=10",
                           "script-update-interval=86400", "script-path=" + sync.MIRROR):
                self.assertIn(option, line)
        for line in maps:
            self.assertIn('data-type=text data="" status-code=200', line)
            self.assertIn('header="Content-Type:text/plain; charset=utf-8|Cache-Control:no-store"', line)
        self.assertNotIn("reject404", self.module)
        self.assertNotIn("type=http-request", self.module)

    def test_disabled_comment_and_scoped_quic(self):
        self.assertIn("# xiaohongshu-ads-17 = type=http-response, pattern=" + sync.DISABLED, self.module)
        self.assertIn("# 上游原行：;" + sync.DISABLED, self.module)
        self.assertIn("保持禁用", self.module)
        self.assertIn("hostname = %APPEND% *.xiaohongshu.com", self.module)
        self.assertIn("AND,((PROTOCOL,UDP),(DST-PORT,443),(DOMAIN-SUFFIX,xiaohongshu.com)),REJECT", self.module)
        self.assertNotIn("DST-PORT,443,REJECT", self.module)
        self.assertIn("禁用旧 Feed 时间模块", self.module)
        self.assertIn("也匹配 splash_config", self.module)

    def test_keep_all_comments_and_rule_order(self):
        source = CONFIG.replace(b"hostname =", "// # > 自定义上游说明\nhostname =".encode())
        comments, rules = sync.parse_config(source)
        self.assertIn("# # > 自定义上游说明", comments)
        self.assertEqual(len(rules), 26)
        self.assertEqual(sum(not disabled for _, _, disabled in rules), 25)
        self.assertIn("# # > 自定义上游说明", sync.render(source, MINIMAL_JS).decode())

    def test_unknown_grammar_actions_or_source_hosts_fail_closed(self):
        bad = (
            CONFIG + b"[rewrite_local]\n",
            CONFIG + b"udp_drop_list=443\n",
            CONFIG.replace(b"reject-200", b"reject-404", 1),
            CONFIG.replace(sync.JS_URL.encode(), b"https://evil.example/test.js", 1),
            CONFIG.replace(sync.JS_URL.encode(), b"http://ddgksf2013.top/scripts/redbook.ads.js", 1),
            CONFIG.replace(b"*.xiaohongshu.com", b"*.example.com"),
            CONFIG.replace(b"hostname =", b"hostname = *\nhostname ="),
            CONFIG.replace(b";" + sync.DISABLED.encode(), sync.DISABLED.encode()),
            CONFIG.replace(b"note\\/tabfeed", b"note\\/newfeed"),
            CONFIG.replace(b" url reject-200", b" url reject-200 extra", 1),
            CONFIG + b"some garbage\n", b"<html>gateway error</html>",
            CONFIG + b"\x00", b"\xef\xbb\xbf" + CONFIG,
            CONFIG + CONFIG[CONFIG.index((sync.PREFIX + sync.SCRIPT_PATHS[0]).encode()):].splitlines()[0] + b"\n",
        )
        for item in bad:
            with self.subTest(source=item[:30]):
                with self.assertRaises((sync.ReviewRequired, UnicodeDecodeError)):
                    sync.parse_config(item)
        with self.assertRaises(sync.ReviewRequired):
            sync.parse_config(CONFIG.replace((sync.PREFIX + sync.REJECT_PATHS[0] + " url reject-200\n").encode(), b""))

    def test_redirects_and_unapproved_download_url(self):
        with self.assertRaises(sync.ReviewRequired):
            sync.download("http://ddgksf2013.top/scripts/redbook.ads.js", 100)
        with self.assertRaises(sync.ReviewRequired):
            sync.StrictRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example/")

    def test_invalid_script(self):
        for javascript in (b"", b"<html>error</html>", b"\xff"):
            with self.assertRaises((sync.ReviewRequired, UnicodeDecodeError)):
                sync.render(CONFIG, javascript)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for path, data in ((sync.MODULE, b"previous-module"), (sync.JAVASCRIPT, b"previous-js")):
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_bytes(data)

    def assert_previous(self):
        self.assertEqual((self.root / sync.MODULE).read_bytes(), b"previous-module")
        self.assertEqual((self.root / sync.JAVASCRIPT).read_bytes(), b"previous-js")

    def test_validation_failure_never_writes(self):
        with mock.patch.object(sync, "validate_javascript", side_effect=RuntimeError("fixture failed")):
            with self.assertRaises(RuntimeError):
                sync.synchronize(self.root, CONFIG, MINIMAL_JS)
        self.assert_previous()
        with self.assertRaises(sync.ReviewRequired):
            sync.synchronize(self.root, CONFIG + b"unknown line\n", MINIMAL_JS)
        self.assert_previous()

    def test_failed_second_download_never_writes(self):
        def download(url, limit):
            if url == sync.JS_URL:
                raise OSError("network failed")
            return CONFIG
        with mock.patch.object(sync, "download", side_effect=download):
            with self.assertRaises(OSError):
                sync.synchronize(self.root)
        self.assert_previous()

    def test_write_failure_rolls_back_bundle(self):
        real_replace = sync.os.replace
        count = 0
        def replace(source, destination):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("injected second replace failure")
            return real_replace(source, destination)
        with mock.patch.object(sync.os, "replace", side_effect=replace):
            with self.assertRaises(OSError):
                sync.replace_bundle(self.root, {sync.MODULE:b"new-module", sync.JAVASCRIPT:b"new-js"})
        self.assert_previous()
        self.assertEqual(len(list((self.root / sync.MODULE).parent.iterdir())), 1)

    def test_check_noop_and_original_bytes(self):
        with mock.patch.object(sync, "validate_javascript"), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(sync.synchronize(self.root, CONFIG, MINIMAL_JS, check=True))
            self.assert_previous()
            self.assertTrue(sync.synchronize(self.root, CONFIG, MINIMAL_JS))
            self.assertEqual((self.root / sync.JAVASCRIPT).read_bytes(), MINIMAL_JS)
            before = (self.root / sync.MODULE).stat().st_mtime_ns
            self.assertFalse(sync.synchronize(self.root, CONFIG, MINIMAL_JS))
            self.assertEqual((self.root / sync.MODULE).stat().st_mtime_ns, before)
            with self.assertRaises(sync.ReviewRequired):
                sync.synchronize(self.root, CONFIG, None)


class RealUpstreamFixtureTests(unittest.TestCase):
    def test_mirrored_original_native_surge_and_every_endpoint(self):
        javascript = (sync.ROOT / sync.JAVASCRIPT).read_bytes()
        sync.validate_javascript(javascript, CONFIG)


if __name__ == "__main__":
    unittest.main(verbosity=2)
