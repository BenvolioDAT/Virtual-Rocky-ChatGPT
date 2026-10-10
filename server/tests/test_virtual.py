import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch
import numpy as np
from brain.body import PhysicalBody, VirtualBody
from brain.eyes import Eyes
from brain.webcam import Webcam

class BodyTests(unittest.IsolatedAsyncioTestCase):
    async def test_physical_disconnected(self):
        self.assertFalse(await PhysicalBody(lambda: None).command({'type':'emotion','name':'happy'}))
    async def test_physical_wire_protocol(self):
        socket = AsyncMock()
        self.assertTrue(await PhysicalBody(lambda: socket).command({'type':'emotion','name':'sad'}))
        import json
        self.assertEqual(json.loads(socket.send.call_args.args[0]), {'type':'emotion','name':'sad'})
    async def test_new_emotions_keep_physical_firmware_compatibility(self):
        socket=AsyncMock()
        body=PhysicalBody(lambda:socket)
        await body.command({'type':'emotion','name':'worried'})
        self.assertEqual(__import__('json').loads(socket.send.call_args.args[0])['name'],'sad')
    async def test_virtual_commands_without_robot(self):
        events = []
        body = VirtualBody(events.append)
        self.assertTrue(await body.command({'type':'emotion','name':'thinking'}))
        await body.command({'type':'volume','level':2})
        self.assertEqual(body.volume, 1)
        self.assertEqual(events[0]['name'], 'thinking')
    def test_amplitude_and_audio_blocks(self):
        events, played = [], []
        class Output:
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def write(self, pcm): played.append(pcm)
        pcm = np.full(1600, 8000, dtype='<i2').tobytes()
        VirtualBody(events.append, Output).play_pcm(pcm)
        self.assertEqual(len(b''.join(played)), len(pcm))
        self.assertTrue(any(e.get('level',0)>0 for e in events))
        self.assertEqual(events[-1], {'type':'talking','on':False})
    def test_output_failure_resets_animation(self):
        events = []
        def fail(**kwargs): raise RuntimeError('speaker unavailable')
        with self.assertRaises(RuntimeError): VirtualBody(events.append, fail).play_pcm(b'\0\0')
        self.assertEqual(events[-2]['level'], 0)
        self.assertFalse(events[-1]['on'])
    def test_absent_camera_releases_capture(self):
        class Capture:
            released = False
            def isOpened(self): return False
            def release(self): self.released = True
        capture = Capture()
        webcam = Webcam(Eyes(), capture_factory=lambda index: capture)
        webcam._run()
        self.assertTrue(capture.released)
        self.assertIn('No webcam', webcam.error)
    def test_stale_camera_is_not_sent(self):
        eyes = Eyes(); eyes.push_frame(b'jpeg'); eyes.frame_at = 0
        self.assertIsNone(eyes.latest())
    async def test_wake_phrase_uses_virtual_body(self):
        from brain import main as core
        from brain.ears import strip_wake_word
        events = []
        self.assertEqual(strip_wake_word('Hey Rocky what do you see?')[0], True)
        with patch.object(core, 'body', VirtualBody(events.append)), patch.object(core, 'say', AsyncMock()), patch.object(core, 'tracker', None):
            await core._handle_heard(('hey Rocky', 1, 2, 3))
        self.assertTrue(any(e.get('name')=='surprised' for e in events))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from brain.face_window import FaceWindow, Bridge

class FaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])
    def test_all_expressions_and_render(self):
        bridge = Bridge(); face = FaceWindow(bridge)
        self.assertTrue(face.windowFlags() & Qt.WindowType.FramelessWindowHint)
        face.show()
        from brain import config
        for name in config.EMOTIONS:
            bridge.event.emit({'type':'emotion','name':name})
            self.app.processEvents()
            self.assertEqual(face.emotion, name)
            self.assertFalse(face.grab().isNull())
        face.close()
    def test_presets_persistence_and_local_animation(self):
        from brain.ui_preferences import PreferenceStore, PRESETS
        from brain import config
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            store=PreferenceStore(Path(directory)/'ui.json')
            bridge=Bridge(); face=FaceWindow(bridge,preferences=store)
            for name,size in PRESETS.items():
                face.set_preset(name)
                self.assertEqual((face.width(),face.height()),size)
                self.assertFalse(face.grab().isNull())
            bridge.event.emit({'type':'emotion','name':'not_an_emotion'})
            self.assertEqual(face.emotion,'neutral')
            bridge.event.emit({'type':'screen','text':'Watching'})
            self.assertEqual(face.animation,'watching_screen')
            face.tick(); self.assertEqual(face.emotion,'neutral')
            face.set_preset('Large'); face.move(30,40); face.close()
            restored=FaceWindow(Bridge(),preferences=store)
            self.assertEqual((restored.width(),restored.height()),PRESETS['Large'])
            self.assertEqual(restored.size_preset,'Large')
            restored.close()
    def test_desktop_status_visible_with_or_without_helper(self):
        bridge = Bridge(); face = FaceWindow(bridge)
        self.assertEqual(face.screen_status, 'Disabled')
        for status in ('Connected', 'Paused', 'Offline', 'Disabled'):
            bridge.event.emit({'type':'screen', 'text':status})
            self.app.processEvents()
            self.assertEqual(face.screen_status, status)
            self.assertFalse(face.grab().isNull())
        face.close()

    def test_screen_menu_actions_follow_state(self):
        from PySide6.QtWidgets import QMenu
        commands = []
        face = FaceWindow(Bridge(), commands.append)
        for state in ('Disabled', 'Connected', 'Paused', 'Offline', 'Error'):
            face.screen_status = state
            menu = QMenu(); submenu = face.add_screen_menu(menu)
            actions = {action.text():action for action in submenu.actions()}
            self.assertEqual(actions['Enable Screen Vision'].isEnabled(), state in ('Disabled','Offline','Error'))
            self.assertEqual(actions['Disable Screen Vision'].isEnabled(), state != 'Disabled')
            if state == 'Paused':
                actions['Resume Screen Access'].trigger()
                self.assertEqual(commands[-1], 'screen resume')
        face.close()
    def test_chatgpt_button_login_cancel_and_signed_in_status(self):
        commands = []
        bridge = Bridge(); face = FaceWindow(bridge,commands.append)
        face.show()
        bridge.event.emit({'type':'auth','mode':'chatgpt','signed_in':False,'busy':False})
        self.app.processEvents()
        self.assertTrue(face.signin.isVisible())
        face.signin.click()
        self.assertEqual(commands[-1],'chatgpt login')
        bridge.event.emit({'type':'auth','mode':'chatgpt','signed_in':False,'busy':True})
        face.signin.click()
        self.assertEqual(commands[-1],'chatgpt cancel')
        bridge.event.emit({'type':'auth','mode':'chatgpt','signed_in':True,'busy':False})
        self.assertFalse(face.signin.isVisible())
        face.close()

    def test_talking_and_gaze(self):
        bridge = Bridge(); face = FaceWindow(bridge, always_on_top=True)
        bridge.event.emit({'type':'mouth','level':.5})
        bridge.event.emit({'type':'talking','on':True})
        bridge.event.emit({'type':'gaze','x':.4,'y':-.2})
        self.assertTrue(face.talking)
        self.assertEqual(face.gaze, (.4,-.2))
        self.assertTrue(face.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        face.close()


class ScreenRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_screen_control_queue_runs_without_waiting_for_conversation(self):
        from brain.virtual import Runtime
        from brain.screen import ScreenClient, ScreenVisionManager
        from types import SimpleNamespace as NS
        from unittest.mock import Mock
        from brain import config
        self.assertFalse(config.START_SCREEN_VISION)
        events = []
        runtime = Runtime(events.append, no_mic=True)
        client = ScreenClient()
        manager = ScreenVisionManager(client)
        manager.poll = lambda: client.state
        def enable(): client.state = 'Connected'; return client.state
        manager.enable = Mock(side_effect=enable)
        manager.disable = Mock(side_effect=client.disconnect)
        core = NS(brain=NS(_strip_images=Mock()))
        with patch('brain.screen.screen', client), patch('brain.screen.screen_manager', manager):
            runtime.enqueue('ask hello')
            runtime.enqueue('screen enable')
            task = asyncio.create_task(runtime.screen_loop(core, NS(START_SCREEN_VISION=False)))
            try:
                for _ in range(50):
                    if client.state == 'Connected': break
                    await asyncio.sleep(.02)
                self.assertEqual(client.state, 'Connected')
                client.token = 'temporary'
                runtime.enqueue('screen disable')
                self.assertIsNone(client.token)  # Revoked synchronously from UI.
                for _ in range(50):
                    if manager.disable.called: break
                    await asyncio.sleep(.02)
                manager.disable.assert_called_once()
                core.brain._strip_images.assert_called_once()
                self.assertEqual(runtime.commands.get_nowait(), 'ask hello')
                self.assertTrue(any(e.get('text') == 'Starting' for e in events))
            finally:
                runtime.stop_event.set()
                await task


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_physical_pcm_frames_and_ack(self):
        done = asyncio.Event()
        socket = AsyncMock()
        async def send(payload):
            if isinstance(payload, str) and 'speak_end' in payload: done.set()
        socket.send.side_effect = send
        chunks = iter([b'\x02\x00'*200, None])
        async def next_chunk(): return next(chunks)
        await PhysicalBody(lambda:socket).stream_pcm(b'\x01\x00'*1800, next_chunk, done)
        binary = [call.args[0] for call in socket.send.call_args_list if isinstance(call.args[0], bytes)]
        self.assertEqual(b''.join(frame[1:] for frame in binary), b'\x01\x00'*1800+b'\x02\x00'*200)
        self.assertTrue(all(frame[0]==1 and len(frame)<=3201 for frame in binary))
    def test_fixed_webcam_gaze_does_not_accumulate(self):
        from brain.tracker import DesktopTracker
        positions = []
        tracker = DesktopTracker(Eyes(), lambda x,y:positions.append((x,y)))
        for _ in range(20): tracker._steer((400,100,100,100),640,480,1)
        self.assertEqual(positions[0], positions[-1])
        self.assertGreater(positions[0][0], 0)
        self.assertLess(positions[0][1], 0)
    async def test_reply_camera_emotion_tts_and_mic_muting(self):
        from brain import main as core
        events, audio, seen = [], [], []
        class FakeBrain:
            emotion = 'happy'
            def reply(self, question, jpeg, on_emotion, **kwargs):
                seen.append((question,jpeg)); on_emotion('happy'); yield 'Hello friend.'
        class Output:
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def write(self, pcm):
                self_test.assertTrue(ears.muted.is_set()); audio.append(pcm)
        class Ears:
            muted = __import__('threading').Event()
            talking = False
        self_test, ears = self, Ears()
        eyes = Eyes(); eyes.push_frame(b'fresh-jpeg')
        body = VirtualBody(events.append, Output)
        with patch.object(core,'body',body), patch.object(core,'brain',FakeBrain()), patch.object(core,'ears',ears), patch.object(core,'eyes',eyes), patch.object(core,'robot_socket',None), patch.object(core.mouth,'stream',lambda *args:iter([b'\x00\x20'*1000])):
            self.assertTrue(await core.converse('what do you see'))
        self.assertEqual(seen[0][1], b'fresh-jpeg')
        self.assertTrue(audio)
        self.assertFalse(ears.muted.is_set())
        self.assertTrue(any(e.get('name')=='happy' for e in events))
        self.assertEqual(eyes.last_said, 'Hello friend.')

if __name__ == '__main__': unittest.main()
