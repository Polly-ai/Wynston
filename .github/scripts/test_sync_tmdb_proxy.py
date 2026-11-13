import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import sync_tmdb_proxy as s
M=('#!name=TMDB\n#!desc=原描述\n#!arguments=x:true\n[Script]\na = type=http-request, script-path='+s.BASE+'tmdb_proxy_request.js\nb = type=http-response,requires-body=true,max-size=0, script-path='+s.BASE+'tmdb_proxy_response.js\n[MITM]\nhostname = %APPEND% api.tmdb.org\n').encode()
class Tests(unittest.TestCase):
 def test_exact_changes(self):
  expected=b'#!category=Polly-ai\n'+M
  for n in s.NAMES:expected=expected.replace(('script-path='+s.BASE+n).encode(),('script-path='+s.RAW+str(s.ASSETS/n)).encode())
  self.assertEqual(s.render(M),expected)
 def test_bad_dependency(self):
  with self.assertRaises(ValueError):s.references(M.replace(s.BASE.encode(),b'https://invalid.example/'))
 def test_missing_dependency(self):
  with self.assertRaises(ValueError):s.references(M.replace(b'b = type=',b'# b = type='))
 def test_noop_bytes(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);f={Path('a'):b'original\r\n'};s.write_bundle(r,f);t=(r/'a').stat().st_mtime_ns;self.assertEqual(s.write_bundle(r,f),[]);self.assertEqual((r/'a').read_bytes(),f[Path('a')]);self.assertEqual((r/'a').stat().st_mtime_ns,t)
 def test_rollback(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);old={Path('a'):b'old-a',Path('b'):b'old-b'};s.write_bundle(r,old);real=Path.replace;count=0
   def fail(a,b):
    nonlocal count
    count+=1
    if count==2:raise OSError('test')
    return real(a,b)
   with patch.object(Path,'replace',fail),self.assertRaises(OSError):s.write_bundle(r,{Path('a'):b'new',Path('b'):b'new'})
   for p,b in old.items():self.assertEqual((r/p).read_bytes(),b)
if __name__=='__main__':unittest.main(verbosity=2)
