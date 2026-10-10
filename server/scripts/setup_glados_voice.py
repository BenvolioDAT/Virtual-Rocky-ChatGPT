"""Explicit official model installation, with bounded, allowlisted tar extraction."""
import hashlib
import json
import re
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from brain.glados_local import model_folder,validate_assets

URL='https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-glados.tar.bz2'
ROOT='vits-piper-en_US-glados'
MAX_DOWNLOAD=100*1024*1024
MAX_EXPANDED=256*1024*1024


def safe_extract(archive,destination):
    """Never use extractall: reject links, special files and unsafe Windows paths."""
    destination=Path(destination).resolve()
    total=0; seen=set()
    with tarfile.open(archive,'r:bz2') as tar:
        for index,member in enumerate(tar):
            if index >= 4000: raise ValueError('Too many archive entries')
            path=PurePosixPath(member.name)
            raw=member.name.rstrip('/').split('/')
            if path.is_absolute() or any(p in ('','.', '..') for p in raw) or '\\' in member.name or ':' in member.name:
                raise ValueError('Unsafe archive path')
            if not raw or raw[0] != ROOT: raise ValueError('Unexpected archive root')
            if not (member.isfile() or member.isdir()): raise ValueError('Archive links and special files are forbidden')
            relative=raw[1:]
            if not relative:
                if not member.isdir(): raise ValueError('Invalid archive root')
                continue
            for part in relative:
                if part.endswith((' ','.')) or re.search(r'[<>"|?*\x00-\x1f]',part) or re.fullmatch(r'(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?',part,re.I):
                    raise ValueError('Unsafe Windows filename')
            allowed=relative[0]=='espeak-ng-data' or (len(relative)==1 and relative[0] in ('en_US-glados.onnx','tokens.txt','README.md','LICENSE','MODEL_CARD'))
            if not allowed: raise ValueError('Unexpected model package file')
            key='/'.join(relative).casefold()
            if key in seen: raise ValueError('Duplicate archive path')
            seen.add(key)
            target=destination.joinpath(*relative).resolve()
            if not target.is_relative_to(destination): raise ValueError('Archive path escaped destination')
            if member.isdir():
                target.mkdir(parents=True,exist_ok=True)
                continue
            total+=member.size
            if member.size < 0 or total > MAX_EXPANDED: raise ValueError('Expanded archive exceeds size limit')
            target.parent.mkdir(parents=True,exist_ok=True)
            source=tar.extractfile(member)
            if source is None: raise ValueError('Unreadable archive file')
            with source, target.open('xb') as output:
                remaining=member.size
                while remaining:
                    chunk=source.read(min(1024*1024,remaining))
                    if not chunk: raise ValueError('Truncated archive file')
                    output.write(chunk); remaining-=len(chunk)
    validate_assets(destination)
    if not 50*1024*1024 <= (destination/'en_US-glados.onnx').stat().st_size <= 80*1024*1024:
        raise ValueError('Unexpected GLaDOS model size')


def download(destination):
    request=urllib.request.Request(URL,headers={'User-Agent':'Virtual-Rocky-optional-model-setup'})
    digest=hashlib.sha256(); size=0
    with urllib.request.urlopen(request,timeout=60) as response,Path(destination).open('xb') as output:
        if not response.geturl().startswith('https://'): raise ValueError('Insecure download redirect')
        length=int(response.headers.get('Content-Length','0'))
        if length > MAX_DOWNLOAD: raise ValueError('Model download exceeds size limit')
        while chunk:=response.read(1024*1024):
            size+=len(chunk)
            if size > MAX_DOWNLOAD: raise ValueError('Model download exceeds size limit')
            digest.update(chunk); output.write(chunk)
        if not size or (length and length!=size): raise ValueError('Incomplete model download')
    # Recorded for provenance only: upstream has no authoritative archive digest.
    return dict(download_bytes=size,observed_sha256=digest.hexdigest())


def install(folder=None):
    folder=Path(folder or model_folder()).resolve()
    if folder.exists():
        try: validate_assets(folder)
        except RuntimeError as exc:
            raise RuntimeError(f'{exc} Rename the incomplete model folder before retrying: {folder}') from exc
        print(f'GLaDOS model already installed: {folder}')
        return
    folder.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.glados-setup-',dir=folder.parent) as temp:
        staging=Path(temp); archive=staging/'model.tar.bz2'; content=staging/'model'; content.mkdir()
        print('Downloading the official sherpa-onnx GLaDOS package (about 67 MB)...')
        observed=download(archive)
        safe_extract(archive,content)
        provenance={'source':URL,'credits':['dnhkng/GLaDOS','k2-fsa/sherpa-onnx','Piper/VITS'],
                    'authoritative_archive_checksum':None,**observed}
        (content/'provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
        content.rename(folder)
    print(f'GLaDOS Local voice setup succeeded: {folder}\nChoose Personality > GLaDOS, then Voice > Test Voice.')


if __name__=='__main__':
    try: install()
    except Exception as exc:
        print(f'GLaDOS voice setup failed: {exc}',file=sys.stderr)
        sys.exit(1)
