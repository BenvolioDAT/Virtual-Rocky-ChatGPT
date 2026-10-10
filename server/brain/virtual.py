"""Desktop entry point: Qt on main thread, reused asyncio brain on a worker."""
import argparse
import asyncio
import os
import queue
import threading
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from .face_window import Bridge, FaceWindow

class Runtime:
    def __init__(self, emit, camera=0, no_mic=False, provider=None):
        self.emit, self.camera, self.no_mic = emit, camera, no_mic
        self.provider = provider
        self.auth = None
        self.auth_task = None
        self.login_cancel = threading.Event()
        self.commands = queue.Queue()
        self.screen_commands = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name='brain')
        self.thread.start()
    def enqueue(self, command):
        if command.startswith('ask '):
            from .screen import watch_command, screen
            from . import main as core
            command = watch_command(command[4:],getattr(core.brain,'_visual_source',None),screen.state == 'Watching') or command
        if command.startswith('ask screenvision '):
            command = command[4:]  # Explicit diagnostics typed in Rocky's question box.
        if command in ('screen disable', 'screen disconnect', 'screenvision disable'):
            from .screen import screen
            screen.disconnect()  # Revoke immediately, including during helper startup.
        target = self.screen_commands if command.startswith(('screen ', 'screenvision ')) else self.commands
        target.put(command)
    def _run(self):
        try: asyncio.run(self.run())
        except Exception as exc:
            print(f'Brain startup failed: {exc}')
            self.emit({'type':'status', 'text':'Setup error — see console'})
    async def run(self):
        from . import main as core, config
        from .body import VirtualBody
        from .webcam import Webcam
        from .tracker import DesktopTracker

        config.MIC_SOURCE = 'mac'  # upstream's name for any PC microphone
        loop = asyncio.get_running_loop()
        core.main_loop = loop
        self.emit({'type':'personality','text':core.personality_status()})
        core.body = VirtualBody(self.emit)
        self.provider = self.provider or os.environ.get('VIRTUAL_LLM_AUTH', 'api' if os.environ.get('LLM_API_KEY') else 'chatgpt')
        if self.provider != 'chatgpt':
            from .web_access import manager as web
            web.mark(('api',None,config.MODEL),'unsupported','Chat Completions has no hosted web-search backend here; direct weather remains available.')
        if self.provider == 'chatgpt':
            from .chatgpt_auth import AuthManager
            from .chatgpt_brain import ChatGPTBrain
            self.auth = AuthManager(config._ENV_FILE.parent / '.rocky-auth')
            core.brain = ChatGPTBrain(self.auth, core.ABILITIES, on_status=lambda text: self.emit({'type':'status','text':text}))
            self.emit_auth()
        else:
            core.brain = core.RobotBrain(core.ABILITIES)
            self.emit({'type':'auth','mode':'api'})
            if not os.environ.get('LLM_API_KEY'):
                print('Set LLM_API_KEY in server/.env for the API-provider option.')
        core.brain.virtual_body = True
        # Serialize voice and typed turns so histories, TTS and mic muting cannot race.
        reply_lock = asyncio.Lock()
        original_converse, original_say = core.converse, core.say
        async def converse(*args, **kwargs):
            async with reply_lock: return await original_converse(*args, **kwargs)
        async def say(*args, **kwargs):
            async with reply_lock: return await original_say(*args, **kwargs)
        core.converse, core.say = converse, say
        tracker = DesktopTracker(core.eyes, lambda x,y: self.emit({'type':'gaze','x':x,'y':y}))
        tracker.enabled = True
        core.tracker = tracker
        tracker.start()
        webcam = Webcam(core.eyes, self.camera) if self.camera is not None else None
        if webcam: webcam.start()
        tasks = [asyncio.create_task(core.voice_loop()), asyncio.create_task(core.doze_loop()),
                 asyncio.create_task(self.screen_loop(core, config))]
        startup = None
        if not self.no_mic:
            startup = asyncio.create_task(core.start_listening())
            tasks.append(startup)
        self.emit({'type':'status', 'text':'Loading speech…' if startup else 'Mic off — right-click'})
        ready_reported = False
        if self.auth and not (self.auth.selected() or {}).get('signed_in'):
            self.emit({'type':'status','text':'Click Continue with ChatGPT'})
        try:
            while not self.stop_event.is_set():
                try: command = self.commands.get_nowait()
                except queue.Empty: command = None
                if startup and startup.done() and not ready_reported:
                    ready_reported = True
                    ready = core.ears is not None and core.ears.has_mac_mic
                    text = f'Say hey {config.ROBOT_NAME}' if ready else 'Mic unavailable — type a question'
                    if self.auth and not (self.auth.selected() or {}).get('signed_in'):
                        text = 'Click Continue with ChatGPT'
                    self.emit({'type':'status','text':text})
                if command:
                    if command == 'listen' and startup and not startup.done():
                        print('Speech models are still loading; wait before toggling the mic.')
                        command = None
                if command:
                    try:
                        if command.startswith(('screen ', 'screenvision ')):
                            self.screen_commands.put(command)
                        elif command.startswith('chatgpt '):
                            await self.auth_command(command[8:], reply_lock, core)
                        elif command.startswith('personality'):
                            async with reply_lock:
                                await core.handle_console_line(command)
                            self.emit({'type':'personality','text':core.personality_status()})
                        elif command == 'track toggle':
                            await core.set_tracking(not tracker.enabled)
                            if not tracker.enabled: self.emit({'type':'gaze','x':0,'y':0})
                        else:
                            await core.handle_console_line(command)
                    except Exception as exc:
                        print(f'Command failed: {exc}')
                        self.emit({'type':'status','text':'Error — see console'})
                listening = core.ears is not None and core.ears.hearing and not core.ears.muted.is_set()
                self.emit({'type':'listening','on':listening})
                await asyncio.sleep(.05)
        finally:
            from .screen import screen_manager
            await asyncio.to_thread(screen_manager.disable)
            self.login_cancel.set()
            if self.auth_task:
                await asyncio.gather(self.auth_task, return_exceptions=True)
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            core.stop_listening()
            tracker.stop()
            if webcam: await asyncio.to_thread(webcam.stop)
            core.converse, core.say = original_converse, original_say
    async def screen_loop(self, core, config):
        from .screen import screen_manager, screen
        if config.START_SCREEN_VISION:
            self.screen_commands.put('screen enable')
        next_poll = 0
        while not self.stop_event.is_set():
            try: command = self.screen_commands.get_nowait()
            except queue.Empty: command = None
            if command:
                action = command.split(' ', 1)[1]
                try:
                    if action == 'enable':
                        self.emit({'type':'screen','text':'Starting'})
                        await asyncio.to_thread(screen_manager.enable)
                    elif action in ('disable', 'disconnect'):
                        # Revoke now, even while a model response is in progress.
                        screen.generation += 1
                        core.brain._strip_images()
                        await asyncio.to_thread(screen_manager.disable)
                    elif action in ('pause', 'resume'):
                        await asyncio.to_thread(screen_manager.pause, action == 'pause')
                        core.brain._strip_images()
                    elif action.startswith('watch '):
                        parts = action.split()
                        monitor = int(parts[1]) if parts[1].isdigit() else parts[1]
                        await asyncio.to_thread(screen_manager.watch,monitor,True,'game' in parts)
                        core.brain._visual_source = 'screen'
                    elif action == 'stopwatch':
                        await asyncio.to_thread(screen_manager.watch,enabled=False)
                        core.brain._strip_images()
                    elif action == 'monitors':
                        await asyncio.to_thread(screen.monitors, {})
                        self.emit({'type':'screen_info','text':__import__('json').dumps(screen.monitor_list, indent=2)})
                    elif action == 'test':
                        result = await asyncio.to_thread(screen_manager.test)
                        print(result)
                        self.emit({'type':'screen_info','text':result})
                    elif action == 'reconnect':
                        screen_manager.failed_reconnects = 0
                        await asyncio.to_thread(screen_manager.poll)
                    elif action == 'status':
                        result = __import__('json').dumps(screen_manager.diagnostics(), indent=2)
                        print(result)
                        self.emit({'type':'screen_info','text':result})
                except Exception as exc:
                    self.emit({'type':'screen_info','text':str(exc)})
                next_poll = 0
            if time.monotonic() >= next_poll:
                state = await asyncio.to_thread(screen_manager.poll)
                self.emit({'type':'screen','text':state})
                next_poll = time.monotonic() + 1
            await asyncio.sleep(.05)
    def emit_auth(self, busy=False):
        if not self.auth: return
        selected = self.auth.selected() or {}
        self.emit({'type':'auth', 'mode':'chatgpt', 'busy':busy,
                   'signed_in':bool(selected.get('signed_in') and selected.get('plan_enabled')),
                   'accounts':self.auth.accounts(), 'models':self.auth.models(),
                   'model':self.auth.model() if selected.get('signed_in') and selected.get('plan_enabled') and self.auth.models() else None})

    async def auth_command(self, command, reply_lock, core):
        if not self.auth: return
        if command == 'cancel':
            self.login_cancel.set()
            return
        if command.startswith('login'):
            if self.auth_task and not self.auth_task.done(): return
            self.login_cancel.clear()
            selected = self.auth.selected()
            key = None if command == 'login new' else selected['key'] if selected else None
            self.auth_task = asyncio.create_task(self.do_sign_in(key, reply_lock, core))
            return
        if self.auth_task and not self.auth_task.done():
            self.emit({'type':'status','text':'Finish or cancel browser sign-in first'})
            return
        try:
            async with reply_lock:
                if command == 'logout':
                    confirmed = await asyncio.to_thread(self.auth.sign_out)
                    core.brain.history.clear()
                    self.emit({'type':'status','text':'Signed out'})
                    if not confirmed:
                        self.emit({'type':'auth_error','text':'Signed out locally. Remote sign-out could not be confirmed; disconnect Virtual Rocky in ChatGPT settings.'})
                elif command.startswith('account '):
                    self.auth.select_account(command[8:])
                    core.brain.history.clear()
                    selected = self.auth.selected()
                    if selected and selected['signed_in'] and selected['plan_enabled']:
                        await asyncio.to_thread(self.auth.models, True)
                elif command.startswith('model '): self.auth.choose_model(command[6:])
                elif command == 'models': await asyncio.to_thread(self.auth.models, True)
                self.emit_auth()
        except Exception as exc:
            from .chatgpt_auth import ChatGPTError
            text = str(exc) if isinstance(exc,ChatGPTError) else 'ChatGPT account update failed. Try again.'
            self.emit({'type':'auth_error','text':text})

    async def do_sign_in(self, key, reply_lock, core):
        from .chatgpt_auth import ChatGPTError
        self.emit_auth(busy=True)
        self.emit({'type':'status','text':'Sign in in your browser'})
        try:
            async with reply_lock:
                enabled = await asyncio.to_thread(self.auth.sign_in, key, self.login_cancel)
                core.brain.history.clear()
                if not enabled:
                    raise ChatGPTError('Signed in, but ChatGPT plan use was not enabled. Sign in again and allow Virtual Rocky to use your plan.')
                await asyncio.to_thread(self.auth.models, True)
            from . import config
            self.emit({'type':'status','text':f'Connected — say hey {config.ROBOT_NAME}'})
        except Exception as exc:
            text = str(exc) if isinstance(exc,ChatGPTError) else 'ChatGPT sign-in failed. Try again.'
            if not self.stop_event.is_set():
                self.emit({'type':'status','text':'Sign-in needs attention'})
                self.emit({'type':'auth_error','text':text})
        finally:
            if not self.stop_event.is_set(): self.emit_auth()

    def stop(self):
        self.stop_event.set()
        self.login_cancel.set()
        from .screen import screen_manager
        screen_manager.disable()
        if self.thread: self.thread.join(timeout=3)

def main():
    parser = argparse.ArgumentParser(description='Virtual Rocky desktop companion')
    parser.add_argument('--no-camera', action='store_true')
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--no-mic', action='store_true')
    parser.add_argument('--always-on-top', action='store_true')
    parser.add_argument('--provider', choices=('chatgpt','api'), help='ChatGPT plan sign-in or existing API-key provider')
    parser.add_argument('--preview', action='store_true', help='Face only: no devices, models or API calls')
    parser.add_argument('--smoke-test', action='store_true', help='Face only; close automatically')
    args = parser.parse_args()
    app = QApplication([])
    bridge = Bridge()
    runtime = None if args.preview or args.smoke_test else Runtime(bridge.event.emit,
        None if args.no_camera else args.camera, args.no_mic, args.provider)
    from .ui_preferences import PreferenceStore
    window = FaceWindow(bridge, runtime.enqueue if runtime else None, args.always_on_top, None if args.preview or args.smoke_test else PreferenceStore())
    window.show()
    if runtime: runtime.start()
    else: window.on_event({'type':'status','text':'Preview — right-click for controls'})
    if args.smoke_test: QTimer.singleShot(1000, app.quit)
    app.exec()
    if runtime: runtime.stop()

if __name__ == '__main__': main()
