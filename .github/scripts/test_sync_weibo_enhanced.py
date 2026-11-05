#!/usr/bin/env python3
"""Offline strict-conversion tests for the complete Weibo assistant module."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sync_weibo', HERE / 'sync_weibo_enhanced.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
SOURCE = sync.SCRIPT_URL
CONFIG = (r'''// @Version V0.1.test
// @UpdateTime 2026-11-06
hostname = api.weibo.cn, bootpreload.uve.weibo.com
# > local settings page
^https://api\.weibo\.cn/__qx_weibo_settings__/(?:api/config)?(?=[?#]|$) url script-echo-response '''+SOURCE+'\n'+
          r'''# > settings write API
^https://api\.weibo\.cn/__qx_weibo_settings__/api/(?:save|reset)(?=[?#]|$) url script-analyze-echo-response '''+SOURCE+'\n'+
          r'''# > main response
^https?://api\.weibo\.cn/2/statuses/container_timeline_hot(?=[?#]|$) url script-response-body '''+SOURCE+'\n')
JS = b'// native Surge source preserved\n$done({});\n'


def patterns(module):
    return [line.split('pattern=',1)[1].split(', ',1)[0]
            for line in module.splitlines() if 'pattern=' in line]


class WeiboConversionTests(unittest.TestCase):
    def test_fixed_name_category_and_settings_link(self):
        out = sync.render(CONFIG.encode(),JS)
        self.assertIn('#!name = 微博 增强助手\n',out)
        self.assertIn('#!category = Polly-ai\n',out)
        self.assertIn('https://api.weibo.cn/__qx_weibo_settings__/',out)
        self.assertIn('V0.1.test',out)
        self.assertIn('ddgksf2013',out)

    def test_all_patterns_and_dynamic_actions_preserved(self):
        _, rules, _ = sync.parse(CONFIG)
        out = sync.render(CONFIG.encode(),JS)
        self.assertEqual(patterns(out),[p for p,_,_ in rules])
        self.assertEqual(out.count('type=http-request'),2)
        self.assertEqual(out.count('type=http-response'),1)
        self.assertIn('# > local settings page',out)
        self.assertIn('# > settings write API',out)
        self.assertIn('# > main response',out)

    def test_settings_read_does_not_require_body(self):
        out = sync.render(CONFIG.encode(),JS)
        line=next(line for line in out.splitlines() if 'type=http-request' in line)
        self.assertIn('requires-body=false',line)
        self.assertNotIn('max-size=',line)
        self.assertIn('Surge/JavaScript/Weibo/weibo_json.js',line)

    def test_settings_save_receives_request_body(self):
        out = sync.render(CONFIG.encode(),JS)
        line=next(line for line in out.splitlines() if 'api/(?:save|reset)' in line)
        self.assertIn('type=http-request',line)
        self.assertIn('requires-body=true, max-size=262144',line)

    def test_response_buffer_is_bounded(self):
        out = sync.render(CONFIG.encode(),JS)
        line=next(line for line in out.splitlines() if 'type=http-response' in line)
        self.assertIn('requires-body=true, max-size=1048576',line)
        self.assertIn('script-update-interval=86400',line)
        self.assertIn('timeout=15',line)
        self.assertNotIn('binary-body-mode',line)

    def test_mitm_only_appends_original_hosts(self):
        out=sync.render(CONFIG.encode(),JS)
        self.assertIn('hostname = %APPEND% api.weibo.cn, bootpreload.uve.weibo.com',out)
        self.assertNotIn('hostname = %APPEND% *',out)

    def test_no_fake_map_for_dynamic_settings(self):
        out=sync.render(CONFIG.encode(),JS)
        self.assertNotIn('\n[Map Local]\n',out)
        self.assertNotIn('data-type=text',out)
        self.assertIn('两个动态设置接口不能用固定空体映射代替',out)

    def test_disabled_rule_stays_disabled(self):
        disabled = r';^https?://api\.weibo\.cn/2/disabled url script-response-body '+SOURCE
        out=sync.render((CONFIG+disabled+'\n').encode(),JS)
        self.assertIn('# 上游默认停用（保持停用）：'+disabled[1:],out)
        self.assertEqual(len(patterns(out)),3)

    def test_deterministic_and_both_source_hashes(self):
        out=sync.render(CONFIG.encode(),JS)
        self.assertEqual(out,sync.render(CONFIG.encode(),JS))
        self.assertIn(sync.sha(CONFIG.encode()),out)
        self.assertIn(sync.sha(JS),out)
        self.assertNotEqual(out,sync.render(CONFIG.encode(),JS+b'// update'))

    def test_wrapped_script_and_hostname_supported(self):
        text=CONFIG.replace('api.weibo.cn, bootpreload.uve.weibo.com',
                            'api.weibo.cn,\nbootpreload.uve.weibo.com')
        text=text.replace('script-echo-response https://','script-echo-response\nhttps://')
        self.assertEqual(len(sync.parse(text)[1]),3)
        with self.assertRaises(sync.SyncError):
            sync.parse(CONFIG+'hostname = api.weibo.cn,\n')

    def test_unknown_directive_or_action_fails_closed(self):
        for text in (CONFIG+'setting = true\n',CONFIG.replace('script-echo-response','script-new-action'),
                     CONFIG.replace('__qx_weibo_settings__','unreviewed-local-path')):
            with self.subTest(text=text),self.assertRaises(sync.SyncError):
                sync.parse(text)

    def test_host_and_script_sources_are_reviewed(self):
        for text in (CONFIG+'hostname = unrelated.example\n',
                     CONFIG.replace(SOURCE,'https://untrusted.example/source.js')):
            with self.subTest(text=text),self.assertRaises(sync.SyncError):
                sync.parse(text)

    def test_duplicate_missing_or_invalid_regex(self):
        for text in ('','hostname = api.weibo.cn\n',CONFIG+CONFIG.splitlines()[-1]+'\n',
                     CONFIG.replace('^https?://api','^[https?://api')):
            with self.subTest(text=text),self.assertRaises(sync.SyncError):
                sync.parse(text)

    def test_original_bytes_and_noop_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'script.js'
            data=JS+b'// CRLF\r\n'
            self.assertTrue(sync.write_changed(p,data))
            before=p.stat().st_mtime_ns
            self.assertFalse(sync.write_changed(p,data))
            self.assertEqual(before,p.stat().st_mtime_ns)
            self.assertEqual(data,p.read_bytes())
            self.assertFalse(p.with_name(p.name+'.sync-tmp').exists())

    def test_failed_validation_leaves_module_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); cfg=root/'input.conf'; script=root/'source.js'
            cfg.write_text(CONFIG); script.write_bytes(JS)
            target=root/sync.MODULE_PATH
            sync.write_changed(target,b'previous valid version\n')
            with patch.object(sync,'prepare',side_effect=sync.SyncError('test failure')):
                result=sync.main(['--root',str(root),'--from-file',str(cfg),'--script-file',str(script)])
            self.assertEqual(result,2)
            self.assertEqual(target.read_bytes(),b'previous valid version\n')


if __name__=='__main__':
    unittest.main(verbosity=2)
