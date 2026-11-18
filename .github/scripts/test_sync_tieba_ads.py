import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sync', HERE / 'sync_tieba_ads.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
CONFIG = (sync.ROOT / sync.ASSETS / 'TieBaAds.conf').read_bytes()
PROTO = (sync.ROOT / sync.ASSETS / 'tieba-proto.js').read_bytes()

class Converter(unittest.TestCase):
    def test_all_patterns_preserved(self):
        hosts, rules, ips = sync.parse(CONFIG)
        files = sync.prepare(CONFIG, PROTO)
        module = files[sync.MODULE].decode()
        for pattern, _, _, _ in rules:
            self.assertEqual(module.count(pattern), 1)
        self.assertIn('hostname = %APPEND% ' + ', '.join(hosts), module)
        for ip in ips: self.assertIn(ip, module)
        self.assertEqual(files[sync.ASSETS / 'tieba-proto.js'], PROTO)
        self.assertEqual(files[sync.ASSETS / 'TieBaAds.conf'], CONFIG)
        self.assertIn('binary-body-mode=true', module)
        self.assertIn('data-type=text data="" status-code=200', module)
        self.assertNotIn('[墨鱼版]', module)

    def test_unknown_rule_rejected(self):
        with self.assertRaises(ValueError): sync.prepare(CONFIG + b'\n^https://example.com url reject\n', PROTO)

    def test_unknown_expression_rejected(self):
        with self.assertRaises(ValueError): sync.prepare(CONFIG.replace(b'.hot_search = []', b'.hot_search = null'), PROTO)

    def test_unknown_dependency_rejected(self):
        with self.assertRaises(ValueError): sync.prepare(CONFIG.replace(b'/app2smile/rules/', b'/other/rules/'), PROTO)

    def test_invalid_js_rejected(self):
        with self.assertRaises(subprocess.CalledProcessError): sync.prepare(CONFIG, b'function {')

    def test_no_change_stability(self):
        self.assertEqual(sync.prepare(CONFIG, PROTO), sync.prepare(CONFIG, PROTO))

    def test_failure_keeps_published_files(self):
        for broken in [b'function {', None]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                old = root / sync.MODULE
                old.parent.mkdir(parents=True)
                old.write_bytes(b'keep published module')
                def fetch(url):
                    if url == sync.CONFIG_URL: return CONFIG
                    if broken is None: raise ValueError('Simulated dependency download failure')
                    return broken
                with patch.object(sync, 'ROOT', root), patch.object(sync, 'pinned', side_effect=fetch), patch('sys.argv', ['sync_tieba_ads.py']):
                    with self.assertRaises((ValueError, subprocess.CalledProcessError)): sync.main()
                self.assertEqual(old.read_bytes(), b'keep published module')
                self.assertFalse((root / sync.ASSETS).exists())

    def test_noop_preserves_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = sync.prepare(CONFIG, PROTO)
            for rel, data in files.items():
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            before = {rel: (root / rel).stat().st_mtime_ns for rel in files}
            with patch.object(sync, 'ROOT', root), patch.object(sync, 'pinned', side_effect=lambda url: CONFIG if url == sync.CONFIG_URL else PROTO), patch('sys.argv', ['sync_tieba_ads.py']):
                sync.main()
            self.assertEqual(before, {rel: (root / rel).stat().st_mtime_ns for rel in files})

    def test_json_behavior(self):
        data = sync.render(CONFIG, PROTO)[sync.ASSETS / 'tieba-json.js']
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'json.js'
            path.write_bytes(data)
            subprocess.run(['node', str(HERE / 'test_tieba_json.cjs'), str(path)], check=True, timeout=30)

if __name__ == '__main__': unittest.main()
