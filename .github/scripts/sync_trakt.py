"""Mirror the upstream module and exact dependencies; validate before writing."""
import json
import pathlib
import re
import subprocess
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = 'https://raw.githubusercontent.com/DemoJameson/Proxy.Modules/main/trakt_simplified_chinese/'
DEST = 'https://raw.githubusercontent.com/Polly-ai/Wynston/main/'
MODULE = 'Surge/Module/trakt_simplified_chinese.sgmodule'
ASSETS = 'Surge/JavaScript/Trakt/'

def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Wynston-Trakt-mirror'})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if not data:
        raise ValueError('Empty upstream response: ' + url)
    return data

def build(module, loader):
    text = module.decode('utf-8')
    if not text.startswith('#!name=') or '[Script]' not in text or '[MITM]' not in text:
        raise ValueError('Invalid Surge module')
    urls = set(re.findall(r'script-path=(https?://[^\s,]+)', text))
    rules = [line for line in text.splitlines() if re.search(r'=\s*type=http-', line)]
    if not urls or len(re.findall(r'script-path=', text)) != len(rules):
        raise ValueError('Missing or unsupported script references')
    files = {}
    for url in sorted(urls):
        if not url.startswith(SOURCE):
            raise ValueError('New upstream source requires review: ' + url)
        name = url[len(SOURCE):]
        if not re.fullmatch(r'[A-Za-z0-9_-]+\.js', name):
            raise ValueError('Unsupported dependency path')
        data = loader(url)
        if len(data) < 100 or data.lstrip().startswith(b'<'):
            raise ValueError('Invalid JavaScript response')
        with tempfile.TemporaryDirectory() as directory:
            script = pathlib.Path(directory) / name
            script.write_bytes(data)
            subprocess.run(['node', '--check', str(script)], check=True, capture_output=True)
        files[ASSETS + name] = data
        text = text.replace('script-path=' + url, 'script-path=' + DEST + ASSETS + name)
    icon = re.search(r'^#!icon=(\S+)$', text, re.M)
    if icon and icon[1] == SOURCE + 'images/trakt.webp':
        image = loader(icon[1])
        if image[:4] != b'RIFF' or image[8:12] != b'WEBP':
            raise ValueError('Invalid WebP icon')
        path = ASSETS + 'images/trakt.webp'
        files[path] = image
        text = text.replace('#!icon=' + icon[1], '#!icon=' + DEST + path)
    text = re.sub(r'^#!category\s*=.*\n?', '', text, flags=re.M)
    text = text.replace('\n', '\n#!category = Polly-ai\n', 1)
    files[MODULE] = text.encode('utf-8')
    return files

def sync(root=ROOT, loader=fetch):
    info = json.loads(loader('https://api.github.com/repos/DemoJameson/Proxy.Modules/commits/main'))
    sha = info['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Invalid upstream commit')
    def pinned(url):
        return loader(url.replace('/Proxy.Modules/main/', '/Proxy.Modules/' + sha + '/'))
    files = build(pinned(SOURCE + 'trakt_simplified_chinese.sgmodule'), pinned)
    # Nothing is written until all downloads and syntax checks have succeeded.
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != data:
            temporary = target.with_suffix(target.suffix + '.tmp')
            temporary.write_bytes(data)
            temporary.replace(target)
            print('Updated', name)
    print('Validated upstream commit', sha, 'assets:', len(files))
    return files

if __name__ == '__main__':
    sync()
