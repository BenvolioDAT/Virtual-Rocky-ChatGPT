"""Optional local webcam capture; missing/disconnected cameras are nonfatal."""
import threading
import time
import cv2

class Webcam:
    def __init__(self, eyes, index=0, capture_factory=None):
        self.eyes, self.index = eyes, index
        self.factory = capture_factory or cv2.VideoCapture
        self.stop_event = threading.Event()
        self.thread = None
        self.error = None
    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name='webcam')
        self.thread.start()
    def _run(self):
        capture = None
        try:
            capture = self.factory(self.index)
            if not capture.isOpened():
                self.error = 'No webcam; voice mode is still available.'
                return
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            while not self.stop_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    self.error = 'Webcam disconnected; voice mode is still available.'
                    break
                ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok: self.eyes.push_frame(jpeg.tobytes())
                self.stop_event.wait(.1)
        except Exception as exc:
            self.error = f'Webcam unavailable: {exc}'
        finally:
            from .session_people import manager
            manager.reset()
            if capture is not None: capture.release()
            if self.error: print(self.error)
    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=2)
