import threading
import unittest
from unittest.mock import patch

from brain.screen import ScreenClient, ScreenVisionManager, wants_screen, vision_source
from desktop_vision.capture import select_monitor
from desktop_vision.screen_bridge import BridgeServer


MONITORS = [dict(id=1, primary=True, x=0, y=0, width=2560, height=1440),
            dict(id=2, primary=False, x=-1920, y=-1080, width=1920, height=1080),
            dict(id=3, primary=False, x=2560, y=500, width=1920, height=1080)]


class Backend:
    def __init__(self): self.captures = []
    def monitors(self): return MONITORS
    def capture(self, selection, region=None, tier='overview'):
        chosen = select_monitor(MONITORS, selection)
        self.captures.append(selection)
        return b'fresh-jpeg', dict(selected=chosen, monitors=MONITORS,selection=dict(monitor=selection,region=region))


class MonitorTests(unittest.TestCase):
    def test_primary_and_number(self):
        self.assertEqual(select_monitor(MONITORS, 'primary'), MONITORS[0])
        self.assertEqual(select_monitor(MONITORS, 2), MONITORS[1])
    def test_all_includes_negative_and_vertical_positions(self):
        self.assertEqual(select_monitor(MONITORS, 'all'),
                         dict(x=-1920, y=-1080, width=6400, height=2660))
    def test_invalid_and_empty(self):
        for selection in (0, 4, True, '2', 'left'):
            with self.assertRaises(ValueError): select_monitor(MONITORS, selection)
        with self.assertRaises(ValueError): select_monitor([], 'all')
    def test_screen_and_camera_routing(self):
        for question in ('What is on monitor two?', 'What is this error?', 'Look at my desktop',
                         'What am I looking at?', 'Where should I click?'):
            self.assertTrue(wants_screen(question))
        for question in ('Look at me', 'What am I holding?', 'What shirt am I wearing?', 'Hello'):
            self.assertFalse(wants_screen(question))
    def test_visual_followups_keep_source_and_explicit_camera_switches(self):
        self.assertEqual(vision_source('Can you see the YouTube video I pulled up?'), 'screen')
        self.assertEqual(vision_source('Can you see it now?', 'screen'), 'screen')
        self.assertEqual(vision_source('Try again', 'screen'), 'screen')
        self.assertEqual(vision_source('What am I holding?', 'screen'), 'camera')
        self.assertEqual(vision_source('Can you see it now?', 'camera'), 'camera')
        self.assertIsNone(vision_source('Hello', 'screen'))


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.server = BridgeServer(self.backend, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = ScreenClient(self.server.server_port)
        self.client.token = self.server.token
        self.client.local.requested = True
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
    def test_discovery_and_status_never_capture(self):
        self.assertEqual(self.client.request('/monitors'), MONITORS)
        self.assertEqual(self.client.status(), 'Connected')
        self.assertEqual(self.backend.captures, [])
    def test_authentication_and_session_rotation(self):
        import secrets
        self.server.token = secrets.token_urlsafe(32)
        self.assertIsNone(self.client.look({'monitor': 2})[1])
        self.assertIsNone(self.client.token)
        self.client.token = 'wrong'
        self.assertEqual(self.client.status(), 'Error')
        self.assertIsNone(self.client.token)
        self.assertEqual(self.backend.captures, [])
    def test_capture_failure_and_timeout_are_graceful(self):
        with patch.object(self.backend, 'capture', side_effect=RuntimeError('capture failure')):
            text, image = self.client.look({'monitor': 2})
        self.assertIsNone(image)
        self.assertIn('failed', text)
        with patch.object(self.client.opener, 'open', side_effect=TimeoutError()):
            text, image = self.client.look({'monitor': 2})
        self.assertIsNone(image)
        self.assertIn('can’t see', text)
    def test_fresh_capture_all_and_specific(self):
        for monitor in (2, 'all', 'primary'):
            text, image = self.client.look({'monitor': monitor})
            self.assertEqual(image, b'fresh-jpeg')
            self.assertIn('Fresh desktop screenshot', text)
        self.assertEqual(self.backend.captures, [2, 'all', 'primary'])
        self.assertFalse(hasattr(self.client, 'image'))
    def test_invalid_paused_and_unrequested(self):
        self.assertIsNone(self.client.look({'monitor': 20})[1])
        self.server.allowed = False
        self.assertEqual(self.client.status(), 'Paused')
        self.assertIn('paused', self.client.look({'monitor': 2})[0])
        self.server.allowed = True
        self.client.local.requested = False
        self.assertIsNone(self.client.look({'monitor': 2})[1])
        self.assertEqual(self.backend.captures, [])
    def test_offline_and_disabled(self):
        self.server.shutdown()
        self.server.server_close()
        self.assertEqual(self.client.status(), 'Offline')
        self.assertIsNone(self.client.look({'monitor': 2})[1])
        self.client.disconnect()
        self.assertEqual(self.client.status(), 'Disabled')
    def test_browser_origin_rejected(self):
        import urllib.request
        import urllib.error
        request = urllib.request.Request(self.client.url + '/monitors',
            headers={'Authorization': 'Bearer ' + self.server.token, 'Origin': 'http://localhost'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.client.opener.open(request, timeout=2)
        self.assertEqual(error.exception.code, 401)
    def test_twenty_fresh_captures_and_same_session_pause_reconnect(self):
        from brain.screen import ScreenVisionManager
        manager = ScreenVisionManager(self.client)
        request_ids = []
        for _ in range(20):
            response = self.client.request('/capture', {'monitor':'primary'})
            request_ids.append(response['metadata']['request_id'])
            self.assertTrue(response['metadata']['success'])
            self.assertIn('timestamp', response['metadata'])
        self.assertEqual(len(set(request_ids)), 20)
        token = self.client.token
        manager.pause(True)
        self.assertIsNone(self.client.look({'monitor':2})[1])
        manager.pause(False)
        self.assertIsNotNone(self.client.look({'monitor':2})[1])
        self.client.disconnect(); self.client.token = token
        self.assertEqual(self.client.status(), 'Connected')
        self.assertIsNotNone(self.client.look({'monitor':'all'})[1])
        self.assertEqual(len(self.backend.captures), 22)
    def test_disconnected_inflight_capture_is_discarded(self):
        started, release = threading.Event(), threading.Event()
        original = self.backend.capture
        def delayed(selection, **kwargs):
            started.set(); release.wait(2)
            return original(selection)
        results = []
        def request():
            self.client.local.requested = True
            results.append(self.client.look({'monitor':2}))
        with patch.object(self.backend, 'capture', delayed):
            worker = threading.Thread(target=request); worker.start()
            self.assertTrue(started.wait(2))
            self.client.disconnect(); release.set(); worker.join(3)
        self.assertIsNone(results[0][1])
        self.assertIn('discarded', results[0][0])
    def test_late_timeout_cannot_change_disabled_state(self):
        def timeout(*args, **kwargs):
            self.client.disconnect()
            raise TimeoutError()
        with patch.object(self.client.opener, 'open', side_effect=timeout):
            text, desktop_frame = self.client.look({'monitor':'primary'})
        self.assertIsNone(desktop_frame)
        self.assertIn('discarded', text)
        self.assertEqual(self.client.state, 'Disabled')
    def test_pause_then_resume_during_capture_still_discards_image(self):
        manager = ScreenVisionManager(self.client)
        original = self.backend.capture
        def during_capture(selection, **kwargs):
            manager.pause(True); manager.pause(False)
            return original(selection)
        with patch.object(self.backend, 'capture', during_capture):
            self.assertIsNone(self.client.look({'monitor':2})[1])


class ManagerTests(unittest.TestCase):
    def test_disabled_does_not_start_anything_or_contact_service(self):
        manager = ScreenVisionManager(ScreenClient())
        with patch('brain.screen.subprocess.Popen') as launch, patch.object(manager.client.opener, 'open') as request:
            self.assertEqual(manager.poll(), 'Disabled')
            manager.disable()
        launch.assert_not_called(); request.assert_not_called()
        self.assertIsNone(manager.client.token)

    def test_automatic_launch_auth_and_shutdown(self):
        import io
        import json
        server = BridgeServer(Backend(), 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        manager = ScreenVisionManager(ScreenClient())
        class Process:
            pid = 123
            returncode = None
            def poll(self): return self.returncode
            def wait(self, timeout=None):
                if not server.exit_requested.wait(timeout): raise __import__('subprocess').TimeoutExpired('helper', timeout)
                self.returncode = 0
                return 0
        def launch(command, **kwargs):
            self.assertNotIn(kwargs['env']['ROCKY_SCREEN_TOKEN'], str(command))
            self.assertEqual(kwargs['env']['ROCKY_SCREEN_PORT'], '0')
            server.token = kwargs['env']['ROCKY_SCREEN_TOKEN']
            process = Process()
            process.stdout = io.StringIO(json.dumps(dict(type='screen_ready',port=server.server_port,session_id=server.session_id))+'\n')
            return process
        try:
            with patch('brain.screen.subprocess.Popen', side_effect=launch) as popen:
                self.assertEqual(manager.enable(), 'Connected')
                token = manager.client.token
                manager.client.local.requested = True
                for _ in range(20): self.assertIsNotNone(manager.client.look({'monitor':'primary'})[1])
                self.assertEqual(manager.client.token, token)
                self.assertEqual(popen.call_count, 1)
                diagnostics = json.dumps(manager.diagnostics())
                self.assertNotIn(token, diagnostics)
                manager.client.disconnect()  # UI revocation precedes asynchronous graceful exit.
                manager.disable()
                self.assertIsNone(manager.process)
                self.assertIsNone(manager.client.token)
                self.assertEqual(manager.client.state, 'Disabled')
                self.assertTrue(server.exit_requested.is_set())
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_launch_failure_and_unresponsive_shutdown(self):
        import subprocess
        from unittest.mock import Mock
        manager = ScreenVisionManager(ScreenClient())
        with patch('brain.screen.subprocess.Popen', side_effect=OSError('launch failed')):
            self.assertEqual(manager.enable(), 'Error')
        self.assertIsNone(manager.client.token)
        process = Mock(stdout=None)
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('helper', 2), 0]
        manager.process = process
        manager.disable()
        process.terminate.assert_called_once()
        self.assertEqual(manager.client.state, 'Disabled')

    def test_crash_never_relaunches_and_clears_credentials(self):
        from unittest.mock import Mock
        manager = ScreenVisionManager(ScreenClient())
        manager.client.token = 'temporary'
        manager.client.state = 'Connected'
        manager.process = Mock(returncode=1)
        manager.process.poll.return_value = 1
        with patch('brain.screen.subprocess.Popen') as launch:
            self.assertEqual(manager.poll(), 'Offline')
            self.assertEqual(manager.poll(), 'Offline')
        launch.assert_not_called()
        self.assertIsNone(manager.client.token)

    def test_reconnect_bounded_to_three_and_success_preserves_session(self):
        from unittest.mock import Mock
        manager = ScreenVisionManager(ScreenClient())
        manager.process = Mock(); manager.process.poll.return_value = None
        manager.client.token = 'temporary'
        def failure(): manager.client.state = 'Offline'; return 'Offline'
        with patch.object(manager.client, 'status', side_effect=failure) as status:
            for _ in range(5): manager.poll()
            self.assertEqual(status.call_count, 3)
            self.assertEqual(manager.client.state, 'Error')
        manager.failed_reconnects = 0
        def success(): manager.client.state = 'Connected'; return 'Connected'
        with patch.object(manager.client, 'status', side_effect=success):
            self.assertEqual(manager.poll(), 'Connected')
        self.assertEqual(manager.client.token, 'temporary')


class HistoryTests(unittest.TestCase):
    def test_repeated_screen_followups_are_authorized_without_webcam(self):
        import base64
        from brain.screen import screen
        from brain.thinking import RobotBrain
        brain = RobotBrain({'look_at_screen': screen.look})
        seen = []
        def conversation(*args):
            seen.append(brain.history[-1]['content'])
            text, desktop_frame = screen.look({'monitor':'primary'})
            self.assertEqual(desktop_frame, b'new-desktop')
            self.assertIn('Fresh desktop', text)
            yield 'I see the desktop.'
        response = dict(jpeg=base64.b64encode(b'new-desktop').decode(), metadata={'success':True})
        with patch.object(screen, 'request', return_value=response) as capture, patch.object(brain, '_converse', conversation):
            for question in ['Can you see the YouTube video I pulled up?'] + ['Can you see it now?']*20:
                list(brain.reply(question, b'wrong-webcam', camera_wanted=True))
            self.assertEqual(capture.call_count, 21)
        self.assertNotIn('wrong-webcam', str(seen))
        self.assertTrue(all(not any(p.get('type') == 'image_url' for p in content) for content in seen))
        self.assertFalse(getattr(screen.local, 'requested', False))
        self.assertNotIn('data:image', str(brain.history))

    def test_chat_completion_desktop_tool_replay(self):
        from types import SimpleNamespace as NS
        from brain.thinking import RobotBrain
        call = NS(index=0, id='screen-1', function=NS(name='look_at_screen', arguments='{"monitor":2}'))
        class Stream:
            def __init__(self, delta): self.delta = delta
            def __iter__(self): return iter([NS(choices=[NS(delta=self.delta)])])
            def close(self): pass
        brain = RobotBrain({'look_at_screen': lambda args: ('Fresh desktop screenshot: monitor 2.', b'fresh')})
        streams = [Stream(NS(tool_calls=[call], content=None)),
                   Stream(NS(tool_calls=[], content='Monitor two shows an error.'))]
        requests = []
        def create_response(**kwargs):
            import copy
            requests.append(copy.deepcopy(kwargs))
            return streams.pop(0)
        with patch.object(brain.client.chat.completions, 'create', side_effect=create_response):
            self.assertEqual(list(brain.reply('What is on monitor two?')), ['Monitor two shows an error.'])
            messages = requests[1]['messages']
            self.assertIn('Fresh desktop screenshot', str(messages))
            self.assertIn('data:image', str(messages))
        self.assertNotIn('data:image', str(brain.history))

    def test_image_removed_after_reply_and_model_error(self):
        import openai
        from brain.thinking import RobotBrain, _image_part
        brain = RobotBrain()
        def conversation(*args):
            brain.history.append({'role': 'user', 'content': [_image_part(b'screen')]})
            yield 'I see the error.'
        with patch.object(brain, '_converse', conversation):
            self.assertEqual(list(brain.reply('screen')), ['I see the error.'])
        self.assertNotIn('data:image', str(brain.history))
        def failing(*args):
            brain.history.append({'role': 'user', 'content': [_image_part(b'screen')]})
            raise openai.APIConnectionError(request=__import__('httpx').Request('POST', 'http://localhost'))
            yield
        with patch.object(brain, '_converse', failing): list(brain.reply('screen'))
        self.assertNotIn('data:image', str(brain.history))


if __name__ == '__main__': unittest.main()
