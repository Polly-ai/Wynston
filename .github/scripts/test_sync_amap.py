#!/usr/bin/env python3
"""Offline tests for strict Amap conversion and no-op updates."""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sync_amap", HERE / "sync_amap.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

SAMPLE = r'''// @Version V1.0.test
// @UpdateTime 2026-11-06
hostname = m5.amap.com, ai.amap.com
host-suffix, optimus-ads.amap.com, direct
# > empty response
^https?:\/\/.*\.amap\.com\/splash url reject-200
# > json response
^https?:\/\/.*\.amap\.com\/dict url reject-dict
# > plain reject
^https?:\/\/.*\.amap\.com\/ads url reject
# > transparent image
^https?:\/\/.*\.amap\.com\/image url reject-img
# > body script
^https?:\/\/.*\.amap\.com\/notice url script-response-body https://raw.githubusercontent.com/ddgksf2013/Scripts/refs/heads/master/amap.js
'''


class ConverterTests(unittest.TestCase):
    def test_metadata_name_and_comment_token_cleanup(self):
        tagged = SAMPLE.replace("# > empty response",
                                "# > empty response@ddgksf2013；保留正文")
        module, assets = sync.convert(tagged)
        self.assertEqual(module.splitlines()[0], "#!name = 高德地图净化")
        self.assertIn("#!category = Polly-ai", module)
        self.assertIn("#!author = \n", module)
        self.assertIn("# > empty response；保留正文", module)
        self.assertNotIn("[墨鱼版]", module)
        self.assertNotIn("@ddgksf2013", module)
        original_comments = [line for line in tagged.splitlines() if line.startswith("# >")]
        rendered_comments = [line for line in module.splitlines() if line.startswith("# >")]
        self.assertCountEqual(rendered_comments,
                              [line.replace("@ddgksf2013", "") for line in original_comments])
        self.assertIn("DOMAIN-SUFFIX,optimus-ads.amap.com,DIRECT", module)
        self.assertIn("hostname = %APPEND% m5.amap.com, ai.amap.com", module)
        self.assertIn("# 上游版本：V1.0.test", module)
        self.assertEqual(len(assets), 1)

    def test_200_is_not_404(self):
        module, _ = sync.convert(SAMPLE)
        line = next(line for line in module.splitlines() if "pattern=" in line and "/splash" in line)
        self.assertIn("type=http-request", line)
        self.assertIn("amap-reply.js", line)
        self.assertNotIn("/splash _ reject", module)
        self.assertIn("status: 200", sync.REPLY_JS)
        self.assertIn('body: ""', sync.REPLY_JS)

    def test_reply_semantics(self):
        module, _ = sync.convert(SAMPLE)
        lines = module.splitlines()
        for endpoint, mode in (("/dict", "dict"), ("/image", "image")):
            line = next(line for line in lines if "pattern=" in line and endpoint in line)
            self.assertIn("type=http-request", line)
            self.assertIn(f"argument={mode}", line)
            self.assertIn("requires-body=false", line)
        image = next(line for line in lines if "argument=image" in line)
        self.assertIn("binary-body-mode=true", image)
        self.assertIn(r"\/ads _ reject", module)
        rewrites = [line for line in lines if line.startswith("^")]
        self.assertTrue(all(line.endswith(" _ reject") for line in rewrites))
        self.assertNotIn(" _ reject-dict", module)
        self.assertNotIn(" _ reject-img", module)

    def test_scripts(self):
        module, assets = sync.convert(SAMPLE)
        self.assertIn("type=http-response", module)
        self.assertIn("requires-body=true, max-size=1048576", module)
        self.assertIn("https://raw.githubusercontent.com/Polly-ai/Wynston/main/Surge/JavaScript/Amap/amap.js", module)
        self.assertEqual(list(assets.values()), ["amap.js"])

    def test_deterministic(self):
        self.assertEqual(sync.convert(SAMPLE), sync.convert(SAMPLE))
        self.assertIn(hashlib.sha256(SAMPLE.encode()).hexdigest(), sync.convert(SAMPLE)[0])

    def test_unknown_upstream_fails_closed(self):
        for bad in ("unexpected = true", "^https://amap.com/foo url unsupported",
                    "^https://amap.com/foo url reject-dict https://invalid.com/foo.js"):
            with self.subTest(bad=bad), self.assertRaises(sync.SyncError):
                sync.convert(SAMPLE + bad + "\n")

    def test_missing_data(self):
        for broken in ("", SAMPLE.replace("hostname =", "# hostname ="),
                       SAMPLE.replace("url script-response-body", "url bad-action")):
            with self.subTest(broken=broken), self.assertRaises(sync.SyncError):
                sync.convert(broken)

    def test_wrapped_sources(self):
        wrapped = SAMPLE.replace("hostname = m5.amap.com, ai.amap.com", "hostname = m5.amap.com,\nai.amap.com")
        wrapped = wrapped.replace("url script-response-body https://", "url script-response-body\nhttps://")
        module, assets = sync.convert(wrapped)
        self.assertIn("hostname = %APPEND% m5.amap.com, ai.amap.com", module)
        self.assertEqual(len(assets), 1)

    def test_duplicate_patterns(self):
        duplicate = next(line for line in SAMPLE.splitlines() if "url reject-200" in line)
        with self.assertRaises(sync.SyncError):
            sync.convert(SAMPLE + duplicate)

    def test_unexpected_script_source(self):
        for bad in ("https://untrusted.invalid/amap.js", "http://raw.githubusercontent.com/ddgksf2013/Scripts/master/amap.js"):
            with self.subTest(bad=bad), self.assertRaises(sync.SyncError):
                sync.convert(SAMPLE.replace("https://raw.githubusercontent.com/ddgksf2013/Scripts/refs/heads/master/amap.js", bad))

    def test_noop_does_not_touch_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "module.sgmodule"
            self.assertTrue(sync.write_changed(path, "valid\n"))
            modified = path.stat().st_mtime_ns
            self.assertFalse(sync.write_changed(path, "valid\n"))
            self.assertEqual(path.stat().st_mtime_ns, modified)
            self.assertTrue(sync.write_changed(path, "updated\n"))
            self.assertEqual(path.read_text(), "updated\n")
            self.assertFalse(path.with_name(path.name + ".sync-tmp").exists())

    def test_reply_script_in_surge_vm(self):
        sync.validate_js({"amap-reply.js": sync.REPLY_JS})


if __name__ == "__main__":
    unittest.main(verbosity=2)
