"""Explicit downloader for pinned official Apache-2.0 Kokoro assets."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from brain.kokoro_local import REPOSITORY,REVISION,ASSETS,model_folder


def verify(path,info):
    if not path.is_file() or path.stat().st_size!=info['size']: return False
    digest=hashlib.sha256() if 'sha256' in info else hashlib.sha1()
    if 'git_sha1' in info: digest.update(f"blob {info['size']}\0".encode())
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
    return digest.hexdigest()==info.get('sha256',info.get('git_sha1'))


def setup(folder=None):
    folder=Path(folder) if folder else model_folder(); folder.mkdir(parents=True,exist_ok=True)
    for name,info in ASSETS.items():
        target=folder/name; target.parent.mkdir(parents=True,exist_ok=True)
        if verify(target,info): print(name+': verified'); continue
        url=f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}'
        temporary=target.with_suffix(target.suffix+'.download')
        print('Downloading pinned official asset: '+name)
        try:
            with urllib.request.urlopen(url,timeout=60) as response, temporary.open('wb') as output:
                size=0
                for chunk in iter(lambda:response.read(1024*1024),b''):
                    size+=len(chunk)
                    if size>info['size']: raise ValueError('Unexpected asset size')
                    output.write(chunk)
            if not verify(temporary,info): raise ValueError('Asset hash verification failed')
            temporary.replace(target)
        finally: temporary.unlink(missing_ok=True)
    (folder/'provenance.json').write_text(json.dumps(dict(repository=REPOSITORY,revision=REVISION,model_version='1.0',license='Apache-2.0',license_url='https://www.apache.org/licenses/LICENSE-2.0',source='https://huggingface.co/'+REPOSITORY,assets=ASSETS),indent=2),encoding='utf-8')
    print('Kokoro ready. This is a generic synthetic voice, not an actor clone.')

if __name__=='__main__': setup()
