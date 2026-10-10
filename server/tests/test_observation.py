import base64
import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    from PIL import Image
except ImportError:
    Image = None
from desktop_vision.memory import VisualMemory, temporal_count
from desktop_vision.watch import ScreenWatch
from desktop_vision.screen_bridge import BridgeServer
from brain.screen import ScreenClient, ScreenVisionManager, vision_source, watch_command
from brain.ui_preferences import PreferenceStore, visible_position, PRESETS

META = {'selection':{'monitor':'primary','region':None}}


class PreferenceTests(unittest.TestCase):
    def test_whitelisted_restore_and_offscreen_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PreferenceStore(Path(directory)/'ui.json')
            store.save(dict(width=480,height=300,x=4000,y=-2000,preset='Large',always_on_top=True,token='NEVER_SAVE',jpeg='NEVER_SAVE'))
            self.assertEqual(store.load()['width'],480)
            self.assertNotIn('NEVER_SAVE',store.path.read_text())
            self.assertEqual(visible_position(4000,-2000,480,300,[(0,0,1920,1080)]),(720,390))
            self.assertEqual(visible_position(-100,20,320,200,[(-1920,0,1920,1080),(0,0,1920,1080)]),(-100,20))
    def test_game_routing_and_watch_commands(self):
        self.assertEqual(vision_source('Can you see me?','screen'),'camera')
        self.assertEqual(vision_source('Why did that happen?','screen'),'screen')
        self.assertEqual(vision_source('What happened in my game?'),'screen')
        self.assertEqual(watch_command('Watch monitor two'),'screen watch 2')
        self.assertEqual(watch_command('Watch my game'),'screen watch primary game')
        self.assertEqual(watch_command('Stop watching my screen'),'screen stopwatch')
        self.assertEqual(watch_command('Stop watching','camera',True),'screen stopwatch')
        self.assertIsNone(watch_command('Stop watching me','screen',True))
        self.assertIsNone(watch_command('What am I holding?'))
    def test_question_selection(self):
        for question in ('What is this?','What game am I playing?','What is happening right now?','What is on monitor two?'):
            self.assertEqual(temporal_count(question),0)
        self.assertEqual(temporal_count('What just happened?'),3)
        self.assertEqual(temporal_count('Why did my health suddenly drop?'),3)
        self.assertEqual(temporal_count('Did that enemy move?'),1)
    def test_unknown_emotion_and_multi_image_parts(self):
        from brain.thinking import RobotBrain, visual_parts
        brain=RobotBrain(); brain.emotion='happy'
        brain._take_emotion_tag('[unknown] Hello',True)
        self.assertEqual(brain.emotion,'neutral')
        parts=visual_parts('Temporal',[{'text':'past','jpeg':b'old'},{'text':'current','jpeg':b'new'}])
        self.assertEqual([p['type'] for p in parts],['text','image_url','text','image_url'])
        brain.history=[{'role':'user','content':parts}]; brain._strip_images()
        self.assertNotIn('data:image',str(brain.history))
    def test_client_never_supplies_history_to_static_question(self):
        client=ScreenClient(); client.local.requested=True
        payload=dict(jpeg=base64.b64encode(b'current').decode(),metadata={},history=[
            dict(jpeg=base64.b64encode(b'past').decode(),metadata={'seconds_ago':2})]*3)
        client.local.question='What is on monitor two?'
        with patch.object(client,'request',return_value=payload):
            self.assertEqual(client.look({'monitor':2})[1],b'current')
        client.local.question='Did that enemy move?'
        with patch.object(client,'request',return_value=payload):
            self.assertEqual(len(client.look({'monitor':2})[1]),2)


