"""Loopback client only. This module has no desktop capture APIs."""
import base64
import itertools
import os
import queue
import secrets
import subprocess
import sys
import time
from pathlib import Path
from screen_diagnostics import log
from desktop_vision.memory import temporal_count
from desktop_vision import settings as screen_settings
import json
import re
import threading
import urllib.request
import urllib.error


def wants_screen(question):
    return bool(re.search(r'\b(screen|desktop|monitor|monitors|application|program|click|error|warning|youtube|browser|website|webpage|tab|game|health|shield|enemy)\b|what am i (looking at|doing)|video.*(pulled up|open|playing)', question, re.I))


def vision_source(question, previous=None):
    """Resolve only active visual requests; retain source for short follow-ups."""
    if re.search(r'look at me|can you see me|what am i holding|what.*shirt.*wear|\b(webcam|clothing)\b', question, re.I):
        return 'camera'
    if wants_screen(question):
        return 'screen'
    if previous and re.search(r'\b(see|look|read|show)\b.*\b(it|this|that|now|again|enemy)\b|what about (now|this|that)|try again|what just happened|why did that happen', question, re.I):
        return previous
    return None


def watch_command(question, previous=None, watching=False):
    q = question.lower().strip().rstrip('.!?')
    if re.search(r'\bstop watching me\b',q): return None
    if re.search(r'\bstop (watching|observing)\b',q) and ('screen' in q or 'game' in q or previous == 'screen' or watching):
        return 'screen stopwatch'
    if re.search(r'\bwatch (my |the )?(screen|game|monitor|active window)|keep an eye on this',q):
        match = re.search(r'monitor\s+(\d+|one|two|three)',q)
        monitor = {'one':'1','two':'2','three':'3'}.get(match[1],match[1]) if match else 'active' if 'active window' in q else 'primary'
        return 'screen watch ' + monitor + (' game' if 'game' in q else '')
    return None


def model_metadata(metadata):
    """Keep provider context useful; performance/session diagnostics stay local."""
    keys=('timestamp','seconds_ago','current','monitor','selection','image_width','image_height','tier','capture_source','change_score','active_fallback','ocr')
    result={k:metadata[k] for k in keys if k in metadata}
    if 'selected' in metadata:
        result['selected']={k:v for k,v in metadata['selected'].items() if k in ('id','x','y','width','height','primary')}
    if metadata.get('window'):
        result['window']={k:v for k,v in metadata['window'].items() if k in ('title','monitor','x','y','width','height')}
    return result


