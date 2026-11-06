#!/usr/bin/env python3
"""Offline tests: Reddit parsing, deterministic output and fail-closed updates."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sync_reddit_ads", HERE / "sync_reddit_ads.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

URL = "https://raw.githubusercontent.com/ddgksf2013/Scripts/refs/heads/master/reddit.js"
CONFIG = r'''// @Version V1.0.test
// @UpdateTime 2026-11-06
hostname = gql-fed.reddit.com
# > Reddit GraphQL response
^https?:\/\/gql-fed\.reddit\.com\/$ url script-response-body ''' + URL + "\n"
JS = "$done({body: $response.body});\n"


class RedditTests(unittest.TestCase):
    def test_exact_pattern_and_mitm(self):
        hosts, entries = sync.parse(CONFIG)
        self.assertEqual(hosts, ["gql-fed.reddit.com"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][0], r"^https?:\/\/gql-fed\.reddit\.com\/$")
        module = sync.render(CONFIG, {"reddit.js": JS})
        self.assertIn("hostname = %APPEND% gql-fed.reddit.com", module)
        self.assertNotIn("%APPEND% *", module)

    def test_category_name_and_comment_token_cleanup(self):
        tagged = CONFIG.replace("# > Reddit GraphQL response",
                                "# > Reddit GraphQL response@ddgksf2013；保留正文")
        module = sync.render(tagged, {"reddit.js": JS})
        self.assertEqual(module.splitlines()[0], "#!name = Reddit 增强")
        self.assertIn("#!category = Polly-ai", module)
        self.assertIn("#!author = \n", module)
        self.assertIn("# > Reddit GraphQL response；保留正文", module)
        self.assertNotIn("[墨鱼版]", module)
        self.assertNotIn("@ddgksf2013", module)
        original_comments = [line for line in tagged.splitlines() if line.startswith("# >")]
        rendered_comments = [line for line in module.splitlines() if line.startswith("# >")]
        self.assertEqual(rendered_comments,
                         [line.replace("@ddgksf2013", "") for line in original_comments])
        self.assertIn("V1.0.test", module)
        self.assertIn(sync.UPSTREAM_URL, module)

    def test_surge_response_parameters(self):
        module = sync.render(CONFIG, {"reddit.js": JS})
        self.assertIn("type=http-response", module)
        self.assertIn("requires-body=true, max-size=1048576", module)
        self.assertIn("script-update-interval=86400, timeout=10", module)
        self.assertIn(sync.RAW_ROOT + "/Surge/JavaScript/Reddit/reddit-surge.js", module)
        self.assertNotIn("binary-body-mode", module)

    def test_deterministic_and_source_hashes(self):
        first = sync.render(CONFIG, {"reddit.js": JS})
        self.assertEqual(first, sync.render(CONFIG, {"reddit.js": JS}))
        self.assertIn(sync.digest(CONFIG), first)
        self.assertIn(sync.digest(JS), first)
        self.assertNotEqual(first, sync.render(CONFIG, {"reddit.js": JS + "// upstream update\n"}))

    def test_unknown_syntax_fails_closed(self):
        for line in ("host, ads.reddit.com, reject", "setting = true",
                     "^https://reddit.com/ url reject-200"):
            with self.subTest(line=line), self.assertRaises(sync.SyncError):
                sync.parse(CONFIG + line + "\n")

    def test_missing_required_fields(self):
        for text in ("", CONFIG.replace("hostname =", "# hostname ="),
                     "hostname = gql-fed.reddit.com\n"):
            with self.subTest(text=text), self.assertRaises(sync.SyncError):
                sync.parse(text)

    def test_wrapped_lines(self):
        text = CONFIG.replace("hostname = gql-fed.reddit.com",
                              "hostname = gql-fed.reddit.com,\ngql.reddit.com")
        text = text.replace("script-response-body https://", "script-response-body\nhttps://")
        hosts, entries = sync.parse(text)
        self.assertEqual(hosts, ["gql-fed.reddit.com", "gql.reddit.com"])
        self.assertEqual(len(entries), 1)
        with self.assertRaises(sync.SyncError):
            sync.parse(CONFIG + "hostname = gql-fed.reddit.com,\n")

    def test_duplicate_url_pattern(self):
        with self.assertRaises(sync.SyncError):
            sync.parse(CONFIG + CONFIG.splitlines()[-1] + "\n")

    def test_untrusted_script_and_hostname(self):
        for bad_url in ("http://raw.githubusercontent.com/ddgksf2013/Scripts/master/reddit.js",
                        "https://untrusted.invalid/reddit.js", URL + "?secret=1",
                        URL.replace("ddgksf2013", "other-author")):
            with self.subTest(url=bad_url), self.assertRaises(sync.SyncError):
                sync.parse(CONFIG.replace(URL, bad_url))
        with self.assertRaises(sync.SyncError):
            sync.parse(CONFIG.replace("hostname = gql-fed.reddit.com", "hostname = unrelated.com"))

    def test_mismatched_assets(self):
        with self.assertRaises(sync.SyncError):
            sync.render(CONFIG, {"other.js": JS})

    def test_noop_does_not_change_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "module.sgmodule"
            self.assertTrue(sync.write_changed(path, "original\r\n"))
            modified = path.stat().st_mtime_ns
            self.assertFalse(sync.write_changed(path, "original\r\n"))
            self.assertEqual(modified, path.stat().st_mtime_ns)
            self.assertEqual(path.read_bytes(), b"original\r\n")
            self.assertFalse(path.with_name(path.name + ".sync-tmp").exists())

    def test_no_write_on_validation_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.conf"
            source.write_text(CONFIG)
            target = root / sync.MODULE_PATH
            sync.write_changed(target, "previous valid version\n")
            with patch.object(sync, "prepare", side_effect=sync.SyncError("validation failed")):
                result = sync.main(["--from-file", str(source), "--root", str(root)])
            self.assertEqual(result, 2)
            self.assertEqual(target.read_text(), "previous valid version\n")

    def test_vm_accepts_surge_only_script(self):
        sync.validate_js({"simple.js": JS})

    def test_compatibility_adapter_preserves_upstream(self):
        source = "// author notice\n$done({body:$response.body});\n"
        adapter = sync.build_adapter(source, "source.js")
        self.assertIn(source, adapter)
        self.assertIn(sync.digest(source), adapter)
        self.assertIn('x-apollo-operation-name', adapter)
        self.assertIn('typeof result.body === "string"', adapter)
        self.assertEqual(sync.adapter_name("source.js"), "source-surge.js")
        sync.validate_js({"source-surge.js": adapter})

    def test_adapter_rejects_invalid_body_and_catches_errors(self):
        for source in ("$done({body:{invalid:true}});", "throw new Error('upstream failure');"):
            adapter = sync.build_adapter(source, "source.js")
            # Generic fixture is preserved by $done({}) fail-open, without a bad body.
            sync.validate_js({"source-surge.js": adapter})

    def test_invalid_js_fails(self):
        for script in ("", "$done({invalid", "$prefs.setValueForKey('value','key'); $done({});"):
            with self.subTest(script=script), self.assertRaises(sync.SyncError):
                sync.validate_js({"simple.js": script})


if __name__ == "__main__":
    unittest.main(verbosity=2)
