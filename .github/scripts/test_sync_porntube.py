import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    'sync_porntube', Path(__file__).with_name('sync_porntube.py'))
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def fixture_module():
    lines = ['#!name=upstream name', '#!desc=精确原文  + desc \\n untouched  ',
             '#!icon=https://example.invalid/icon.png', '#!author=upstream',
             '#!homepage=https://github.com/Yu9191/Rewrite', '#!category=18+',
             '#!arguments=test:default', '#!arguments-desc=原文\\n参数',
             '', '[Script]', '# preserve comments and whitespace']
    for filename, (label, action) in sync.ACTIONS.items():
        lines.append(f'{label} = type={action}, pattern=^https?://fixture.invalid/a,'
                     f' requires-body=1, max-size=-1, timeout=10, '
                     f'script-path={sync.SOURCE_PREFIX}{filename}, argument=x={{{{value}}}}')
    lines += ['', '[MITM]', 'hostname = %APPEND% fixture.invalid, *.fixture.invalid', '']
    return '\r\n'.join(lines).encode()


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'target'
        self.source = Path(self.temp.name) / 'source'
        self.data = {sync.MODULE: fixture_module()}
        for filename in sync.ACTIONS:
            # Executing this fixture would throw; --check must only parse it.
            self.data['porntube/dist/' + filename] = (
                b'// preserve CRLF and final bytes\r\nthrow new Error("DO NOT EXECUTE");\r\n')
        self.root.mkdir()
        self.unrelated = self.root / 'unrelated.txt'
        self.unrelated.write_bytes(b'unrelated legacy file\x00')

    def run_sync(self):
        return sync.sync(self.root, fetch=self.data.__getitem__)

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_metadata_description_and_all_rules_preserved(self):
        source = self.data[sync.MODULE]
        expected = source.replace(b'#!name=upstream name',
                                  ('#!name=' + sync.NAME).encode())
        expected = expected.replace(b'#!category=18+', b'#!category=Polly-ai')
        for filename in sync.ACTIONS:
            expected = expected.replace((sync.SOURCE_PREFIX + filename).encode(),
                                        (sync.DEST_PREFIX + filename).encode())
        self.assertEqual(sync.transform_module(source), expected)
        before = next(x for x in source.splitlines(keepends=True) if x.startswith(b'#!desc='))
        after = next(x for x in expected.splitlines(keepends=True) if x.startswith(b'#!desc='))
        self.assertEqual(before, after)

    def test_js_bytes_and_unchanged_second_sync(self):
        self.assertEqual(len(self.run_sync()), 5)
        for filename in sync.ACTIONS:
            self.assertEqual((self.root / sync.DEST_JS / filename).read_bytes(),
                             self.data['porntube/dist/' + filename])
        snapshot = self.snapshot()
        self.assertEqual(self.run_sync(), [])
        self.assertEqual(self.snapshot(), snapshot)

    def test_malformed_sources_fail_before_write(self):
        self.run_sync()
        baseline = self.snapshot()
        original = self.data[sync.MODULE]
        variants = [
            b'', b'\xff', original + b'\x00',
            original.replace(b'#!desc=', b'#!unknown='),
            original + b'#!desc=duplicate\n',
            original.replace(b'[Script]', b'[URL Rewrite]'),
            original.replace(b'type=http-request', b'type=cron', 1),
            original.replace(b'porntube-request.js', b'unknown.js'),
            original.replace(sync.SOURCE_PREFIX.encode(), b'https://example.invalid/', 1),
            original.replace(b'timeout=10', b'timeout=10, unexpected=yes', 1),
            original.replace(b'hostname =', b'skip-server-cert-verify ='),
            original.replace(b'timeout=10', b'timeout=10, timeout=20', 1),
            b'\n'.join(line for line in original.splitlines()
                       if b'porntube-request.js' not in line),
        ]
        for malformed in variants:
            with self.subTest(source=malformed[:50]):
                self.data[sync.MODULE] = malformed
                with self.assertRaises(sync.SourceError):
                    self.run_sync()
                self.assertEqual(self.snapshot(), baseline)

    def test_last_dependency_syntax_failure_before_write(self):
        self.run_sync()
        baseline = self.snapshot()
        self.data[sync.MODULE] = self.data[sync.MODULE].replace(b'untouched', b'changed upstream desc')
        self.data['porntube/dist/porntube-request.js'] = b'const changed = true;\n'
        self.data['porntube/dist/porntube-frontend.js'] = b'function broken( {'
        with self.assertRaises(sync.SourceError):
            self.run_sync()
        self.assertEqual(self.snapshot(), baseline)

    def test_missing_dependency_before_write(self):
        baseline = self.snapshot()
        del self.data['porntube/dist/porntube-frontend.js']
        with self.assertRaises(KeyError):
            self.run_sync()
        self.assertEqual(self.snapshot(), baseline)

    def test_offline_cli(self):
        for relative, data in self.data.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        result = subprocess.run([sys.executable, str(Path(sync.__file__)),
                                 '--root', str(self.root), '--source-dir', str(self.source)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Updated:', result.stdout)

    def test_api_fallback_checks_contents_integrity(self):
        import base64
        import hashlib
        import urllib.error
        payload = b'const x = 1;\n'
        path = 'porntube/dist/porntube.js'
        obj = {'type': 'file', 'path': path, 'encoding': 'base64',
               'content': base64.b64encode(payload).decode(), 'size': len(payload),
               'sha': hashlib.sha1(b'blob ' + str(len(payload)).encode() + b'\0' + payload).hexdigest()}
        with mock.patch.object(sync, 'request_bytes', side_effect=urllib.error.URLError('TLS')):
            with mock.patch.object(sync, 'api_json', return_value=obj):
                self.assertEqual(sync.fetch_file(path, 'a' * 40), payload)
                obj['sha'] = '0' * 40
                with self.assertRaises(sync.SourceError):
                    sync.fetch_file(path, 'a' * 40)


if __name__ == '__main__':
    unittest.main()
