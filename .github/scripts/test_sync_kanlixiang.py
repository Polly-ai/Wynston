#!/usr/bin/env python3
"""Offline tests for the minimal, exact-reference Kanlixiang mirror."""
import base64
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('sync_kanlixiang', Path(__file__).with_name('sync_kanlixiang.py'))
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
URL = 'https://raw.githubusercontent.com/Aioneas/Surge/main/Script/klx_no_ads.js'
PIN = 'https://raw.githubusercontent.com/Aioneas/Surge/' + 'a' * 40 + '/Script/klx_test.js?v=20260814g'
SAMPLE = ('#!category=看理想\n#!name=原名称\n#!desc=原描述，不删改。\n#!author=baby + Aioneas\n'
          '# 原说明完整保留\n[Map Local]\n'
          '^https://api\\.vistopia\\.com\\.cn/ad data-type=base64 data="eyJzdGF0dXMiOiJzdWNjZXNzIiwiZGF0YSI6W119" status-code=200 header="Content-Type: application/json"\n'
          '^https://api\\.vistopia\\.com\\.cn/popup data-type=base64 data="eyJzdGF0dXMiOiJlcnJvciIsImRhdGEiOm51bGx9" status-code=404 header="Content-Type: application/json"\n'
          '[Script]\n广告 = type=http-response, pattern=^https://api\\.vistopia\\.com\\.cn/home, requires-body=1, max-size=0, script-path=' + URL + '\n'
          '兼容 = type=http-response, pattern=^https://api\\.vistopia\\.com\\.cn/play, requires-body=1, max-size=0, timeout=15, script-path=' + PIN + '\n'
          '[MITM]\nhostname = %APPEND% api.vistopia.com.cn, shop.vistopia.com.cn\n').encode()
JS = b'$done({});\n'


class MirrorTests(unittest.TestCase):
    def test_only_category_and_script_urls_change(self):
        result = sync.render(SAMPLE)
        expected = SAMPLE.decode().replace('#!category=看理想', '#!category=Polly-ai')
        for url, name in sync.parse(SAMPLE).items():
            expected = expected.replace(url, sync.MIRROR + (sync.ASSETS / name).as_posix())
        self.assertEqual(result, expected.encode())
        self.assertIn('原描述，不删改。'.encode(), result)
        self.assertIn('原说明完整保留'.encode(), result)
        self.assertIn(b'requires-body=1, max-size=0', result)

    def test_exact_pins_and_version_queries_are_fetched(self):
        calls = []
        def fetcher(url):
            calls.append(url)
            return JS
        files = sync.prepare(SAMPLE, fetcher)
        self.assertEqual(calls, [URL, PIN])
        self.assertEqual(files[sync.ASSETS / 'klx_test.js'], JS)
        self.assertEqual(len(files), 3)

    def test_base64_status_semantics_preserved(self):
        result = sync.render(SAMPLE).decode()
        self.assertIn('status-code=404', result)
        self.assertIn('status-code=200', result)
        self.assertIn(base64.b64encode(b'{"status":"success","data":[]}').decode(), result)
        self.assertIn(base64.b64encode(b'{"status":"error","data":null}').decode(), result)

    def test_deterministic_output(self):
        self.assertEqual(sync.render(SAMPLE), sync.render(SAMPLE))

    def test_unknown_source_or_filename_collision_rejected(self):
        for bad in (SAMPLE.replace(URL.encode(), b'https://untrusted.example/a.js'),
                    SAMPLE.replace(PIN.encode(), PIN.replace('klx_test.js', 'klx_no_ads.js').encode()),
                    SAMPLE.replace(PIN.encode(), (PIN + '&token=secret').encode())):
            with self.assertRaises(sync.ReviewRequired):
                sync.parse(bad)

    def test_unknown_section_and_mitm_scope_rejected(self):
        for bad in (SAMPLE + b'[General]\nloglevel = verbose\n',
                    SAMPLE.replace(b'%APPEND% api.vistopia.com.cn, shop.vistopia.com.cn', b'%APPEND% *'),
                    SAMPLE.replace(b'requires-body=1', b'requires-body=false')):
            with self.assertRaises(sync.ReviewRequired):
                sync.parse(bad)

    def test_missing_invalid_or_html_source_rejected(self):
        for bad in (b'', b'<html>bad gateway</html>', SAMPLE + b'\x00',
                    SAMPLE.replace(b'#!desc=', b'# description='),
                    SAMPLE.replace(b'data="eyJzdGF0dXMiOiJlcnJvciIsImRhdGEiOm51bGx9"', b'data="bad!"')):
            with self.assertRaises((sync.ReviewRequired, ValueError)):
                sync.parse(bad)

    def test_script_syntax_validation(self):
        sync.validate_javascript({'good.js': JS})
        with self.assertRaises(sync.ReviewRequired):
            sync.validate_javascript({'bad.js': b'$done({syntax error'} )

    def test_noop_does_not_touch_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {Path('module'): b'module', Path('original'): b'original\r\n'}
            self.assertEqual(len(sync.replace_bundle(root, files)), 2)
            times = {p: (root / p).stat().st_mtime_ns for p in files}
            self.assertEqual(sync.replace_bundle(root, files), [])
            for path, data in files.items():
                self.assertEqual((root / path).read_bytes(), data)
                self.assertEqual((root / path).stat().st_mtime_ns, times[path])

    def test_failed_replace_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = {Path('a'): b'old-a', Path('b'): b'old-b'}
            sync.replace_bundle(root, old)
            real = Path.replace
            count = 0
            def failed(source, target):
                nonlocal count
                count += 1
                if count == 2:
                    raise OSError('injected failure')
                return real(source, target)
            with patch.object(Path, 'replace', failed), self.assertRaises(OSError):
                sync.replace_bundle(root, {Path('a'): b'new-a', Path('b'): b'new-b'})
            for path, data in old.items():
                self.assertEqual((root / path).read_bytes(), data)

    def test_download_failure_never_publishes_partial_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / 'upstream.sgmodule'
            module.write_bytes(SAMPLE)
            sync.replace_bundle(root, {sync.MODULE: b'previous module'})
            with patch.object(sync, 'prepare', side_effect=sync.ReviewRequired('test fetch failure')):
                code = sync.main(['--module', str(module), '--root', str(root)])
            self.assertEqual(code, 2)
            self.assertEqual((root / sync.MODULE).read_bytes(), b'previous module')


if __name__ == '__main__':
    unittest.main(verbosity=2)
