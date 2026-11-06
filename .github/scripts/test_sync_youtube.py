#!/usr/bin/env python3
"""Offline conversion tests for exact YouTube description and binary parameters."""
import importlib.util
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sync_youtube',HERE/'sync_youtube.py')
sync=importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
DESC='基于稳定版，额外去除首页Shorts，去除首页shorts区块，去除视频播内嵌购推荐卡'
REDIRECT=r'^https?:\/\/[\w-]+\.googlevideo\.com\/(?!dclk_video_ads).+?&ctier=L(&.+?),ctier,(.+)'
CONFIG=('#!author=DivineEngine + app2smile + Maasea + ddgksf2013 + Aioneas + Oneasai + ZenmoFeiShi\n'
        '#!name=Original source name\n#!desc='+DESC+'\n'+REDIRECT+' url 302 https://$1$2$3\n'+
        '\n'.join(p+' url reject-200' for p in sorted(sync.REJECT_PATTERNS))+'\n'+
        sync.RESPONSE_PATTERN+' url script-response-body '+sync.JS_URL+'\n'+
        'hostname = *.googlevideo.com, redirector*.googlevideo.com, www.youtube.com, s.youtube.com, youtubei.googleapis.com\n').encode()
JS=b'// Synthetic rendering fixture; never published\n$done({});\n'