class ScreenClient:
    def __init__(self, port=47831):
        self.url = f'http://127.0.0.1:{port}'
        self.token = None
        self.local = threading.local()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.state = 'Disabled'
        self.last_request = None
        self.last_capture = None
        self.connected_at = None
        self.session_id = None
        self.monitor_list = []
        self.generation = 0
        self._counter = itertools.count(1)
        self.watch_info = {}
        self.model_image_count = 0
        self.last_model_request = None

    def disconnect(self):
        self.generation += 1
        self.token = None
        self.connected_at = None
        self.monitor_list = []
        self.state = 'Disabled'
        self.watch_info = {}
        log('disconnected', session=self.session_id)

    def request(self, path, args=None):
        token, generation = self.token, self.generation
        if not token:
            if self.state in ('Offline', 'Error'):
                raise ValueError('I cannot see your desktop right now. Screen Vision is ' + self.state.lower() + '. Enable it again or check Status.')
            raise ValueError('I cannot see your desktop right now. Screen Vision is disabled.')
        request_id = next(self._counter)
        log('request', session=self.session_id, request=request_id, endpoint=path,
            monitor=(args or {}).get('monitor', '-'))
        request = urllib.request.Request(self.url + path,
            data=json.dumps(args).encode() if args is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                     'X-Request-ID': str(request_id)})
        try:
            with self.opener.open(request, timeout=5) as response:
                body = response.read(24 * 1024 * 1024 + 1)
                if len(body) > 24 * 1024 * 1024:
                    raise ValueError('Screenshot response too large.')
                result = json.loads(body)
                if generation != self.generation or token != self.token:
                    raise ValueError('Screen Vision disconnected during this request; image discarded.')
                if path == '/capture':
                    self.last_request = 'success'
                    self.last_capture = result['metadata']
                return result
        except urllib.error.HTTPError as exc:
            if generation != self.generation or token != self.token:
                raise ValueError('Screen Vision disconnected during this request; image discarded.') from None
            try:
                detail = json.loads(exc.read(4096)).get('error', 'Request rejected.')
            except Exception:
                detail = 'Request rejected.'
            log('rejected', session=self.session_id, request=request_id, status=exc.code, reason=detail)
            self.last_request = detail
            if exc.code == 401:
                if token == self.token:
                    self.token = None
                    self.state = 'Error'
                raise ValueError('Screen Vision authentication rejected; disable and enable to create a new session.') from None
            if exc.code == 403:
                self.state = 'Paused'
            raise ValueError(detail) from None
        except (OSError, urllib.error.URLError) as exc:
            if generation != self.generation or token != self.token:
                raise ValueError('Screen Vision disconnected during this request; image discarded.') from None
            reason = 'timeout' if isinstance(exc, TimeoutError) or isinstance(getattr(exc, 'reason', None), TimeoutError) else 'connection_lost'
            self.last_request = reason
            self.state = 'Offline'
            log(reason, session=self.session_id, request=request_id)
            raise ValueError('I can’t see your desktop right now. Screen Vision connection is unavailable (' + reason + ').') from None

    def status(self):
        if not self.token:
            return self.state if self.state in ('Error', 'Offline') else 'Disabled'
        try:
            result = self.request('/status')
            self.state = result['status']
            self.watch_info = result.get('watch',{})
            return self.state
        except Exception:
            return self.state if self.state in ('Error', 'Offline') else 'Offline'

    def monitors(self, args):
        try:
            self.monitor_list = self.request('/monitors')
            return json.dumps(self.monitor_list), None
        except Exception as exc:
            return str(exc), None

    def look(self, args):
        if not getattr(self.local, 'requested', False):
            log('capture_rejected', reason='no_active_screen_request')
            return 'Desktop capture requires an active screen-related question from the human.', None
        if self.state == 'Paused':
            return 'Desktop access is paused in the helper.', None
        budget = getattr(self.local,'capture_budget',None)
        if budget is not None:
            if budget <= 0: return 'Screen capture limit reached for this reply. Answer from the supplied images or ask a follow-up.', None
            self.local.capture_budget -= 1
        try:
            question = getattr(self.local,'question','')
            args = dict(args)
            args.setdefault('monitor', self.watch_info.get('monitor','primary'))
            args.setdefault('tier','detail' if args.get('region') or re.search(r'small text|read|closer|warning|error',question,re.I) else 'overview')
            count = temporal_count(question)
            if screen_settings.SCREEN_OCR_ENABLED and re.search(r'read|text|warning|error',question,re.I): args['ocr'] = True
            args['history_count'] = 0 if args.get('region') else count
            result = self.request('/capture', args)
            desktop_frame = base64.b64decode(result['jpeg'], validate=True)
            history = result.get('history',[])[:min(3,count)] if count and not args.get('region') else []
            if history:
                images = [{'text':str(f['metadata']['seconds_ago']) + ' seconds ago; historical changed screenshot, not current. ' + json.dumps(model_metadata(f['metadata'])),
                           'jpeg':base64.b64decode(f['jpeg'],validate=True)} for f in history]
                images.append({'text':'Current fresh screenshot. ' + json.dumps(model_metadata(result['metadata'])),'jpeg':desktop_frame})
                self.model_image_count += len(images)
                self.last_model_request = time.time()
                return 'Temporal desktop observations, oldest to current. Only infer visible changes; unseen events and causes are uncertain.', images
            self.model_image_count += 1
            self.last_model_request = time.time()
            note = ' No relevant historical frames are available; earlier events cannot be established from this image.' if count and not args.get('region') else ''
            return ('Fresh desktop screenshot taken for this request.' + note + ' Monitor metadata: ' +
                    json.dumps(model_metadata(result['metadata'])), desktop_frame)
        except Exception as exc:
            return str(exc), None


