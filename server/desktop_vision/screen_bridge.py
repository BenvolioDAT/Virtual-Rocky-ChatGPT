"""Visible, session-authenticated, loopback-only on-demand capture process."""
import base64
import hmac
import json
import secrets
import threading
import os
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .capture import WindowsCapture
from .watch import ScreenWatch
from screen_diagnostics import log

PORT = 47831


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, backend, port=PORT, token=None):
        self.token = token or secrets.token_urlsafe(32)
        self.session_id = secrets.token_hex(8)  # Public diagnostic ID, never a credential.
        self.backend = backend
        self.allowed = True
        self.lock = threading.Lock()
        self.exit_requested = threading.Event()
        self.access_generation = 0
        self.authenticated = False
        self.last_capture = None
        self.watch = ScreenWatch(backend,self.lock)
        super().__init__(('127.0.0.1', port), Handler)
        log('helper_started', session=self.session_id, host='127.0.0.1', port=self.server_port)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log tokens, screenshots or request bodies.

    def respond(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        self.connection.settimeout(5)
        # Reject browser-origin requests, including localhost pages. No CORS.
        try:
            accepted = (not self.headers.get('Origin') and
                self.headers.get('Host') == '127.0.0.1:' + str(self.server.server_port) and
                hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + self.server.token))
        except TypeError:
            accepted = False
        if not accepted:
            log('authentication_rejected', session=self.server.session_id, reason='invalid_session_or_origin')
        elif not self.server.authenticated:
            self.server.authenticated = True
            log('authenticated', session=self.server.session_id)
        return accepted

    def do_GET(self):
        if not self.authorized():
            return self.respond(401, {'error': 'Session authentication required.'})
        try:
            if self.path == '/status':
                return self.respond(200, {'status': 'Paused' if not self.server.allowed else 'Watching' if self.server.watch.watching else 'Error' if self.server.watch.error else 'Connected',
                                          'session_id': self.server.session_id,'watch':self.server.watch.status()})
            if self.path == '/monitors':
                return self.respond(200, self.server.backend.monitors())
            self.respond(404, {'error': 'Unknown endpoint.'})
        except Exception as exc:
            log('discovery_failed', session=self.server.session_id, reason=type(exc).__name__)
            self.respond(503, {'error': 'Monitor discovery failed (' + type(exc).__name__ + ').'})

    def do_POST(self):
        if not self.authorized():
            return self.respond(401, {'error': 'Session authentication required.'})
        if self.path not in ('/capture', '/pause', '/shutdown','/watch'):
            return self.respond(404, {'error': 'Unknown endpoint.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                raise ValueError('Invalid request size.')
            args = json.loads(self.rfile.read(size))
            if self.path == '/shutdown':
                self.server.watch.stop()
                self.server.allowed = False
                self.server.access_generation += 1
                self.respond(200, {'status': 'Disabled'})
                self.server.token = secrets.token_urlsafe(32)
                self.server.exit_requested.set()
                log('shutdown_requested', session=self.server.session_id)
                return
            if self.path == '/pause':
                self.server.watch.stop()
                if not isinstance(args, dict) or type(args.get('paused')) is not bool:
                    raise ValueError('paused must be a boolean.')
                self.server.allowed = not args['paused']
                self.server.access_generation += 1
                log('pause_state', session=self.server.session_id, allowed=self.server.allowed)
                return self.respond(200, {'status': 'Connected' if self.server.allowed else 'Paused'})
            if self.path == '/watch':
                if not isinstance(args,dict) or type(args.get('enabled')) is not bool:
                    raise ValueError('Watch enabled must be a boolean.')
                if not args['enabled']:
                    self.server.watch.stop()
                elif not self.server.allowed:
                    return self.respond(403,{'error':'Desktop access is paused.'})
                else:
                    monitor = args.get('monitor','primary')
                    from .capture import select_monitor
                    if monitor != 'active': select_monitor(self.server.backend.monitors(),monitor)
                    self.server.watch.start(monitor,args.get('interval'),bool(args.get('game',False)))
                self.server.access_generation += 1
                return self.respond(200,{'status':'Watching' if self.server.watch.watching else 'Connected','watch':self.server.watch.status()})
            if not isinstance(args, dict) or set(args) - {'monitor','region','tier','history_count','ocr'}:
                raise ValueError('Unknown capture parameter.')
            history_count = args.get('history_count',0)
            if type(history_count) is not int or not 0 <= history_count <= 3:
                raise ValueError('History count must be 0 to 3.')
            with self.server.lock:
                if not self.server.allowed:
                    return self.respond(403, {'error': 'Desktop access is paused.'})
                request_id = self.headers.get('X-Request-ID', '-')[:64]
                selection = args.get('monitor', 'primary')
                generation = self.server.access_generation
                started = time.monotonic()
                log('capture_start', session=self.server.session_id, request=request_id, monitor=selection)
                if args.get('region') is not None or args.get('tier') is not None or selection == 'active':
                    jpeg,metadata = self.server.backend.capture(selection,region=args.get('region'),tier=args.get('tier','overview'))
                else: jpeg, metadata = self.server.backend.capture(selection)
                if not self.server.allowed or generation != self.server.access_generation:
                    return self.respond(403, {'error': 'Desktop access is paused.'})
                metadata.update(timestamp=datetime.now(timezone.utc).isoformat(),
                                success=True, current=True, seconds_ago=0, capture_source='screen_request',
                                monitor=selection, request_id=request_id, session_id=self.server.session_id,
                                duration_ms=round((time.monotonic()-started)*1000), bytes=len(jpeg))
                self.server.last_capture = metadata
                if args.get('ocr'):
                    from .ocr import extract
                    metadata['ocr'] = extract(jpeg)
                log('capture_success', session=self.server.session_id, request=request_id,
                    width=metadata.get('image_width'), height=metadata.get('image_height'),
                    bytes=len(jpeg), duration_ms=metadata['duration_ms'])
                historical = self.server.watch.memory.select(metadata,history_count,jpeg) if self.server.watch.watching and not args.get('region') else []
                history = [dict(jpeg=base64.b64encode(f.jpeg).decode(),metadata=dict(f.metadata,timestamp=f.timestamp,
                               seconds_ago=round(time.time()-f.timestamp,2),change_score=f.change_score,current=False)) for f in historical]
                if not self.server.allowed or generation != self.server.access_generation:
                    return self.respond(403,{'error':'Desktop access changed during processing; images discarded.'})
                self.respond(200, dict(metadata=metadata, jpeg=base64.b64encode(jpeg).decode(),history=history))
        except ValueError as exc:
            log('capture_rejected', session=self.server.session_id, reason=str(exc))
            self.respond(400, {'error': str(exc)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            log('client_disconnected', session=self.server.session_id)
        except Exception as exc:
            detail = type(exc).__name__ + ': ' + str(exc)[:240]
            log('capture_failed', session=self.server.session_id, reason=detail)
            self.respond(503, {'error': 'Screen capture failed (' + detail + ').'})


def main():
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.title('Virtual Rocky Screen Vision')
    token = os.environ.pop('ROCKY_SCREEN_TOKEN', None)
    managed = bool(token)
    server = BridgeServer(WindowsCapture(), int(os.environ.get('ROCKY_SCREEN_PORT', PORT)), token)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    tk.Label(root, text='Desktop vision available — on-demand only\nScreenshots may be sent to your model provider.').pack(padx=20, pady=12)
    if not managed:
        tk.Label(root, text='Standalone diagnostics: use Enable Screen Vision in Rocky for normal use.').pack()
    status = tk.StringVar(value='Allow screenshots: yes')
    tk.Label(root, textvariable=status).pack()
    try:
        monitor_count = len(server.backend.monitors())
    except Exception as exc:
        monitor_count = 0
        log('discovery_failed', reason=type(exc).__name__)
    tk.Label(root, text=f'Monitors: {monitor_count}').pack(pady=5)
    def pause():
        server.watch.stop()
        server.allowed = not server.allowed
        server.access_generation += 1
        log('pause_state', session=server.session_id, allowed=server.allowed)
        status.set('Allow screenshots: ' + ('yes' if server.allowed else 'PAUSED'))
    def monitors():
        try:
            messagebox.showinfo('Monitors', '\n'.join(
                f"Monitor {m['id']}: {m['width']}×{m['height']} at {m['x']},{m['y']} — primary: {m['primary']}"
                for m in server.backend.monitors()) or 'No displays detected.')
        except Exception:
            messagebox.showerror('Monitors', 'Monitor discovery failed. Check capture dependencies.')
    def close():
        server.watch.stop()
        server.allowed = False
        server.token = secrets.token_urlsafe(32)
        server.shutdown()
        server.server_close()
        root.destroy()
        log('helper_closed', session=server.session_id)
    tk.Button(root, text='Pause / resume access', command=pause).pack(pady=5)
    tk.Button(root, text='Show monitor list', command=monitors).pack(pady=5)
    tk.Button(root, text='Exit — disable screen access', command=close).pack(pady=10)
    root.protocol('WM_DELETE_WINDOW', close)
    parent_handle = None
    if managed and os.name == 'nt' and os.environ.get('ROCKY_SCREEN_PARENT'):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        parent_handle = kernel.OpenProcess(0x00100000, False, int(os.environ['ROCKY_SCREEN_PARENT']))
        if not parent_handle:
            server.exit_requested.set()
    def refresh():
        parent_exited = bool(parent_handle and kernel.WaitForSingleObject(parent_handle, 0) == 0)
        if server.exit_requested.is_set() or parent_exited:
            close()
            return
        status.set('Status: ' + ('Error: ' + server.watch.error if server.watch.error else 'Connected' if server.authenticated else 'Waiting for Rocky') +
                   '\nScreenshots: ' + ('Allowed' if server.allowed else 'PAUSED') +
                   ('\nWatching ' + str(server.watch.monitor) + ' locally. ' + str(server.watch.memory.status()['frames']) + ' RAM frames.\nNo automatic cloud uploads.' if server.watch.watching else ''))
        root.after(200, refresh)
    root.after(200, refresh)
    if managed:
        print(json.dumps({'type':'screen_ready', 'port':server.server_port,
                          'session_id':server.session_id}), flush=True)
    try:
        root.mainloop()
    finally:
        server.server_close()
        if parent_handle:
            kernel.CloseHandle(parent_handle)


if __name__ == '__main__':
    main()
