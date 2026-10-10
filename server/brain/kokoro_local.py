"""Optional offline Kokoro v1.0. Runtime never installs or downloads assets."""
import importlib.util
import sys
import threading
from pathlib import Path
import numpy as np

REPOSITORY='hexgrad/Kokoro-82M'
REVISION='f3ff3571791e39611d31c381e3a41a3af07b4987'
ASSETS={
 'config.json':dict(size=2351,git_sha1='14a726edd3718279eac426630879ff743955b16a'),
 'kokoro-v1_0.pth':dict(size=327212226,sha256='496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4'),
 'voices/af_heart.pt':dict(size=523425,sha256='0ab5709b8ffab19bfd849cd11d98f75b60af7733253ad0d67b12382a102cb4ff'),
}
_lock=threading.RLock(); _pipeline=None

def model_folder():
    return (Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent)/'models'/'tts'/'kokoro'


def load_pipeline(folder):
    if not all((folder/name).is_file() for name in ASSETS): raise RuntimeError('Kokoro assets missing. Run setup-local-voice.cmd.')
    if importlib.util.find_spec('kokoro') is None or importlib.util.find_spec('en_core_web_sm') is None: raise RuntimeError('Kokoro dependencies missing. Run setup-local-voice.cmd.')
    from kokoro import KModel,KPipeline
    model=KModel(repo_id=REPOSITORY,config=str(folder/'config.json'),model=str(folder/'kokoro-v1_0.pth')).to('cpu').eval()
    return KPipeline(lang_code='a',repo_id=REPOSITORY,model=model,device='cpu')


def synthesize(text,settings,pipeline=None):
    global _pipeline
    with _lock:
        folder=model_folder()
        if pipeline is None:
            voice=folder/'voices'/(settings['kokoro_voice']+'.pt')
            if not voice.is_file(): raise RuntimeError('Selected local voice pack is missing. Run setup-local-voice.cmd.')
            if _pipeline is None: _pipeline=load_pipeline(folder)
            pipeline=_pipeline
        else: voice=folder/'voices'/(settings['kokoro_voice']+'.pt')
        audio=[]
        for result in pipeline(text,voice=str(voice),speed=settings['speed']):
            samples=result.audio if hasattr(result,'audio') else result[2]
            if hasattr(samples,'detach'): samples=samples.detach().cpu().numpy()
            samples=np.asarray(samples,dtype=np.float32).reshape(-1)
            if not np.all(np.isfinite(samples)): raise RuntimeError('Invalid local TTS audio.')
            if len(samples): audio.append(samples)
        if not audio: raise RuntimeError('Local TTS produced no audio.')
        from .mouth import samples_to_pcm16k
        return samples_to_pcm16k(np.concatenate(audio),24000)