@unittest.skipIf(Image is None,'Optional Pillow not installed')
class MemoryTests(unittest.TestCase):
    def test_primary_and_its_number_share_history_but_other_targets_do_not(self):
        memory=VisualMemory()
        meta=dict(META,selected={'id':1,'x':0,'y':0,'width':200,'height':120})
        with Image.new('RGB',(200,120),'black') as image: memory.observe(image,meta)
        numbered=dict(meta,selection={'monitor':1,'region':None})
        self.assertEqual(len(memory.select(numbered,1)),1)
        active=dict(meta,selection={'monitor':'active','region':None})
        self.assertEqual(memory.select(active,1),[])
    def test_duplicate_small_change_threshold_and_expiry(self):
        clock=[0.0]
        memory=VisualMemory(max_frames=3,max_seconds=12,clock=lambda:clock[0])
        with Image.new('RGB',(200,120),'black') as image:
            self.assertTrue(memory.observe(image,META)[0])
            self.assertFalse(memory.observe(image,META)[0])
            image.putpixel((1,1),(255,255,255))
            self.assertFalse(memory.observe(image,META)[0])
        clock[0]=13
        self.assertEqual(memory.status()['frames'],0)
        self.assertIsNone(memory.signature)
    def test_bounded_ring_and_current_duplicate_selection(self):
        clock=[0.0]; memory=VisualMemory(max_frames=3,clock=lambda:clock[0])
        for value in (0,50,100,150,200):
            with Image.new('RGB',(100,60),(value,)*3) as image: memory.observe(image,META)
            clock[0]+=2
        self.assertEqual(len(memory.frames),3)
        self.assertEqual(memory.frames[0].timestamp,4)
        with Image.new('RGB',(100,60),(200,)*3) as image:
            buffer=io.BytesIO(); image.save(buffer,'JPEG')
        selected=memory.select(META,3,buffer.getvalue())
        self.assertEqual(len(selected),2)
        self.assertEqual(memory.select({'selection':{'monitor':2,'region':None}},3),[])
        self.assertEqual(memory.select(META,0),[])
        memory.clear(); self.assertEqual(memory.status()['bytes'],0)


