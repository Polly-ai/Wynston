import pathlib
import tempfile
import unittest
import sync_trakt as s

SCRIPT = b'var preserved = "upstream";\n' * 8
IMAGE = b'RIFF0000WEBPimage'
URL = s.SOURCE + 'trakt_simplified_chinese.js'
MODULE = ('#!name=Trakt 增强\n#!desc=Original description\n#!category=Other\n'
          '#!icon=' + s.SOURCE + 'images/trakt.webp\n#!arguments=test:true\n'
          '[Script]\nOriginal = type=http-response, pattern=^https://example.com, requires-body=true, max-size=0, timeout=60, script-path=' + URL +
          '\n[MITM]\nhostname = %APPEND% example.com\n').encode()

def loader(url):
    return IMAGE if url.endswith('.webp') else SCRIPT

class SyncTests(unittest.TestCase):
    def test_only_permitted_changes(self):
        files = s.build(MODULE, loader)
        result = files[s.MODULE].decode()
        original = MODULE.decode().replace('#!category=Other\n', '')
        restored = result.replace('#!category = Polly-ai\n', '')
        restored = restored.replace(s.DEST + s.ASSETS + 'trakt_simplified_chinese.js', URL)
        restored = restored.replace(s.DEST + s.ASSETS + 'images/trakt.webp', s.SOURCE + 'images/trakt.webp')
        self.assertEqual(restored, original)
        self.assertEqual(files[s.ASSETS + 'trakt_simplified_chinese.js'], SCRIPT)
        self.assertEqual(files[s.ASSETS + 'images/trakt.webp'], IMAGE)

    def test_reject_unexpected_dependencies(self):
        with self.assertRaises(ValueError):
            s.build(MODULE.replace(URL.encode(), b'https://other.example/file.js'), loader)

    def test_invalid_javascript(self):
        with self.assertRaises(Exception):
            s.build(MODULE, lambda url: b'{{{' * 100)

    def test_invalid_image(self):
        with self.assertRaises(ValueError):
            s.build(MODULE, lambda url: b'wrong image' if url.endswith('.webp') else SCRIPT)

    def test_failure_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            old = root / s.MODULE
            old.parent.mkdir(parents=True)
            old.write_bytes(b'existing module')
            def broken(url):
                if 'api.github.com' in url:
                    return b'{"sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
                if url.endswith('.sgmodule'):
                    return MODULE
                raise OSError('download failed')
            with self.assertRaises(OSError):
                s.sync(root, broken)
            self.assertEqual(old.read_bytes(), b'existing module')
            self.assertEqual(list(root.rglob('*.*')), [old])

if __name__ == '__main__':
    unittest.main()
