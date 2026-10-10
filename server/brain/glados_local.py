"""Optional CPU GLaDOS-style Piper/VITS TTS. No runtime network access."""
import sys
import threading
from pathlib import Path

_lock=threading.RLock()
_tts=None


def model_folder():
    base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
    return base/'models'/'glados'


def validate_assets(folder):
    folder=Path(folder)
    for name in ('en_US-glados.onnx','tokens.txt','espeak-ng-data/phontab','espeak-ng-data/phondata','espeak-ng-data/phonindex','espeak-ng-data/en_dict'):
        path=folder/name
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError(f'GLaDOS asset missing or empty: {name}. Run setup-glados-voice.cmd.')
    if not (folder/'espeak-ng-data/lang').is_dir():
        raise RuntimeError('GLaDOS phonemizer language data missing. Run setup-glados-voice.cmd.')


def load_model(folder):
    validate_assets(folder)
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise RuntimeError('sherpa-onnx is not installed. Run setup-glados-voice.cmd.') from exc
    config=sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(folder/'en_US-glados.onnx'),tokens=str(folder/'tokens.txt'),
                data_dir=str(folder/'espeak-ng-data')),
            provider='cpu',num_threads=2,debug=False),max_num_sentences=1)
    if not config.validate(): raise RuntimeError('Invalid GLaDOS TTS configuration. Run setup-glados-voice.cmd.')
    return sherpa_onnx.OfflineTts(config)


def synthesize(text,settings):
    global _tts
    with _lock:
        if _tts is None: _tts=load_model(model_folder())
        try:
            import sherpa_onnx
            generation=sherpa_onnx.GenerationConfig()
            generation.sid=0
            # Sherpa maps speed to inverse VITS length_scale; 1.0 is natural.
            generation.speed=settings['speed']
            audio=_tts.generate(text,generation)
            from .mouth import samples_to_pcm16k
            return samples_to_pcm16k(audio.samples,audio.sample_rate)
        except Exception:
            # A repaired installation can be retried on the next utterance.
            _tts=None
            raise
