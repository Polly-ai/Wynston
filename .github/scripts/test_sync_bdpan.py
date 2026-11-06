#!/usr/bin/env python3
"""Offline tests for full BaiduPan modules and transactional daily updates."""
import importlib.util
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sync_bdpan',HERE/'sync_bdpan.py')
sync=importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def fixture(kind):
    source=sync.PROJECTS[kind]['source']
    if kind=='ads':
        rules=(r'''# > ad description @ddgksf2013
^https?:\/\/pan\.baidu\.com\/api\/getconfig url reject-dict
# > splash description @ddgksf2013
^https?:\/\/pan\.baidu\.com\/api\/splash url reject-200
# > response description
^https?:\/\/afd\.baidu\.com\/afd\/entry url script-response-body '''+source+'\n'+
               r'''# > task description
^https:\/\/pan\.baidu\.com\/api\/taskscore\/tasklist url jsonjq-response-body '.result.list=[]'
''')
    else:
        rules=(r'^https:\/\/pan\.baidu\.com\/api\/streaming\?app_id=\d+&type=M3U8_HQ_1080 url script-request-header '+source+'\n'+
               r'^https:\/\/pan\.baidu\.com\/rest\/.*\/membership\/user url script-response-body '+source+'\n')
    return ('/*\nBaiduPan original configuration\n[rewrite_local]\n'+rules+
            '[mitm]\nhostname = pan.baidu.com, afd.baidu.com\n*/\n'
            "const version = 'V1.0.test';\n$done({});\n").encode()


def active_patterns(module):
    found=[]
    for line in module.splitlines():
        if not line or line.startswith('#'):
            continue
        if 'pattern=' in line:
            found.append(line.split('pattern=',1)[1].split(', ',1)[0])
        elif line.startswith('^'):
            found.append(line.split()[0])
    return found


