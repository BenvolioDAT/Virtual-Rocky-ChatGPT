"""Bounded, expiring image RAM. Never persists or calls a provider."""
from collections import deque
from dataclasses import dataclass
import io
import threading
import time
from . import settings


def temporal_count(question):
    import re
    q = question.lower()
    if re.search(r'just happened|happened.*(game|health)|health.*(drop|happen)|shield.*(drop|happen)|why did.*(drop|lose)', q): return 3
    if re.search(r'did.*(move|change)|what changed|compare|before|why did that happen', q): return 1
    return 0


@dataclass
class VisualFrame:
    timestamp: float
    jpeg: bytes
    metadata: dict
    change_score: float
    signature: bytes


def selection_key(metadata):
    selection=metadata.get('selection',{})
    selected=metadata.get('selected',{})
    monitor=selection.get('monitor')
    identity=monitor if monitor in ('active','all') else selected.get('id',monitor)
    region=selection.get('region')
    return (identity,tuple(sorted(region.items())) if region else None,
            tuple(selected.get(k) for k in ('x','y','width','height')))


class VisualMemory:
    def __init__(self, max_frames=settings.SCREEN_MEMORY_MAX_FRAMES, max_seconds=settings.SCREEN_MEMORY_MAX_SECONDS,
                 threshold=settings.SCREEN_CHANGE_THRESHOLD, clock=time.time):
        self.frames = deque(maxlen=max_frames)
        self.max_seconds, self.threshold, self.clock = max_seconds, threshold, clock
        self.signature = None
        self.lock = threading.RLock()
        self.accepted = self.ignored = 0
    def prune(self):
        with self.lock:
            while self.frames and self.clock()-self.frames[0].timestamp > self.max_seconds:
                self.frames.popleft()
            if not self.frames: self.signature = None
    def clear(self):
        with self.lock:
            self.frames.clear(); self.signature = None
    def observe(self, image, metadata):
        from PIL import Image
        with image.convert('L') as gray:
            with gray.resize(settings.SCREEN_COMPARE_SIZE, Image.Resampling.BILINEAR) as tiny:
                signature = tiny.tobytes()
        with self.lock:
            self.prune()
            score = 1.0 if self.signature is None else sum(abs(a-b) for a,b in zip(signature,self.signature))/(255*len(signature))
            if score < self.threshold:
                self.ignored += 1
                return False, score
            self.signature = signature
            # Encode only retained, meaningful history frames; never a full-resolution watch JPEG.
            with image.copy() as preview:
                preview.thumbnail(settings.SCREEN_HISTORY_SIZE)
                with io.BytesIO() as buffer:
                    preview.save(buffer,'JPEG',quality=settings.SCREEN_OVERVIEW_QUALITY)
                    meta = dict(metadata, image_width=preview.width,image_height=preview.height,capture_source='screen_watch')
                    self.frames.append(VisualFrame(self.clock(),buffer.getvalue(),meta,score,signature))
            self.accepted += 1
            return True,score
    def select(self, current_metadata, count, current_jpeg=None):
        signature = None
        if current_jpeg and count:
            from PIL import Image
            with Image.open(io.BytesIO(current_jpeg)) as image:
                with image.convert('L') as gray:
                    with gray.resize(settings.SCREEN_COMPARE_SIZE) as small: signature = small.tobytes()
        with self.lock:
            self.prune()
            candidates = [f for f in self.frames if selection_key(f.metadata) == selection_key(current_metadata)
                          and f.metadata.get('window',{}).get('handle') == current_metadata.get('window',{}).get('handle')]
            if signature:
                candidates = [f for f in candidates if sum(abs(a-b) for a,b in zip(signature,f.signature))/(255*len(signature)) >= self.threshold]
            return candidates[-min(3,count):] if count else []
    def status(self):
        with self.lock:
            self.prune()
            return dict(frames=len(self.frames),max_frames=self.frames.maxlen,
                        bytes=sum(len(f.jpeg)+len(f.signature) for f in self.frames)+len(self.signature or b''),accepted=self.accepted,ignored=self.ignored,
                        oldest_age=round(self.clock()-self.frames[0].timestamp,1) if self.frames else None,
                        last_change_age=round(self.clock()-self.frames[-1].timestamp,1) if self.frames else None)
