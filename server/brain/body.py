"""Body boundary: brain commands and PCM playback, independent of Qt."""
from typing import Protocol
import json
import asyncio

class Body(Protocol):
    virtual: bool
    async def command(self, payload: dict) -> bool: ...
    def play_pcm(self, pcm: bytes) -> None: ...

class PhysicalBody:
    virtual = False
    def __init__(self, socket_provider): self.socket_provider = socket_provider
    async def command(self, payload):
        if payload.get('type') in ('presentation','companion_info','feature_info','source_info'): return True
        if payload.get('type') == 'emotion':
            mapping = {'excited':'happy', 'confused':'thinking', 'curious':'surprised',
                       'worried':'sad', 'skeptical':'thinking'}
            payload = dict(payload, name=mapping.get(payload.get('name'), payload.get('name')))
        socket = self.socket_provider()
        if socket is None: return False
        await socket.send(json.dumps(payload))
        return True
    async def stream_pcm(self, first, next_chunk, done):
        """Original ESP32 binary framing and playback acknowledgment."""
        done.clear()
        await self.command({"type": "speak_begin", "bytes": 0})
        buf = bytearray()
        total = 0
        chunk = first
        while chunk is not None:
            buf += chunk
            while len(buf) >= 3200:
                socket = self.socket_provider()
                if socket is None: return
                await socket.send(b"\x01" + bytes(buf[:3200]))
                del buf[:3200]
                total += 3200
            chunk = await next_chunk()
        socket = self.socket_provider()
        if buf and socket is not None:
            await socket.send(b"\x01" + bytes(buf))
            total += len(buf)
        await self.command({"type": "speak_end"})
        try:
            await asyncio.wait_for(done.wait(), timeout=total / 32000 + 5)
        except asyncio.TimeoutError:
            print("(robot never said it finished speaking)")

    def play_pcm(self, pcm):
        from .mouth import play
        play(pcm)

class VirtualBody:
    virtual = True
    def __init__(self, emit, audio_factory=None):
        self.emit, self.audio_factory = emit, audio_factory
        self.volume = 0.7
    async def command(self, payload):
        if payload.get('type') == 'volume':
            self.volume = max(0.0, min(1.0, float(payload['level'])))
        self.emit(dict(payload))
        return True
    def play_pcm(self, pcm):
        """Blocking 40ms PCM blocks align mouth amplitude with playback."""
        import numpy as np
        import sounddevice as sd
        factory = self.audio_factory or sd.RawOutputStream
        self.emit({'type': 'talking', 'on': True})
        try:
            with factory(samplerate=16000, channels=1, dtype='int16') as output:
                for offset in range(0, len(pcm), 1280):
                    samples = np.frombuffer(pcm[offset:offset+1280], dtype='<i2').astype(np.float32)
                    samples *= self.volume
                    level = float(np.sqrt(np.mean((samples / 32768) ** 2))) if len(samples) else 0
                    self.emit({'type': 'mouth', 'level': min(1.0, level * 8)})
                    output.write(samples.astype('<i2').tobytes())
        finally:
            self.emit({'type': 'mouth', 'level': 0.0})
            self.emit({'type': 'talking', 'on': False})