class ScreenVisionManager:
    """Own one visible child. No persistence or automatic process restart."""
    def __init__(self, client):
        self.client = client
        self.process = None
        self._session_token = None
        self.lock = threading.RLock()
        self.failed_reconnects = 0
        self.start_time = None

    def enable(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                if self.client.state in ('Connected', 'Watching', 'Paused', 'Starting'):
                    return self.client.state
                self.disable()  # New launch only after an explicit Enable action.
            self.client.disconnect()
            self.client.state = 'Starting'
            token = secrets.token_urlsafe(32)
            self._session_token = token
            self.client.token = token
            env = os.environ.copy()
            env.update(ROCKY_SCREEN_TOKEN=token, ROCKY_SCREEN_PORT='0',
                       ROCKY_SCREEN_PARENT=str(os.getpid()))
            command = [sys.executable, '-m', 'desktop_vision.screen_bridge']
            if getattr(sys, 'frozen', False):
                command = [sys.executable, '--screen-helper']
            try:
                self.process = subprocess.Popen(command, cwd=str(Path(__file__).resolve().parent.parent),
                                                env=env, stdout=subprocess.PIPE, text=True,
                                                encoding='utf-8', bufsize=1)
                self.start_time = time.monotonic()
                log('helper_starting', pid=self.process.pid)
                ready_queue = queue.Queue()
                process = self.process
                def read_ready():
                    try: ready_queue.put(process.stdout.readline())
                    except Exception: ready_queue.put('')
                threading.Thread(target=read_ready, daemon=True).start()
                ready = json.loads(ready_queue.get(timeout=10))
                if ready.get('type') != 'screen_ready' or not 0 < ready.get('port', 0) <= 65535:
                    raise ValueError('Invalid helper readiness message.')
                self.client.url = f"http://127.0.0.1:{ready['port']}"
                self.client.session_id = ready['session_id']
                self.process.stdout.close()
                state = self.client.status()
                if state != 'Connected':
                    raise ValueError('Helper authentication failed.')
                self.client.monitor_list = self.client.request('/monitors')
                if not self.client.monitor_list:
                    raise ValueError('No displays detected.')
                self.client.connected_at = time.monotonic()
                self.failed_reconnects = 0
                log('connected', session=self.client.session_id, pid=self.process.pid,
                    monitors=len(self.client.monitor_list))
                return state
            except Exception as exc:
                log('startup_failed', reason=type(exc).__name__)
                self.client.last_request = 'Helper startup failed (' + type(exc).__name__ + '). Check the helper console and optional dependencies.'
                self.disable()
                self.client.state = 'Error'
                return 'Error'
            finally:
                env.pop('ROCKY_SCREEN_TOKEN', None)

    def disable(self):
        # Invalidate locally first, including any response still in flight.
        token, url = self._session_token or self.client.token, self.client.url
        self.client.disconnect()
        with self.lock:
            process, self.process = self.process, None
            if process and process.poll() is None:
                try:
                    request = urllib.request.Request(url + '/shutdown', data=b'{}',
                        headers={'Authorization':'Bearer ' + (token or ''), 'Content-Type':'application/json'})
                    with self.client.opener.open(request, timeout=1): pass
                except Exception:
                    log('shutdown_connection_unavailable', pid=process.pid)
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    log('helper_terminate', pid=process.pid)
                    process.terminate()
                    try: process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
            if process and process.stdout and not process.stdout.closed:
                process.stdout.close()
            self.failed_reconnects = 0
            self._session_token = None
            self.client.state = 'Disabled'
            log('disabled')

    def pause(self, paused=True):
        self.client.generation += 1  # Discard earlier in-flight images even after resume.
        result = self.client.request('/pause', {'paused':paused})
        self.client.state = result['status']
        return self.client.state

    def watch(self, monitor='primary', enabled=True, game=False, interval=None):
        self.client.generation += 1
        result = self.client.request('/watch',dict(enabled=enabled,monitor=monitor,game=game,interval=interval))
        self.client.state = result['status']
        self.client.watch_info = result.get('watch',{})
        return self.client.state

    def poll(self):
        if not self.process:
            return self.client.state
        if self.process.poll() is not None:
            if self.client.state != 'Offline':
                log('helper_exited', pid=self.process.pid, exit_code=self.process.returncode)
            self.client.token = None
            self._session_token = None
            self.client.generation += 1
            self.client.state = 'Offline'
            return 'Offline'
        if self.client.state == 'Error' and self.failed_reconnects >= 3:
            return 'Error'
        state = self.client.status()
        if state == 'Offline':
            self.failed_reconnects += 1
            log('reconnect', attempt=self.failed_reconnects, session=self.client.session_id)
            if self.failed_reconnects >= 3:
                self.client.state = 'Error'
                return 'Error'
        else:
            if self.failed_reconnects: log('reconnected', session=self.client.session_id)
            self.failed_reconnects = 0
        return self.client.state

    def diagnostics(self):
        alive = bool(self.process and self.process.poll() is None)
        return dict(state=self.client.state, process='running' if alive else 'stopped',
                    pid=self.process.pid if alive else None, host='127.0.0.1',
                    session_id=self.client.session_id, monitor_count=len(self.client.monitor_list),
                    capture_allowed=self.client.state in ('Connected','Watching'),watch=self.client.watch_info,
                    model_images_supplied=self.client.model_image_count,last_model_screen_request=self.client.last_model_request,
                    last_request=self.client.last_request, last_capture=self.client.last_capture,
                    connection_age_seconds=round(time.monotonic()-self.client.connected_at) if self.client.connected_at else None)

    def test(self):
        import io
        from PIL import Image  # Optional image decoding only; no capture APIs.
        self.client.monitor_list = self.client.request('/monitors')
        result = self.client.request('/capture', {'monitor':'primary'})
        desktop_frame = base64.b64decode(result['jpeg'], validate=True)
        with Image.open(io.BytesIO(desktop_frame)) as image:
            image.verify()
            dimensions = image.size
        if min(dimensions) < 1:
            raise ValueError('Helper returned an empty image.')
        return 'Screen Vision test passed: ' + json.dumps(result['metadata']) + f"; {len(desktop_frame)} bytes. Image discarded."


screen = ScreenClient()
screen_manager = ScreenVisionManager(screen)
