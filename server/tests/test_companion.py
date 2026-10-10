import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from brain.voice_manager import VoiceManager, DEFAULT, validate as voice_validate
from brain.face_theme_manager import FaceThemeManager, CLASSIC, validate as theme_validate
from brain.personality_manager import PersonalityManager, validate as personality_validate
from brain.default_personality import ROCKY
from brain.ui_preferences import PreferenceStore

class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=PreferenceStore(self.root/'ui.json')
        for name in ('personalities','voices','themes'): (self.root/name).mkdir()
        self.write('personalities',ROCKY)
        gamer=ROCKY|dict(id='gamer',display_name='Gamer Buddy',robot_name='Pixel',wake_phrases=['hey pixel'])
        gamer.pop('default_voice_id',None)
        self.write('personalities',gamer)
        self.write('voices',DEFAULT)
        self.write('voices',DEFAULT|dict(id='rocky_voice',display_name='Rocky Voice',provider='fish',fish_voice_id='reference',temperature=.2,top_p=.8))
        self.write('themes',CLASSIC)
        self.write('themes',CLASSIC|dict(id='purple',display_name='Purple',primary='#cf8cff'))
        self.people=PersonalityManager(self.root/'personalities',self.store)
        self.voices=VoiceManager(self.root/'voices',self.store)
        self.people._voices=self.voices
        self.themes=FaceThemeManager(self.root/'themes',self.store)
    def write(self,folder,data): (self.root/folder/(data['id']+'.json')).write_text(json.dumps(data),encoding='utf-8')
    def patches(self):
        from contextlib import ExitStack
        stack=ExitStack()
        for module,name,value in [('personality_manager','manager',self.people),('voice_manager','manager',self.voices),('face_theme_manager','manager',self.themes),('mouth','voice_manager',self.voices),('face_window','manager',self.people),('face_window','voices',self.voices),('face_window','themes',self.themes)]: stack.enter_context(patch('brain.'+module+'.'+name,value))
        return stack
    def test_migration_and_independent_restart(self):
        self.assertEqual(self.voices.active_id,'rocky_voice')
        self.people.set_active_profile('gamer')
        self.assertEqual(self.voices.active_id,'rocky_voice')
        self.voices.set_active_profile('default'); self.themes.set_active_theme('purple')
        self.assertEqual(self.people.get_robot_name(),'Pixel')
        self.assertEqual(PersonalityManager(self.people.folder,self.store).active_id,'gamer')
        self.assertEqual(VoiceManager(self.voices.folder,self.store).active_id,'default')
        self.assertEqual(FaceThemeManager(self.themes.folder,self.store).active_id,'purple')
        self.people.set_active_profile('rocky')
        self.assertEqual(self.voices.active_id,'rocky_voice'); self.assertEqual(self.themes.active_id,'purple')
    def test_other_identity_migration_and_invalid_saved_values(self):
        self.store.save(dict(active_personality='gamer',active_voice=None,active_face_theme=[]))
        self.assertEqual(VoiceManager(self.voices.folder,self.store).active_id,'default')
        self.assertEqual(FaceThemeManager(self.themes.folder,self.store).active_id,'classic')
        other=PreferenceStore(self.root/'other.json'); other.save({'active_personality':'gamer'})
        self.assertEqual(VoiceManager(self.voices.folder,other).active_id,'default')
    def test_removed_profiles_fall_back_independently(self):
        self.people.set_active_profile('gamer'); self.themes.set_active_theme('purple')
        (self.voices.folder/'rocky_voice.json').unlink(); self.voices.reload_profiles()
        self.assertEqual(self.voices.active_id,'default'); self.assertTrue(self.voices.errors)
        self.assertEqual(self.people.active_id,'gamer'); self.assertEqual(self.themes.active_id,'purple')
        (self.themes.folder/'purple.json').unlink(); self.themes.reload_themes()
        self.assertEqual(self.themes.active_id,'classic'); self.assertEqual(self.people.active_id,'gamer')
    def test_validation_and_recovery(self):
        for key,value in [('provider','shell'),('fish_voice_id',[]),('temperature',float('nan')),('top_p',True),('level',9),('highpass_hz',8000),('presence_db',99),('api_key','secret'),('id','../bad')]:
            with self.subTest(key=key), self.assertRaises(ValueError): voice_validate(DEFAULT|{key:value})
        for key,value in [('primary','red'),('background','#bad'),('line_width',0),('eye_style','executable'),('display_name','')]:
            with self.subTest(key=key), self.assertRaises(ValueError): theme_validate(CLASSIC|{key:value})
        (self.voices.folder/'bad.json').write_text('{')
        (self.themes.folder/'bad.json').write_text('[]')
        self.voices.reload_profiles(); self.themes.reload_themes()
        self.assertTrue(self.voices.errors); self.assertTrue(self.themes.errors)
        legacy=personality_validate(ROCKY|{'voice':{'temperature':'old','api_key':'discard'}})
        self.assertNotIn('voice',legacy)
    def test_reload_updates_active_settings_and_adds_entries(self):
        self.write('voices',self.voices.get_active_profile()|dict(temperature=.9))
        self.voices.reload_profiles(); self.assertEqual(self.voices.get_temperature(),.9)
        self.write('themes',CLASSIC|dict(id='custom',display_name='Custom'))
        self.themes.reload_themes(); self.assertIn('custom',[t['id'] for t in self.themes.list_themes()])
        self.themes.set_active_theme('custom')
        self.write('themes',CLASSIC|dict(id='custom',display_name='Custom',line_width=99))
        self.themes.reload_themes(); self.assertEqual(self.themes.active_id,'classic')
    def test_system_voice_bypasses_fish_and_reply_snapshot(self):
        from brain import mouth
        with self.patches(), patch.dict('os.environ',{'FISH_AUDIO_API_KEY':'test'}), patch.object(mouth,'_fish_stream',return_value=iter([b'\x01\x00'*50])) as fish, patch.object(mouth,'_synthesize_builtin',return_value=b'\x01\x00'*50) as system:
            old=mouth.Leveler()
            self.voices.set_active_profile('default')
            list(mouth.stream('Hello',old)); self.assertEqual(fish.call_args.args[1]['fish_voice_id'],'reference')
            list(mouth.stream('Hello')); system.assert_called_once(); self.assertEqual(fish.call_count,1)
            self.assertFalse(mouth.fish_available())
    def test_missing_credentials_and_failed_fish_use_system(self):
        from brain import mouth
        with self.patches(), patch.dict('os.environ',{},clear=True), patch.object(mouth,'_synthesize_builtin',return_value=b'\x01\x00'*50) as system:
            list(mouth.stream('Hello')); system.assert_called_once()
        with self.patches(), patch.dict('os.environ',{'FISH_AUDIO_API_KEY':'test'}), patch.object(mouth,'_fish_stream',side_effect=OSError('unreachable')), patch.object(mouth,'_synthesize_builtin',return_value=b'\x01\x00'*50) as system:
            list(mouth.stream('Hello')); system.assert_called_once()

    def test_fish_request_reads_new_settings(self):
        from brain import mouth
        captured=[]
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*args): return b''
        def request(req,**kw): captured.append(json.loads(req.data)); return Response()
        with self.patches(), patch.dict('os.environ',{'FISH_AUDIO_API_KEY':'test'}), patch('brain.mouth.urllib.request.urlopen',request):
            list(mouth._fish_stream('Hello'))
            self.voices.update_tuning('level',.22)
            self.assertEqual(mouth.Leveler().level,.22)
            self.write('voices',self.voices.get_active_profile()|dict(fish_voice_id='new',temperature=.7)); self.voices.reload_profiles()
            list(mouth._fish_stream('Hello'))
        self.assertEqual(captured[0]['reference_id'],'reference'); self.assertEqual(captured[1]['reference_id'],'new'); self.assertEqual(captured[1]['temperature'],.7)
    def test_local_commands_status_test_and_folders(self):
        from brain import main
        with self.patches(), patch.object(main,'send_to_robot',new=AsyncMock()) as events, patch.object(main,'say',new=AsyncMock()) as say, patch.object(main,'open_profile_folder') as folder:
            asyncio.run(main.handle_console_line('voice default'))
            asyncio.run(main.handle_console_line('theme purple'))
            asyncio.run(main.handle_console_line('voice test')); say.assert_awaited_once_with('Voice test. Hello, friend.')
            for command,target in [('voice',self.voices),('theme',self.themes),('personality',self.people)]:
                asyncio.run(main.handle_console_line(command+' folder')); folder.assert_called_with(target.folder)
                asyncio.run(main.handle_console_line(command+' list'))
            asyncio.run(main.handle_console_line('companion status'))
            text=events.call_args.args[0]['text']
            self.assertIn('Default System Voice',text); self.assertIn('Purple',text); self.assertIn('Robot name: Rocky',text)
    def test_ui_menus_repaint_and_shared_emotion(self):
        from PySide6.QtWidgets import QApplication,QMenu
        from brain.face_window import FaceWindow,Bridge
        app=QApplication.instance() or QApplication([])
        with self.patches():
            commands=[]; face=FaceWindow(Bridge(),commands.append); self.addCleanup(face.close)
            menu=QMenu(face); face.add_personality_menu(menu); voice,theme=face.add_presentation_menus(menu)
            self.assertEqual([a.text() for a in menu.actions()],['Personality','Voice','Face Theme'])
            self.assertTrue(next(a for a in voice.actions() if a.text()=='Rocky Voice').isChecked())
            next(a for a in theme.actions() if a.text()=='Purple').trigger(); self.assertEqual(commands[-1],'theme purple')
            next(a for a in voice.actions() if a.text()=='Test Voice').trigger(); self.assertEqual(commands[-1],'voice test')
            next(a for a in voice.actions() if a.text()=='Reload Voices').trigger(); self.assertEqual(commands[-1],'voice reload')
            next(a for a in theme.actions() if a.text()=='Open Face Theme Folder').trigger(); self.assertEqual(commands[-1],'theme folder')
            before=face.grab().toImage()
            self.themes.set_active_theme('purple')
            with patch.object(face,'update') as update: face.on_event({'type':'presentation','text':'Purple'}); self.assertTrue(update.called)
            self.assertNotEqual(before,face.grab().toImage())
            face.on_event({'type':'emotion','name':'worried'}); self.assertEqual(face.emotion,'worried')
            self.assertEqual(self.people.active_id,'rocky'); self.assertEqual(self.voices.active_id,'rocky_voice')
    def test_physical_theme_events_are_ignored(self):
        from brain.body import PhysicalBody
        socket=type('Socket',(),{'send':AsyncMock()})()
        body=PhysicalBody(lambda:socket)
        asyncio.run(body.command({'type':'presentation','text':'Purple'})); socket.send.assert_not_awaited()
        asyncio.run(body.command({'type':'emotion','name':'happy'})); socket.send.assert_awaited_once()
    def test_builtins_have_no_secrets_or_personality_voice(self):
        server=Path(__file__).resolve().parent.parent
        for path in (server/'personalities').glob('*.json'): self.assertNotIn('voice',json.loads(path.read_text(encoding='utf-8')))
        for path in (server/'voices').glob('*.json'):
            data=json.loads(path.read_text(encoding='utf-8')); voice_validate(data)
            self.assertNotIn('API_KEY',path.read_text(encoding='utf-8'))

    def test_saved_voice_wins_over_personality_migration(self):
        self.store.save({'active_personality':'gamer','active_voice':'rocky_voice'})
        restored=VoiceManager(self.voices.folder,self.store)
        self.assertEqual(restored.active_id,'rocky_voice')
        self.store.save({'active_personality':'rocky','active_voice':'default'})
        self.assertEqual(VoiceManager(self.voices.folder,self.store).active_id,'default')

    def test_duplicate_voice_and_invalid_active_reload(self):
        duplicate=self.voices.get_active_profile() | dict(fish_voice_id='duplicate')
        (self.voices.folder/'z_duplicate.json').write_text(json.dumps(duplicate),encoding='utf-8')
        with self.assertLogs('brain.data_profiles',level='WARNING') as logs:
            self.voices.reload_profiles()
        self.assertTrue(any('z_duplicate.json: duplicate id' in text for text in logs.output))
        self.assertEqual(self.voices.get_fish_voice_id(),'reference')
        (self.voices.folder/'z_duplicate.json').unlink()
        self.write('voices',self.voices.get_active_profile() | dict(level=-1))
        self.voices.reload_profiles()
        self.assertEqual(self.voices.get_provider(),'system')
        self.assertEqual(self.store.load()['active_voice'],'default')
        self.assertEqual(self.people.active_id,'rocky')

    def test_system_fallback_survives_missing_or_overridden_default(self):
        self.write('voices',DEFAULT | dict(provider='fish',fish_voice_id='reference'))
        self.voices.set_active_profile('default')
        self.voices.reload_profiles()
        self.assertEqual(self.voices.get_provider(),'system')
        self.assertTrue(any('fallback profile must use the system provider' in error for error in self.voices.errors))
        (self.voices.folder/'default.json').unlink()
        self.voices.reload_profiles()
        self.assertEqual(self.voices.get_active_profile(),DEFAULT)

    def test_legacy_personality_cannot_supply_runtime_voice(self):
        from brain import mouth
        legacy=ROCKY | dict(id='gamer',display_name='Gamer Buddy',robot_name='Pixel',voice=dict(fish_voice_id='ignored',temperature=0,top_p=0))
        self.write('personalities',legacy)
        self.people.reload_profiles()
        self.people.set_active_profile('gamer')
        with self.patches():
            settings=mouth.Leveler().settings
        self.assertEqual(settings['fish_voice_id'],'reference')
        self.assertEqual((settings['temperature'],settings['top_p']),(.2,.8))
        self.assertNotIn('voice',self.people.get_active_profile())

    def test_console_and_tts_do_not_read_old_config_aliases(self):
        from brain import main,config,mouth
        aliases=('TTS_VOICE_ID','TTS_TEMPERATURE','TTS_TOP_P','TTS_LEVEL','TTS_HIGHPASS_HZ','TTS_PRESENCE_DB')
        for key in aliases: self.assertFalse(hasattr(config,key),key)
        with self.patches(), patch.object(config,'TTS_LEVEL',99,create=True), patch.object(config,'TTS_VOICE_ID','ignored',create=True):
            asyncio.run(main._console_command('voice',{'key':'TTS_LEVEL','value':.22}))
            self.assertEqual(main.console_state()['voice']['TTS_LEVEL'],.22)
            settings=mouth.Leveler().settings
            self.assertEqual(settings['level'],.22)
            self.assertEqual(settings['fish_voice_id'],'reference')
            self.assertEqual(config.TTS_LEVEL,99)

    def test_voice_commands_preserve_conversation_screen_and_camera(self):
        from brain import main
        from brain.screen import screen,screen_manager
        from types import SimpleNamespace
        from unittest.mock import Mock
        brain=SimpleNamespace(history=[{'role':'assistant','content':'remember'}],_visual_source='screen',clear_conversation=Mock())
        camera=object(); tracker=object()
        previous=(copy.deepcopy(brain.history),screen.state,copy.deepcopy(screen.watch_info),main.eyes.last_heard,main.eyes.last_said)
        with self.patches(), patch.object(main,'brain',brain), patch.object(main,'tracker',tracker), patch.object(main.eyes,'latest',return_value=camera), patch.object(main,'send_to_robot',new=AsyncMock()), patch.object(screen,'request',side_effect=AssertionError('screen state changed')) as screen_request, patch.object(screen,'disconnect') as disconnect, patch.object(screen_manager,'disable') as disable:
            for command in ('voice default','voice reload','voice rocky_voice'):
                asyncio.run(main.handle_console_line(command))
            brain.clear_conversation.assert_not_called()
            self.assertEqual(brain.history,previous[0]); self.assertEqual(brain._visual_source,'screen')
            self.assertEqual(screen.state,previous[1]); self.assertEqual(screen.watch_info,previous[2])
            screen_request.assert_not_called(); disconnect.assert_not_called(); disable.assert_not_called()
            self.assertEqual((main.eyes.last_heard,main.eyes.last_said),previous[3:])
            self.assertIs(main.eyes.latest(),camera); self.assertIs(main.tracker,tracker)

    def test_voice_test_runs_tts_without_brain_or_history_changes(self):
        from brain import main,mouth
        from types import SimpleNamespace
        from unittest.mock import Mock
        brain=SimpleNamespace(history=[{'role':'assistant','content':'remember'}],reply=Mock(side_effect=AssertionError('LLM called')))
        captured=[]
        async def consume(reply,interruptible=True):
            while await reply._next() is not None: pass
            return True
        def system(text): captured.append(text); return b'\x01\x00'*50
        self.voices.set_active_profile('default'); self.voices.update_tuning('highpass_hz',300)
        with self.patches(), patch.object(main,'brain',brain), patch.object(main,'turn_lock',asyncio.Lock()), patch.object(main.SpokenReply,'play',consume), patch.object(mouth,'_synthesize_builtin',side_effect=system), patch.object(mouth,'_fish_stream',side_effect=AssertionError('Fish called')), patch.object(mouth.Equalizer,'process',autospec=True,side_effect=lambda eq,x:x) as eq:
            asyncio.run(main.handle_console_line('voice test'))
        self.assertEqual(captured,['Voice test. Hello, friend.'])
        brain.reply.assert_not_called()
        self.assertEqual(brain.history,[{'role':'assistant','content':'remember'}])
        self.assertEqual(len(eq.call_args.args[0].stages),2)

    def test_missing_fish_configuration_reports_reason_without_changing_voice(self):
        from brain import mouth
        for reference,key,reason in [('reference','','FISH_AUDIO_API_KEY'),('','present','a Fish reference ID')]:
            profile=self.voices.get_active_profile() | dict(fish_voice_id=reference)
            with self.patches(), patch.object(self.voices,'get_active_profile',return_value=profile), patch.dict('os.environ',{'FISH_AUDIO_API_KEY':key}), patch.object(mouth,'_synthesize_builtin',return_value=b'\x01\x00'*50), self.assertLogs('brain.mouth',level='WARNING') as logs:
                self.assertTrue(mouth.synthesize('Hello'))
            self.assertIn(reason,logs.output[0]); self.assertIn('selected voice remains unchanged',logs.output[0])
            self.assertEqual(self.voices.active_id,'rocky_voice')

    def test_empty_fish_response_falls_back_instead_of_silent_audio(self):
        from brain import mouth
        with self.patches(), patch.dict('os.environ',{'FISH_AUDIO_API_KEY':'test'}), patch.object(mouth,'_fish_stream',return_value=iter([])), patch.object(mouth,'_synthesize_builtin',return_value=b'\x01\x00'*50) as system:
            self.assertTrue(mouth.synthesize('Hello'))
        system.assert_called_once(); self.assertEqual(self.voices.active_id,'rocky_voice')

    def test_concurrent_switches_produce_coherent_voice_snapshots(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        first=self.voices.get_active_profile()
        second=first | dict(id='alternate',display_name='Alternate',fish_voice_id='alternate',temperature=.7,top_p=.3,level=.25,highpass_hz=300,presence_db=6)
        self.write('voices',second); self.voices.reload_profiles()
        fields=('id','fish_voice_id','temperature','top_p','level','highpass_hz','presence_db')
        expected={tuple(p[field] for field in fields) for p in (first,second)}
        barrier=threading.Barrier(2)
        def switch():
            barrier.wait(timeout=5)
            for i in range(100): self.voices.set_active_profile('alternate' if i%2 else 'rocky_voice')
        def read():
            barrier.wait(timeout=5)
            for i in range(1000):
                snapshot=self.voices.get_active_profile()
                self.assertIn(tuple(snapshot[field] for field in fields),expected)
                snapshot['fish_voice_id']='mutated copy'
        with ThreadPoolExecutor(max_workers=2) as pool:
            workers=[pool.submit(switch),pool.submit(read)]
            for worker in workers: worker.result(timeout=15)