@unittest.skipIf(Image is None,'Optional Pillow not installed')
class WatchTests(unittest.TestCase):
    class Backend:
        value=0
        def monitors(self): return [dict(id=1,primary=True,x=0,y=0,width=200,height=120)]
        def observe(self,selection):
            return Image.new('RGB',(200,120),(self.value,)*3),dict(META)
        def capture(self, selection, region=None, tier='overview'):
            image,meta=self.observe(selection)
            with image:
                buffer=io.BytesIO(); image.save(buffer,'JPEG')
                return buffer.getvalue(),dict(meta,image_width=200,image_height=120)
    def test_local_watch_never_calls_provider_and_clears(self):
        backend=self.Backend(); watch=ScreenWatch(backend,threading.Lock())
        with patch('openai.OpenAI') as model:
            watch.start(interval=.5)
            deadline=time.monotonic()+2
            while watch.samples < 2 and time.monotonic()<deadline: time.sleep(.02)
            self.assertGreaterEqual(watch.samples,2)
            self.assertEqual(watch.memory.status()['frames'],1)
            self.assertGreaterEqual(watch.memory.ignored,1)
            self.assertEqual(watch.status()['automatic_cloud_uploads'],0)
            watch.stop()
            model.assert_not_called()
        self.assertEqual(watch.memory.status()['frames'],0)
    def test_http_watch_history_current_only_pause_stop_and_auth(self):
        backend=self.Backend(); server=BridgeServer(backend,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        client=ScreenClient(server.server_port); client.token=server.token
        manager=ScreenVisionManager(client)
        try:
            self.assertEqual(manager.watch(interval=60),'Watching')
            # Drive deterministic changed samples without waiting for periodic timers.
            time.sleep(.05)
            for value in (60,120,180):
                backend.value=value; server.watch.sample(server.watch.generation)
            static=client.request('/capture',{'monitor':'primary','history_count':0})
            self.assertEqual(static['history'],[])
            temporal=client.request('/capture',{'monitor':'primary','history_count':3})
            self.assertGreaterEqual(len(temporal['history']),2)
            self.assertLessEqual(len(temporal['history']),3)
            client.local.requested=True; client.local.question='What just happened?'
            text,images=client.look({'monitor':'primary'})
            self.assertIsInstance(images,list)
            self.assertIn('Temporal',text)
            self.assertLessEqual(len(images),4)
            self.assertIn('Current fresh',images[-1]['text'])
            manager.pause(True)
            self.assertEqual(server.watch.memory.status()['frames'],0)
            self.assertFalse(server.watch.watching)
            manager.pause(False); manager.watch(interval=60)
            manager.watch(enabled=False)
            self.assertEqual(server.watch.memory.status()['frames'],0)
            client.token='wrong'
            with self.assertRaises(ValueError): client.request('/watch',{'enabled':True})
        finally:
            server.watch.stop(); server.shutdown(); server.server_close(); thread.join()
    def test_watch_failure_and_late_sample_cannot_restore_cleared_ram(self):
        backend=self.Backend(); watch=ScreenWatch(backend,threading.Lock())
        original=backend.observe
        def stop_during_capture(selection):
            result=original(selection); watch.stop(); return result
        watch.watching=True
        with patch.object(backend,'observe',side_effect=stop_during_capture): watch.sample(watch.generation)
        self.assertEqual(watch.memory.status()['frames'],0)
        self.assertFalse(watch.watching)
        with patch.object(backend,'observe',side_effect=RuntimeError('capture failed')):
            watch.start(interval=.5)
            watch.thread.join(2)
        self.assertFalse(watch.watching)
        self.assertIn('capture failed',watch.error)
        self.assertEqual(watch.memory.status()['frames'],0)
        watch.stop(); self.assertIsNone(watch.error)


@unittest.skipIf(Image is None,'Optional Pillow not installed')
class CropTests(unittest.TestCase):
    def test_region_bounds_active_fallback_and_tiers(self):
        from desktop_vision.capture import WindowsCapture
        from types import SimpleNamespace as NS
        backend=WindowsCapture()
        monitors=[dict(id=1,primary=True,x=0,y=0,width=2000,height=1200)]
        class Capture:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def grab(self,rect):
                return NS(size=(rect['width'],rect['height']),rgb=b'\0'*(rect['width']*rect['height']*3))
        with patch.object(backend,'monitors',return_value=monitors),patch('mss.mss',return_value=Capture()),patch('desktop_vision.windows.foreground_window',return_value=None):
            overview,meta=backend.capture('primary')
            self.assertEqual((meta['image_width'],meta['image_height']),(1500,900))
            detail,meta=backend.capture(1,{'x':10,'y':20,'width':80,'height':40},'detail')
            self.assertEqual((meta['selected']['x'],meta['selected']['y']),(10,20))
            self.assertEqual(meta['image_width'],80)
            self.assertLess(len(detail),len(overview))
            with self.assertRaises(ValueError): backend.capture(1,{'x':1990,'y':0,'width':80,'height':40})
            _,meta=backend.capture('active')
            self.assertEqual(meta['active_fallback'],'primary')
        window=dict(handle=7,title='Game',monitor=1,x=20,y=30,width=500,height=300)
        with patch.object(backend,'monitors',return_value=monitors),patch('mss.mss',return_value=Capture()),patch('desktop_vision.windows.foreground_window',return_value=window):
            _,meta=backend.capture('active',{'x':10,'y':10,'width':100,'height':50})
            self.assertEqual(meta['selected']['x'],30)
            self.assertEqual(meta['window']['title'],'Game')
    def test_ocr_disabled_and_missing_binary_are_safe(self):
        from desktop_vision.ocr import extract
        from desktop_vision import settings
        self.assertFalse(extract(b'invalid')['available'])
        with patch.object(settings,'SCREEN_OCR_ENABLED',True),patch('shutil.which',return_value=None):
            self.assertFalse(extract(b'invalid')['available'])
        from types import SimpleNamespace as NS
        with patch.object(settings,'SCREEN_OCR_ENABLED',True),patch('shutil.which',return_value='tesseract.exe'),patch('subprocess.run',return_value=NS(stdout=b'Visible text\n'*500)) as run:
            result=extract(b'in-memory-jpeg')
            self.assertTrue(result['available'])
            self.assertLessEqual(len(result['text']),settings.SCREEN_OCR_MAX_CHARS)
            self.assertEqual(run.call_args.args[0],['tesseract.exe','stdin','stdout'])
            self.assertEqual(run.call_args.kwargs['input'],b'in-memory-jpeg')


if __name__=='__main__': unittest.main()