class BaiduPanTests(unittest.TestCase):
    def test_fixed_names_category_versions(self):
        for kind,title in [('ads','百度网盘净化'),('unlock','百度网盘 功能增强')]:
            source=fixture(kind);out=sync.render(source,kind).decode()
            self.assertIn('#!name = '+title+'\n',out)
            self.assertIn('#!category = Polly-ai\n',out)
            self.assertIn('V1.0.test',out)
            self.assertIn(sync.digest(source),out)
            self.assertIn(sync.PROJECTS[kind]['source'],out)

    def test_original_rule_patterns_and_comment_text(self):
        for kind in sync.PROJECTS:
            source=fixture(kind);hosts,rules,notes,version=sync.parse(source,kind)
            out=sync.render(source,kind).decode()
            self.assertCountEqual(active_patterns(out),[p for p,_,_,_,d in rules if not d])
            for _,_,_,comment,_ in rules:
                if comment:self.assertIn(comment,out)
            self.assertEqual(hosts,['pan.baidu.com','afd.baidu.com'])

    def test_native_map_local_status_and_bodies(self):
        out=sync.render(fixture('ads'),'ads').decode()
        maps=[line for line in out.splitlines() if line.startswith('^')]
        self.assertEqual(len(maps),2)
        parameters=[]
        for line in maps:
            pattern,options=line.split(maxsplit=1)
            options=dict(part.split('=',1) for part in shlex.split(options))
            self.assertEqual(options['data-type'],'text')
            self.assertEqual(options['status-code'],'200')
            self.assertIn('Cache-Control:no-store',options['header'])
            parameters.append(options)
        self.assertEqual({o['data'] for o in parameters},{'','{}'})
        self.assertTrue(any('application/json' in o['header'] for o in parameters))
        self.assertIn('\n[Map Local]\n',out)
        self.assertNotIn(' _ reject',out)

    def test_qx_jq_converted_to_independent_response_script(self):
        out=sync.render(fixture('ads'),'ads').decode()
        line=next(line for line in out.splitlines() if 'pattern=' in line and 'taskscore' in line)
        self.assertIn('type=http-response',line)
        self.assertIn('bdpan.taskscore.js',line)
        self.assertIn('requires-body=true, max-size=1048576',line)
        self.assertIn('value.result.list = []',sync.JQ_SCRIPT)
        self.assertIn('if (value === null) value = {}',sync.JQ_SCRIPT)
        self.assertIn('if (value.result == null) value.result = {}',sync.JQ_SCRIPT)

    def test_request_and_response_modes_with_native_url_engine(self):
        out=sync.render(fixture('unlock'),'unlock').decode()
        req=next(line for line in out.splitlines() if 'type=http-request' in line)
        res=next(line for line in out.splitlines() if 'type=http-response' in line)
        self.assertIn('requires-body=false',req)
        self.assertIn('engine=webview',req)
        self.assertIn('requires-body=true, max-size=1048576',res)
        self.assertIn('engine=webview',res)
        for line in (req,res):
            self.assertIn('script-update-interval=86400',line)
            self.assertIn('timeout=15',line)
            self.assertNotIn('binary-body-mode',line)
        self.assertNotIn('\n[Map Local]\n',out)

    def test_overlap_warning_and_mitm_do_not_expand_scope(self):
        for kind in sync.PROJECTS:
            out=sync.render(fixture(kind),kind).decode()
            self.assertIn('“功能增强”的响应规则优先',out)
            self.assertIn('hostname = %APPEND% pan.baidu.com, afd.baidu.com',out)
            self.assertNotIn('hostname = %APPEND% *',out)

    def test_bridge_embeds_full_original_and_deterministic(self):
        for kind in sync.PROJECTS:
            source=fixture(kind)
            bridge=sync.build_adapter(source,kind)
            self.assertIn(source,bridge)
            self.assertIn(sync.digest(source).encode(),bridge)
            self.assertEqual(bridge,sync.build_adapter(source,kind))
            self.assertIn(b'finish({}); return;',bridge)
            self.assertIn(b'typeof result.body === "string"',bridge)
            self.assertIn(b'typeof result.url === "string"',bridge)
            self.assertEqual(sync.render(source,kind),sync.render(source,kind))

    def test_disabled_rules_stay_disabled(self):
        source=fixture('ads').replace(b'^https?:\\/\\/afd',b';^https?:\\/\\/afd')
        _,rules,_,_=sync.parse(source,'ads')
        self.assertEqual(sum(bool(d) for _,_,_,_,d in rules),1)
        out=sync.render(source,'ads').decode()
        self.assertEqual(len(active_patterns(out)),3)
        self.assertIn('# bdpan_ads_',out)

    def test_unknown_action_source_and_jq_fail_closed(self):
        source=fixture('ads')
        candidates=[source.replace(b'reject-200',b'reject-new'),
                    source.replace(sync.PROJECTS['ads']['source'].encode(),b'https://untrusted.example/script.js'),
                    source.replace(b"'.result.list=[]'",b"'.result=[]'"),
                    source.replace(b'url reject-200',b'url reject-200 extra')]
        for value in candidates:
            with self.subTest(value=value[:25]),self.assertRaises(sync.ReviewRequired):
                sync.parse(value,'ads')

    def test_missing_duplicate_and_invalid_regex(self):
        source=fixture('unlock')
        first=next(line for line in source.splitlines() if line.startswith(b'^'))
        candidates=[b'',b'no block comment',source.replace(b'hostname =',b'unknown_hostname ='),
                    source.replace(b'*/',first+b'\n*/',1),
                    source.replace(b'^https:',b'^[https:',1),source+b'\0']
        for value in candidates:
            with self.subTest(value=value[:25]),self.assertRaises(sync.ReviewRequired):
                sync.parse(value,'unlock')

    def test_unknown_mitm_host_rejected(self):
        for kind in sync.PROJECTS:
            with self.assertRaises(sync.ReviewRequired):
                sync.parse(fixture(kind).replace(b'pan.baidu.com, afd.baidu.com',b'*.baidu.com'),'ads' if kind=='ads' else 'unlock')

    def test_safe_paired_write_and_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);files={Path('a/module'):b'module',Path('b/script'):b'original\r\n'}
            self.assertEqual(set(sync.write_bundle(root,files)),{str(p) for p in files})
            times={p:(root/p).stat().st_mtime_ns for p in files}
            self.assertEqual(sync.write_bundle(root,files),[])
            for p,data in files.items():
                self.assertEqual((root/p).read_bytes(),data)
                self.assertEqual((root/p).stat().st_mtime_ns,times[p])

    def test_second_replace_failure_restores_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old={Path('a'):b'old-a',Path('b'):b'old-b'}
            sync.write_bundle(root,old)
            replace=Path.replace;count=0
            def failing(source,target):
                nonlocal count
                count+=1
                if count==2:raise OSError('injected second failure')
                return replace(source,target)
            with patch.object(Path,'replace',failing),self.assertRaises(OSError):
                sync.write_bundle(root,{Path('a'):b'new-a',Path('b'):b'new-b'})
            for p,data in old.items():self.assertEqual((root/p).read_bytes(),data)
            self.assertFalse((root/'b.sync-tmp').exists())

    def test_validation_failure_leaves_existing_publication_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'input.js';source.write_bytes(fixture('ads'))
            target=Path(sync.PROJECTS['ads']['module']);sync.write_bundle(root,{target:b'last valid module'})
            with patch.object(sync,'prepare',side_effect=sync.ReviewRequired('test validation error')):
                result=sync.main(['--kind','ads','--source',str(source),'--root',str(root)])
            self.assertEqual(result,2)
            self.assertEqual((root/target).read_bytes(),b'last valid module')


if __name__=='__main__':
    unittest.main(verbosity=2)
