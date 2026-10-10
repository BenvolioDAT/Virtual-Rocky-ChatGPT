"""Local-only observe worker. This module has no model/provider client."""
import threading
import time
from .memory import VisualMemory
from . import settings


class ScreenWatch:
    def __init__(self, backend, capture_lock):
        self.backend,self.capture_lock = backend,capture_lock
        self.memory = VisualMemory()
        self.watching = False
        self.monitor = 'primary'
        self.interval = settings.SCREEN_WATCH_INTERVAL
        self.stop_event = threading.Event()
        self.generation = 0
        self.thread = None
        self.samples = 0
        self.capture_ms = self.detect_ms = self.cpu_ms = 0.0
        self.error = None
        self.active_window = None
    def start(self, monitor='primary', interval=None, game=False):
        self.stop()
        self.monitor = monitor
        self.interval = interval if interval is not None else settings.SCREEN_WATCH_INTERVAL
        if not isinstance(self.interval,(int,float)) or isinstance(self.interval,bool) or not .5 <= self.interval <= 60:
            raise ValueError('Watch interval must be between 0.5 and 60 seconds.')
        self.memory.threshold = settings.SCREEN_GAME_CHANGE_THRESHOLD if game else settings.SCREEN_CHANGE_THRESHOLD
        self.stop_event = threading.Event()
        self.watching = True
        self.error = None
        generation = self.generation
        self.thread = threading.Thread(target=self.run,args=(generation,self.stop_event),daemon=True,name='local-screen-watch')
        self.thread.start()
    def stop(self):
        self.watching = False
        self.generation += 1
        self.stop_event.set()
        self.memory.clear()
        self.active_window = None
        self.error = None
    def sample(self, generation):
        started,cpu = time.monotonic(),time.process_time()
        with self.capture_lock:
            if generation != self.generation or not self.watching: return
            image,metadata = self.backend.observe(self.monitor)
        captured = time.monotonic()
        try:
            # Fence the RAM write as well as capture; Stop must win over late samples.
            with self.memory.lock:
                if generation != self.generation or not self.watching: return
                self.active_window = metadata.get('_foreground',metadata.get('window'))
                old = self.memory.frames[-1].metadata if self.memory.frames else None
                if old and (old.get('selection') != metadata.get('selection') or
                            old.get('window',{}).get('handle') != metadata.get('window',{}).get('handle')):
                    self.memory.clear()
                self.memory.observe(image,metadata)
        finally: image.close()
        self.samples += 1
        self.capture_ms += (captured-started)*1000
        self.detect_ms += (time.monotonic()-captured)*1000
        self.cpu_ms += (time.process_time()-cpu)*1000
    def run(self, generation, stop_event):
        while generation == self.generation and not stop_event.is_set():
            start = time.monotonic()
            try: self.sample(generation)
            except Exception as exc:
                error = type(exc).__name__ + ': ' + str(exc)[:160]
                self.stop()
                self.error = error
                return
            stop_event.wait(max(.05,self.interval-(time.monotonic()-start)))
    def status(self):
        return dict(watching=self.watching,monitor=self.monitor,interval=self.interval,active_window=self.active_window,
                    threshold=self.memory.threshold,error=self.error,**self.memory.status(),
                    samples=self.samples,average_capture_ms=round(self.capture_ms/max(1,self.samples),2),
                    average_detection_encode_ms=round(self.detect_ms/max(1,self.samples),2),
                    average_cpu_ms=round(self.cpu_ms/max(1,self.samples),2),automatic_cloud_uploads=0)
