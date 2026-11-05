#!/usr/bin/env python3
"""Offline tests for CaiYun Surge conversion, including requested VIP flags."""
import importlib.util
import re
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("sync_caiyun_ads", Path(__file__).with_name("sync_caiyun_ads.py"))
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
URL = sync.SCRIPT_URL
VIP1 = r"^https?:\/\/biz\.cyapi\.cn\/api\/v\d\/user_detail"
VIP2 = r"^https?:\/\/biz\.cyapi\.cn\/v\d\/user"
ACTIVITY = r"^https?:\/\/wrapper\.cyapi\.cn\/v\d\/activity"
AD = r"^https?:\/\/ad\.cyapi\.cn\/v\d"
CONFIG = ("// @Version V1.0.test\n// @UpdateTime 2026-11-06\n"
          "hostname = wrapper.cyapi.cn, ad.cyapi.cn\n# > client VIP flag\n"
          + VIP1 + " url script-response-body " + URL + "\n"
          + VIP2 + " url script-response-body " + URL + "\n# > activity ad\n"
          + ACTIVITY + " url script-response-body " + URL + "\n"
          + AD + " url reject-200\n")
SOURCE = "// upstream attribution\n$done({body:$response.body});\n"


class CaiYunTests(unittest.TestCase):
    def test_membership_patterns_retained(self):
        hosts, rules, vips = sync.parse(CONFIG)
        self.assertEqual(set(vips), {VIP1, VIP2})
        self.assertEqual(len(rules), 4)
        self.assertEqual([mode for _,mode,_ in rules], ["vip","vip","response","empty"])
        module = sync.render(CONFIG, SOURCE)
        self.assertIn("pattern=" + VIP1, module)
        self.assertIn("pattern=" + VIP2, module)

    def test_explicit_biz_mitm_append(self):
        hosts, _, _ = sync.parse(CONFIG)
        self.assertEqual(hosts, ["wrapper.cyapi.cn", "ad.cyapi.cn", "biz.cyapi.cn"])
        module = sync.render(CONFIG, SOURCE)
        self.assertIn("hostname = %APPEND% wrapper.cyapi.cn, ad.cyapi.cn, biz.cyapi.cn", module)
        self.assertNotIn("%APPEND% *", module)

    def test_no_duplicate_biz_hostname(self):
        text = CONFIG.replace("hostname = wrapper.cyapi.cn, ad.cyapi.cn", "hostname = wrapper.cyapi.cn, ad.cyapi.cn, biz.cyapi.cn")
        hosts, _, _ = sync.parse(text)
        self.assertEqual(hosts.count("biz.cyapi.cn"), 1)

    def test_does_not_add_biz_without_membership_rule(self):
        text = "\n".join(line for line in CONFIG.splitlines() if not line.startswith(tuple(sync.VIP_PATTERNS)))
        hosts, _, vips = sync.parse(text)
        self.assertEqual(vips, [])
        self.assertNotIn("biz.cyapi.cn", hosts)

    def test_metadata_fixed(self):
        module = sync.render(CONFIG, SOURCE)
        self.assertIn("#!category = Polly-ai", module)
        self.assertIn("#!name = 彩云天气 增强\n", module)
        self.assertNotIn("@ddgksf2013", module)
        self.assertNotIn("墨鱼版", module)
        self.assertIn("≤7.20.2", module)
        self.assertIn("不代表真实订阅", module)
        self.assertIn("V1.0.test", module)
        self.assertIn("# > client VIP flag", module)

    def test_requested_comment_cleanup_preserves_explanations_and_rules(self):
        text = CONFIG.replace("# > client VIP flag", "# > client VIP flag @ddgksf2013")
        text = text.replace("# > activity ad", "# > activity ad@ddgksf2013")
        text = text.replace(AD + " url reject-200", "# > general ad request@ddgksf2013\n" + AD + " url reject-200")
        cleaned = sync.render(text, SOURCE)
        self.assertNotIn("@ddgksf2013", cleaned)
        self.assertIn("# > client VIP flag\n", cleaned)
        self.assertIn("# > activity ad\n", cleaned)
        self.assertIn("# > general ad request\n", cleaned)
        before = [line for line in sync.render(CONFIG, SOURCE).splitlines()
                  if "pattern=" in line or line.startswith("^")]
        after = [line for line in cleaned.splitlines()
                 if "pattern=" in line or line.startswith("^")]
        self.assertEqual(before, after)
        self.assertIn("#!name = 彩云天气 增强\n", cleaned)

    def test_surge_response_parameters(self):
        module = sync.render(CONFIG, SOURCE)
        response = [line for line in module.splitlines() if "type=http-response" in line]
        self.assertEqual(len(response), 3)
        for line in response:
            self.assertIn("requires-body=true, max-size=1048576", line)
            self.assertIn("caiyun-surge.js", line)
            self.assertIn("script-update-interval=86400, timeout=10", line)
        self.assertNotIn("binary-body-mode", module)

    def test_reject200_uses_native_map_local(self):
        module = sync.render(CONFIG, SOURCE)
        section = module.split("\n[Map Local]\n", 1)[1].split("\n[MITM]\n", 1)[0]
        line = next(line for line in section.splitlines() if line.startswith("^"))
        pattern, parameters_text = line.split(maxsplit=1)
        self.assertEqual(pattern, AD)
        parameters = dict(part.split("=", 1) for part in shlex.split(parameters_text))
        self.assertEqual(parameters["data-type"], "text")
        self.assertEqual(parameters["data"], "")
        self.assertEqual(parameters["status-code"], "200")
        self.assertIn("Content-Type:text/plain; charset=utf-8", parameters["header"])
        self.assertNotIn("type=http-request", module)
        self.assertNotIn("caiyun-reply.js", module)
        self.assertNotIn(" _ reject", module)

    def test_all_original_patterns_preserved(self):
        before = [line.split()[0] for line in CONFIG.splitlines() if line.startswith("^")]
        after = [line.split("pattern=",1)[1].split(", ",1)[0] if "pattern=" in line else line.split()[0]
                 for line in sync.render(CONFIG,SOURCE).splitlines() if "pattern=" in line or line.startswith("^")]
        self.assertEqual(before,after)

    def test_source_preserved_and_output_stable(self):
        bridge = sync.build_bridge(SOURCE)
        self.assertIn(SOURCE,bridge)
        self.assertIn(sync.sha(SOURCE),bridge)
        self.assertEqual(bridge,sync.build_bridge(SOURCE))
        module = sync.render(CONFIG,SOURCE)
        self.assertEqual(module,sync.render(CONFIG,SOURCE))
        self.assertIn(sync.sha(CONFIG),module)
        self.assertNotEqual(module,sync.render(CONFIG,SOURCE+"// update\n"))

    def test_no_shared_authentication_api(self):
        bridge = sync.build_bridge(SOURCE)
        for term in ("$httpClient", "$task", "$persistentStore", "$prefs", "Cookie", "Authorization"):
            self.assertNotIn(term,bridge)

    def test_unknown_rule_requires_review(self):
        for text in ("setting = true", "^https://unknown.example/ url reject-200",
                     r"^https?:\/\/ad\.cyapi\.cn\/new url reject"):
            with self.subTest(text=text), self.assertRaises(sync.SyncError):
                sync.parse(CONFIG+text+"\n")

    def test_unknown_hostname_requires_review(self):
        for host in ("*.cyapi.cn", "unrelated.example"):
            with self.subTest(host=host), self.assertRaises(sync.SyncError):
                sync.parse(CONFIG+"hostname = "+host+"\n")

    def test_script_source_and_action_are_validated(self):
        for text in (CONFIG.replace(URL,"https://untrusted.example/test.js"),
                     CONFIG.replace("script-response-body","script-request-header"),
                     CONFIG.replace("url reject-200","url reject-dict")):
            with self.subTest(text=text), self.assertRaises(sync.SyncError):
                sync.parse(text)

    def test_duplicate_and_incomplete_inputs(self):
        for text in ("", "hostname = wrapper.cyapi.cn\n", CONFIG+AD+" url reject-200\n"):
            with self.subTest(text=text), self.assertRaises(sync.SyncError):
                sync.parse(text)

    def test_noop_preserves_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"file.js"
            self.assertTrue(sync.write_changed(path,"keep\r\n"))
            before = path.stat().st_mtime_ns
            self.assertFalse(sync.write_changed(path,"keep\r\n"))
            self.assertEqual(before,path.stat().st_mtime_ns)
            self.assertEqual(path.read_bytes(),b"keep\r\n")

    def test_failed_validation_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config,source = root/"input.conf",root/"source.js"
            config.write_text(CONFIG); source.write_text(SOURCE)
            target = root/sync.MODULE_PATH
            sync.write_changed(target,"previous valid module\n")
            with patch.object(sync,"prepare",side_effect=sync.SyncError("test failure")):
                result = sync.main(["--from-file",str(config),"--script-file",str(source),"--root",str(root)])
            self.assertEqual(result,2)
            self.assertEqual(target.read_text(),"previous valid module\n")

    def test_invalid_javascript_rejected(self):
        for source in ("", "$done({bad syntax"):
            with self.subTest(source=source), self.assertRaises(sync.SyncError):
                sync.validate_scripts({"source.js":source})


if __name__ == "__main__":
    unittest.main(verbosity=2)