class YouTubeTests(unittest.TestCase):
    def test_exact_name_category_description_and_author(self):
        module=sync.render(CONFIG,JS).decode()
        self.assertEqual(module.splitlines()[0],'#!name = YouTube 净化')
        self.assertEqual(module.splitlines()[1],'#!desc='+DESC)
        self.assertIn('#!category = Polly-ai\n',module)
        self.assertIn('DivineEngine + app2smile + Maasea',module)
        self.assertNotIn('Original source name',module)

    def test_description_follows_original_not_converter_paraphrase(self):
        new='上游新增描述（文字、标点和 Shorts 大小写原样保留）'
        module=sync.render(CONFIG.replace(DESC.encode(),new.encode()),JS).decode()
        self.assertEqual(module.splitlines()[1],'#!desc='+new)

    def test_bad_redirect_is_present_but_disabled(self):
        module=sync.render(CONFIG,JS).decode()
        section=module.split('\n[URL Rewrite]\n',1)[1].split('\n[Map Local]\n',1)[0]
        self.assertIn('# 上游原行（保留但不启用）：'+REDIRECT+' url 302 https://$1$2$3',section)
        self.assertIn('# '+REDIRECT+' https://$1$2$3 302',section)
        self.assertFalse(any(line and not line.startswith('#') for line in section.splitlines()))

    def test_changed_redirect_never_silently_reenabled(self):
        config=CONFIG.replace(b'https://$1$2$3',b'https://$1$2')
        module=sync.render(config,JS).decode()
        self.assertIn('# '+REDIRECT+' https://$1$2 302',module)
        self.assertFalse(any(line.startswith('^') and line.endswith(' 302') for line in module.splitlines()))

    def test_native_map_local_all_four_status200_empty(self):
        module=sync.render(CONFIG,JS).decode()
        mappings=[line for line in module.splitlines() if line.startswith('^')]
        self.assertEqual(len(mappings),4)
        self.assertEqual({line.split(maxsplit=1)[0] for line in mappings},sync.REJECT_PATTERNS)
        for line in mappings:
            _,options=line.split(maxsplit=1)
            values=dict(s.split('=',1) for s in shlex.split(options))
            self.assertEqual(values['data-type'],'text')
            self.assertEqual(values['data'],'')
            self.assertEqual(values['status-code'],'200')
            self.assertIn('Cache-Control:no-store',values['header'])
        self.assertNotIn(' _ reject',module)
        self.assertNotIn('type=http-request',module)

    def test_response_is_raw_binary_and_bounded(self):
        module=sync.render(CONFIG,JS).decode()
        scripts=[line for line in module.splitlines() if line.startswith('youtube-cleanup =')]
        self.assertEqual(len(scripts),1)
        line=scripts[0]
        for field in ('type=http-response','requires-body=true','binary-body-mode=true',
                      'max-size=4194304','script-update-interval=86400','timeout=15',
                      'script-path='+sync.MIRROR):
            self.assertIn(field,line)
        self.assertIn('pattern='+sync.RESPONSE_PATTERN,line)
        self.assertNotIn('argument=',line)

    def test_preserve_original_mitm_hostnames(self):
        module=sync.render(CONFIG,JS).decode()
        expected='hostname = %APPEND% *.googlevideo.com, redirector*.googlevideo.com, www.youtube.com, s.youtube.com, youtubei.googleapis.com'
        self.assertIn(expected,module)
        self.assertNotIn('hostname = %APPEND% *\n',module)

    def test_all_source_patterns_accounted_for(self):
        _,_,rules,_=sync.parse(CONFIG)
        module=sync.render(CONFIG,JS).decode()
        for pattern,_,_,_,original in rules:
            self.assertIn(pattern,module)
        self.assertEqual(len(rules),6)
        self.assertEqual(sum(action=='reject-200' for _,action,_,_,_ in rules),4)
        self.assertEqual(sum(action=='script-response-body' for _,action,_,_,_ in rules),1)

    def test_source_hashes_and_no_dynamic_timestamp(self):
        module=sync.render(CONFIG,JS)
        self.assertIn(sync.digest(CONFIG).encode(),module)
        self.assertIn(sync.digest(JS).encode(),module)
        self.assertEqual(module,sync.render(CONFIG,JS))
        self.assertNotEqual(module,sync.render(CONFIG,JS+b'// update'))

    def test_unknown_grammar_or_action_fails_closed(self):
        for bad in (CONFIG+b'setting = true\n',CONFIG.replace(b'url reject-200',b'url reject-404',1),
                    CONFIG+b'[Script]\n',CONFIG+b'\0'):
            with self.subTest(bad=bad[:30]),self.assertRaises(sync.ReviewRequired):
                sync.parse(bad)

    def test_unsafe_script_source_or_new_host_rejected(self):
        for bad in (CONFIG.replace(sync.JS_URL.encode(),b'https://untrusted.example/script.js'),
                    CONFIG+b'hostname = untrusted.example\n'):
            with self.subTest(bad=bad[:30]),self.assertRaises(sync.ReviewRequired):
                sync.parse(bad)

    def test_missing_duplicate_or_changed_endpoint_rejected(self):
        first=next(line for line in CONFIG.splitlines() if line.startswith(b'^') and b'url reject-200' in line)
        for bad in (b'',CONFIG.replace(first+b'\n',b''),CONFIG+first+b'\n',
                    CONFIG.replace(b'#!desc=',b'# desc='),CONFIG.replace(b'account\\/get_setting',b'account\\/new_setting')):
            with self.subTest(bad=bad[:30]),self.assertRaises(sync.ReviewRequired):
                sync.parse(bad)

    def test_noop_preserves_exact_bytes_and_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);files={Path('module'):b'module',Path('original'):b'original\r\n'}
            self.assertTrue(sync.replace_bundle(root,files))
            times={p:(root/p).stat().st_mtime_ns for p in files}
            self.assertFalse(sync.replace_bundle(root,files))
            for p,data in files.items():
                self.assertEqual((root/p).read_bytes(),data)
                self.assertEqual((root/p).stat().st_mtime_ns,times[p])

    def test_bundle_failure_restores_existing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old={Path('module'):b'old-module',Path('script'):b'old-script'}
            sync.replace_bundle(root,old);replace=Path.replace;count=0
            def failing(source,target):
                nonlocal count
                count+=1
                if count==2:raise OSError('test write failure')
                return replace(source,target)
            with patch.object(Path,'replace',failing),self.assertRaises(OSError):
                sync.replace_bundle(root,{Path('module'):b'new-module',Path('script'):b'new-script'})
            for p,data in old.items():self.assertEqual((root/p).read_bytes(),data)
            self.assertFalse((root/'script.sync-tmp').exists())

    def test_failed_validation_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);c=root/'input.conf';j=root/'source.js'
            c.write_bytes(CONFIG);j.write_bytes(JS);target=root/sync.MODULE
            sync.replace_bundle(root,{sync.MODULE:b'previous valid'})
            with patch.object(sync,'prepare',side_effect=sync.ReviewRequired('test validation error')):
                result=sync.main(['--config',str(c),'--javascript',str(j),'--root',str(root)])
            self.assertEqual(result,2)
            self.assertEqual(target.read_bytes(),b'previous valid')


if __name__=='__main__':
    unittest.main(verbosity=2)
