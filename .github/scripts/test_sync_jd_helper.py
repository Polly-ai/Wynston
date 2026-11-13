#!/usr/bin/env python3
import importlib.util,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('sync',Path(__file__).with_name('sync_jd_helper.py'))
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
SOURCE=('''#!name=京东助手
#!desc=Original description
#!arguments=JD_UNION_ID:null,JTT_APPKEY:null
[Script]
one = type=http-response,pattern=^https://in.example/,requires-body=1,max-size=-1,script-path=URL,argument=test
{{{MMMCK_SCRIPT}}} = type=http-request,pattern=^https://mmm.example/,requires-body=1,max-size=0,script-path=URL,timeout=30
[MITM]
hostname = %APPEND% in.m.jd.com, lite-in.m.jd.com, apapia-sqk-weblogic.manmanbuy.com
''').replace('URL',s.SCRIPT_URL).encode()
JS=b'// original\n$done({});\n'
class Tests(unittest.TestCase):
 def test_exact_minimal_changes(self):
  expected=b'#!category=Polly-ai\n'+SOURCE.replace(('script-path='+s.SCRIPT_URL).encode(),('script-path='+s.RAW+s.SCRIPT.as_posix()).encode())
  self.assertEqual(s.render(SOURCE,JS),expected)
 def test_invalid_reference(self):
  with self.assertRaises(s.ReviewRequired):s.render(SOURCE.replace(s.SCRIPT_URL.encode(),b'https://invalid.example/a.js'),JS)
 def test_invalid_type(self):
  with self.assertRaises(s.ReviewRequired):s.render(SOURCE.replace(b'type=http-request',b'type=unknown'),JS)
 def test_missing_rule(self):
  with self.assertRaises(s.ReviewRequired):s.render(SOURCE.replace(b'{{{MMMCK_SCRIPT}}} =',b'# disabled ='),JS)
 def test_noop(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);files={Path('a'):b'original\r\n'};self.assertEqual(s.write(root,files),['a']);t=(root/'a').stat().st_mtime_ns;self.assertEqual(s.write(root,files),[]);self.assertEqual((root/'a').stat().st_mtime_ns,t)
 def test_rollback(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);old={Path('a'):b'old-a',Path('b'):b'old-b'};s.write(root,old);real=Path.replace;count=0
   def failed(a,b):
    nonlocal count
    count+=1
    if count==2:raise OSError('test failure')
    return real(a,b)
   with patch.object(Path,'replace',failed),self.assertRaises(OSError):s.write(root,{Path('a'):b'new-a',Path('b'):b'new-b'})
   for p,b in old.items():self.assertEqual((root/p).read_bytes(),b)
if __name__=='__main__':unittest.main(verbosity=2)
