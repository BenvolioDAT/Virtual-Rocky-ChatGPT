import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch,Mock
import numpy as np
from brain.web_access import WebAccess,WeatherClient,intent,spoken_text
from brain.memory_manager import MemoryManager
from brain.session_people import SessionPeople,introduction
from brain.ui_preferences import PreferenceStore

CURRENT=dict(time='2026-10-09T12:00',temperature_2m=70,apparent_temperature=68,relative_humidity_2m=60,precipitation=.01,weather_code=3,wind_speed_10m=6,wind_direction_10m=180)
DAILY=dict(time=['2026-10-09','2026-10-10','2026-10-11'],temperature_2m_max=[73,75,76],temperature_2m_min=[50,52,54],precipitation_probability_max=[40,30,20],weather_code=[3,2,0])

class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
        self.store=PreferenceStore(self.root/'prefs.json'); self.requests=[]; self.now=0
        def fetch(url):
            self.requests.append(url)
            if 'geocoding' in url: return dict(results=[dict(name='Cleveland',admin1='Tennessee',country='United States',latitude=35.16,longitude=-84.87)])
            return dict(current=copy.deepcopy(CURRENT),daily=copy.deepcopy(DAILY),timezone='America/New_York')
        self.web=WebAccess(self.store,WeatherClient(fetch,lambda:self.now))
        self.memory=MemoryManager(self.root/'private'/'memory.db',self.store)
        self.people=SessionPeople(lambda:self.now)
    def patches(self):
        stack=ExitStack()
        for module,key,value in [('web_access','manager',self.web),('chatgpt_brain','web',self.web),('memory_manager','manager',self.memory),('session_people','manager',self.people),('capabilities','web',self.web),('capabilities','memory',self.memory),('capabilities','people',self.people),('feature_controls','web',self.web),('feature_controls','memory',self.memory),('feature_controls','people',self.people)]: stack.enter_context(patch('brain.'+module+'.'+key,value))
        return stack
    def test_weather_geocoding_units_and_cache(self):
        self.web.set_location('Cleveland, Tennessee'); self.web.begin_turn('What is the weather?')
        result=json.loads(self.web.get_weather({})[0]); self.assertEqual(len(self.requests),2)
        self.assertIn('Cleveland',result['location']); self.assertEqual(result['units']['temperature'],'F')
        self.assertEqual(result['current']['temperature_2m'],70); self.assertEqual(result['forecast'][0]['high'],73)
        self.assertIn('temperature_unit=fahrenheit',self.requests[1]); self.assertIn('wind_speed_unit=mph',self.requests[1])
        self.now=20; self.web.begin_turn('Weather?'); self.assertTrue(json.loads(self.web.get_weather({})[0])['cached']); self.assertEqual(len(self.requests),2)
        self.now=301; self.web.begin_turn('Weather?'); self.web.get_weather({}); self.assertEqual(len(self.requests),3)
    def test_weather_explicit_city_overrides_default(self):
        from brain import capabilities
        self.web.set_location('Cleveland, Tennessee')
        with self.patches(): notes,early=capabilities.begin('What is the weather in Atlanta today?')
        self.assertIsNone(early); self.assertTrue(notes); self.assertIn('name=Atlanta',self.requests[0])
    def test_weather_missing_city_disabled_and_failure(self):
        self.web.begin_turn('Weather?'); self.assertIn('Which city',self.web.get_weather({})[0]); self.assertFalse(self.requests)
        self.web.set_enabled(False); self.web.set_location('Cleveland'); self.assertIn('disabled',self.web.get_weather({})[0]); self.assertFalse(self.requests)
        self.web.set_enabled(True); self.web.weather.fetch=Mock(side_effect=OSError('offline'))
        self.web.begin_turn('Weather?'); self.assertIn('unavailable',self.web.get_weather({})[0])
    def test_weather_unrelated_question_makes_no_http_request(self):
        self.web.begin_turn('What is a capacitor?'); self.assertIn('explicit weather',self.web.get_weather({'location':'Atlanta'})[0]); self.assertFalse(self.requests)
    def test_question_routing_and_no_background_queries(self):
        for q in ('What is a capacitor?','What is 12 times 8?','How does my code look?','What is on my screen?','Look at me','What should I eat tonight?'):
            self.assertIsNone(intent(q))
        for q in ("What's the latest EVE Online news?",'Who won the game tonight?','Search the web for capacitors','What happened today?','Who is the CEO of that company?','Recent EVE Online patches'):
            self.assertEqual(intent(q),'search')
        self.assertEqual(intent('Weather in Atlanta?'),'weather'); self.assertFalse(self.requests)
    def test_web_disabled_and_api_provider_cannot_guess_current_info(self):
        from brain import capabilities
        with self.patches():
            self.web.set_enabled(False); _,early=capabilities.begin('News today',chatgpt=True); self.assertIn('cannot verify',early)
            self.web.set_enabled(True); _,early=capabilities.begin('Latest news',chatgpt=False); self.assertIn('unavailable',early)
        self.assertFalse(self.requests)
    def test_sources_are_bounded_http_links_and_urls_are_not_spoken(self):
        items=[dict(type='web_search_call',status='completed',action={'sources':[{'url':'https://www.ccpgames.com/news','title':'CCP'},{'url':'javascript:evil','title':'bad'}]}),dict(type='message',content=[dict(annotations=[dict(type='url_citation',url='https://www.ccpgames.com/news',title='Duplicate')])])]
        self.assertTrue(self.web.collect(items,'Fresh news.'))
        self.assertEqual(len(self.web.sources()),1); self.assertEqual(self.web.sources()[0]['domain'],'www.ccpgames.com')
        self.assertNotIn('https',spoken_text('Read [CCP](https://www.ccpgames.com/news). https://example.org'))
        self.web.begin_turn('Latest news'); self.assertFalse(self.web.sources())
    def test_hosted_tool_visibility_support_and_toggle(self):
        connection=('chatgpt','acct','model'); self.assertEqual(self.web.hosted_tools(connection),[{'type':'web_search'}])
        self.web.mark(connection,'unsupported'); self.assertFalse(self.web.hosted_tools(connection)); self.assertIn('Unsupported',self.web.status())
        self.assertTrue(self.web.hosted_tools(('chatgpt','acct','different-model')))
        self.web.set_enabled(False); self.assertFalse(self.web.hosted_tools(connection))
    def brain(self,events,requests=None,error=None):
        from brain.chatgpt_brain import ChatGPTBrain
        requests=requests if requests is not None else []
        class Stream:
            def __enter__(self): return iter(events(len(requests)-1) if callable(events) else events)
            def __exit__(self,*args): pass
        class Client:
            def __init__(self,**kw): self.responses=NS(create=self.create)
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def create(self,**kw):
                requests.append(kw)
                if error: raise error
                return Stream()
        auth=NS(selected=lambda:{'key':'acct'},token=lambda key:'test',model=lambda key:'model')
        return ChatGPTBrain(auth,{'look':lambda args:('No camera',None)},Client)
    def test_hosted_search_preserves_namespace_and_citations(self):
        requests=[]
        item=NS(type='web_search_call',status='completed',action={'sources':[{'url':'https://example.org/news','title':'News'}]})
        events=[NS(type='response.output_text.delta',delta='[neutral] Fresh [news](https://example.org/news).'),NS(type='response.output_item.done',item=item),NS(type='response.completed',response=NS(output=[]))]
        with self.patches():
            brain=self.brain(events,requests); spoken=list(brain.reply('Latest EVE Online news'))
        self.assertIn({'type':'web_search'},requests[0]['tools']); self.assertEqual(requests[0]['tools'][0]['type'],'namespace')
        self.assertEqual(requests[0]['tool_choice'],{'type':'web_search'}); self.assertEqual(requests[0]['max_tool_calls'],1)
        self.assertIn('Fresh news.',spoken); self.assertEqual(self.web.sources()[0]['title'],'News')
        self.assertNotIn('web_search_call',json.dumps(brain.history)); self.assertNotIn('https://example.org/news',str(spoken))
    def test_hosted_missing_completion_never_speaks_current_claim(self):
        events=[NS(type='response.output_text.delta',delta='[neutral] A current claim.'),NS(type='response.completed',response=NS(output=[]))]
        with self.patches(): spoken=list(self.brain(events).reply('Latest news'))
        self.assertNotIn('A current claim.',spoken); self.assertTrue(any('unavailable' in line for line in spoken))
    def test_hosted_rejection_is_honest_and_does_not_retry_other_provider(self):
        import openai,httpx
        response=httpx.Response(400,request=httpx.Request('POST','https://api.openai.com/v1/responses'))
        error=openai.BadRequestError('unsupported',response=response,body={'error':{'code':'unsupported_tool'}})
        requests=[]
        with self.patches(): spoken=list(self.brain([],requests,error).reply('Latest news'))
        self.assertEqual(len(requests),1); self.assertIn('unavailable',' '.join(spoken)); self.assertIn('Unsupported',self.web.status())
    def test_static_chatgpt_turn_has_no_hosted_tool(self):
        requests=[]; events=[NS(type='response.output_text.delta',delta='[neutral] A capacitor stores energy.'),NS(type='response.completed')]
        with self.patches(): list(self.brain(events,requests).reply('What is a capacitor?'))
        self.assertFalse(any(t['type']=='web_search' for t in requests[0]['tools']))
    def test_explicit_memory_tool_flow_saves_fact_without_retaining_tool_payload(self):
        from brain import capabilities
        first=[NS(type='response.output_item.done',item=NS(type='function_call',call_id='remember1',name='remember_person_fact',arguments=json.dumps({'person':'John','fact':'likes Factorio'}))),NS(type='response.completed')]
        second=[NS(type='response.output_text.delta',delta='[neutral] I remembered that.'),NS(type='response.completed')]
        requests=[]
        with self.patches():
            brain=self.brain(lambda round:first if round==0 else second,requests)
            brain.actions.update(capabilities.actions())
            spoken=list(brain.reply('Remember my friend John likes Factorio.'))
        self.assertEqual(len(requests),2); self.assertIn('I remembered that.',spoken)
        self.assertIn('Factorio',self.memory.recall('John')[0]['fact'])
        self.assertFalse(any(m['role']=='tool' or m.get('tool_calls') for m in brain.history))
        self.assertNotIn('_private_memory',json.dumps(requests))
    def test_pending_weather_data_is_discarded_after_disable(self):
        self.web.begin_turn('Weather in Atlanta?')
        def weather(*args):
            self.web.set_enabled(False)
            return {'current':CURRENT}
        with patch.object(self.web.weather,'get_weather',side_effect=weather): result,_=self.web.get_weather({'location':'Atlanta'})
        self.assertIn('discarded',result); self.assertFalse(self.web.sources())
    def test_pending_memory_context_is_withheld_after_disable(self):
        from brain.thinking import RobotBrain
        brain=RobotBrain()
        brain.history=[{'role':'user','content':[{'type':'text','text':'question'},{'type':'text','text':'private fact','_capability_context':'memory'}]},{'role':'tool','tool_call_id':'1','content':'private retrieval','_private_memory':True}]
        self.memory.set_enabled(False)
        with self.patches(): outgoing=brain._request_history()
        self.assertNotIn('private fact',json.dumps(outgoing)); self.assertNotIn('private retrieval',json.dumps(outgoing))
        self.assertNotIn('_capability_context',json.dumps(outgoing)); self.assertNotIn('_private_memory',json.dumps(outgoing))
    def test_explicit_probe_is_on_demand_and_reports_verified_support(self):
        from brain.chatgpt_brain import ChatGPTBrain
        requests=[]
        class Client:
            def __init__(self,**kw): self.responses=NS(create=self.create)
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def create(self,**kw):
                requests.append(kw)
                return NS(status='completed',output=[dict(type='web_search_call',status='completed',action={})])
        auth=NS(selected=lambda:{'key':'acct'},model=lambda key:'model',token=lambda key:'test')
        with self.patches():
            brain=ChatGPTBrain(auth,client_factory=Client); self.assertFalse(requests)
            self.assertIn('verified',brain.probe_web())
            self.web.set_enabled(False); brain.probe_web()
        self.assertEqual(len(requests),1)
    def test_no_memory_data_for_math_even_if_fact_mentions_times(self):
        from brain import capabilities
        self.memory.remember('likes the Times newspaper and owns 12 mugs',local=True)
        with self.patches(): notes,early=capabilities.begin('What is 12 times 8?')
        self.assertFalse(notes); self.assertIsNone(early)
    def test_downloader_hash_verification_rejects_changed_asset(self):
        import importlib.util,hashlib
        path=Path(__file__).resolve().parent.parent/'scripts'/'setup_kokoro_voice.py'
        spec=importlib.util.spec_from_file_location('kokoro_setup_test',path); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        asset=self.root/'asset'; asset.write_bytes(b'known data')
        info={'size':10,'sha256':hashlib.sha256(b'known data').hexdigest()}
        self.assertTrue(module.verify(asset,info)); asset.write_bytes(b'changed!!?'); self.assertFalse(module.verify(asset,info))
    def test_weather_context_does_not_persist_in_conversation(self):
        self.web.set_location('Cleveland')
        events=[NS(type='response.output_text.delta',delta='[neutral] It is cloudy.'),NS(type='response.completed')]; requests=[]
        with self.patches():
            brain=self.brain(events,requests); list(brain.reply('What is the weather?'))
        self.assertIn('temperature_2m',json.dumps(requests[0]['input'])); self.assertNotIn('temperature_2m',json.dumps(brain.history))
        self.assertNotIn('_capability_context',json.dumps(requests[0]['input'])); self.assertFalse(self.memory.path.exists())
    def test_memory_initialization_explicit_write_persistence_and_recall(self):
        with self.assertRaises(ValueError): self.memory.remember('likes EVE Online')
        self.memory.begin_turn('Remember I like EVE Online'); saved=self.memory.remember('likes EVE Online')
        restored=MemoryManager(self.memory.path,self.store); self.assertEqual(restored.recall('EVE Online')[0]['id'],saved['id'])
        self.memory.begin_turn('Forget that memory'); self.assertTrue(self.memory.forget(saved['id'])); self.assertFalse(restored.recall('EVE Online'))
    def test_people_aliases_relevant_retrieval_and_ambiguity(self):
        self.memory.person('John Smith',['John','Johnny'],local=True)
        self.memory.remember('likes Factorio','Johnny',local=True,person=True)
        self.memory.remember('likes chess','Sarah',local=True,person=True)
        result=self.memory.recall("What game does John like?")
        self.assertEqual(len(result),1); self.assertEqual(result[0]['subject'],'John Smith'); self.assertIn('Factorio',result[0]['fact'])
        self.assertFalse(self.memory.recall('What is 12 times 8?'))
        with self.assertRaises(ValueError): self.memory.person('Other John',['John'],local=True)
    def test_disabled_memory_has_no_read_or_write_side_effects(self):
        self.memory.set_enabled(False)
        self.assertFalse(self.memory.recall('John')); self.assertFalse(self.memory.list_people())
        with self.assertRaises(ValueError): self.memory.remember('Fact',local=True)
        self.assertFalse(self.memory.path.exists())
    def test_delete_all_removes_facts_people_aliases_even_when_disabled(self):
        self.memory.person('John',['Johnny'],local=True); self.memory.remember('likes Factorio','John',local=True,person=True)
        with self.assertRaises(ValueError): self.memory.delete_all()
        self.memory.set_enabled(False); self.memory.delete_all(True); self.memory.set_enabled(True)
        self.assertFalse(self.memory.list_people()); self.assertFalse(self.memory.recall('John'))
    def test_memory_tools_reject_unapproved_writes_and_do_not_store_web(self):
        self.memory.begin_turn('Latest news')
        result,_=self.memory.tool('remember_fact',{'fact':'news'}); self.assertIn('not completed',result); self.assertFalse(self.memory.path.exists())
    def test_session_single_face_label_and_persistent_text_are_separate(self):
        from brain.capabilities import label_visible_person
        self.people.update([(10,10,20,20)]); self.memory.begin_turn('This is John.')
        with self.patches(): result,_=label_visible_person({'name':'John'})
        self.assertIn('session_only',result); self.assertEqual(self.people.visible()[0]['name'],'John')
        self.memory.remember('likes Factorio','John',local=True,person=True)
        self.people.reset(); self.people.update([(10,10,20,20)])
        self.assertIsNone(self.people.visible()[0]['name']); self.assertIn('Factorio',self.memory.recall('John')[0]['fact'])
        with sqlite3.connect(self.memory.path) as db:
            columns=[row[1] for row in db.execute('PRAGMA table_info(people)')]
        db.close()
        self.assertEqual(columns,['id','name','normalized'])
    def test_multiple_faces_do_not_guess_and_missing_track_loses_label(self):
        self.people.update([(10,10,20,20),(100,10,20,20)])
        with self.assertRaises(ValueError): self.people.label('John')
        self.people.label('John','right'); self.assertEqual(self.people.visible()[1]['name'],'John')
        self.people.update([]); self.people.update([(100,10,20,20)]); self.assertIsNone(self.people.visible()[0]['name'])
        self.people.label('John'); self.now=3; self.assertFalse(self.people.visible())
    def test_ambiguous_box_continuity_drops_labels(self):
        self.people.update([(0,0,40,40)]); self.people.label('John')
        self.people.update([(0,0,40,40),(2,0,40,40)])
        self.assertTrue(all(t['name'] is None for t in self.people.visible()))
    def test_label_requires_explicit_human_introduction(self):
        from brain.capabilities import label_visible_person
        self.people.update([(0,0,20,20)]); self.memory.begin_turn('Who is this?')
        with self.patches(): result,_=label_visible_person({'name':'John'})
        self.assertIn('explicit introduction',result); self.assertFalse(self.memory.path.exists())
        self.assertEqual(introduction("That's Sarah."),'Sarah')
    def test_model_cannot_guess_position_when_user_introduction_is_ambiguous(self):
        from brain.capabilities import label_visible_person
        self.people.update([(0,0,20,20),(60,0,20,20)])
        self.memory.begin_turn('This is John.')
        with self.patches(): result,_=label_visible_person({'name':'John','position':'left'})
        self.assertIn('must specify',result); self.assertTrue(all(t['name'] is None for t in self.people.visible()))
        self.memory.begin_turn('This is John Right.')
        with self.patches(): result,_=label_visible_person({'name':'John Right','position':'right'})
        self.assertIn('must specify',result)
        self.memory.begin_turn('This is John, on the left.')
        with self.patches(): result,_=label_visible_person({'name':'John','position':'left'})
        self.assertIn('session_only',result); self.assertEqual(self.people.visible()[0]['name'],'John')
    def test_glados_default_voice_and_core_rules_preserved(self):
        from brain.personality_manager import PersonalityManager
        from brain.voice_manager import VoiceManager
        from brain.face_theme_manager import FaceThemeManager
        server=Path(__file__).resolve().parent.parent
        personalities=PersonalityManager(server/'personalities',self.store); voices=VoiceManager(server/'voices',self.store); themes=FaceThemeManager(server/'face_themes',self.store)
        personalities._voices=voices
        old_theme=themes.active_id; personalities.set_active_profile('glados')
        from brain import ears
        with patch('brain.personality_manager.manager',personalities): self.assertTrue(ears.strip_wake_word('Hey GLaDOS!')[0])
        self.assertEqual(personalities.get_robot_name(),'GLaDOS'); self.assertIn('hey glados',personalities.get_wake_phrases()); self.assertEqual(voices.active_id,'glados_local'); self.assertEqual(themes.active_id,old_theme)
        self.assertIn('Never automatically identify',personalities.get_system_prompt()); self.assertIn('completed web search',personalities.get_system_prompt())
        voices.set_active_profile('glados_synthetic'); themes.set_active_theme('clinical_ai'); self.assertEqual(voices.get_provider(),'kokoro_local')
    def test_kokoro_profile_validation_and_synthetic_local_pcm(self):
        from brain.voice_manager import DEFAULT,validate
        from brain.kokoro_local import synthesize
        settings=validate(DEFAULT|dict(id='synthetic',provider='kokoro_local',effect='clinical_ai',kokoro_voice='af_heart'))
        for key,value in [('kokoro_voice','../actor'),('speed',2),('effect','shell')]:
            with self.assertRaises(ValueError): validate(settings|{key:value})
        def pipeline(text,**kw): yield ('words','phonemes',np.ones(2400,dtype=np.float32)*.2)
        pcm=synthesize('Test',settings,pipeline); self.assertEqual(len(pcm),3200)
        self.assertTrue(np.all(np.frombuffer(pcm,dtype='<i2')>0))
    def test_missing_kokoro_falls_back_and_voice_effect_chunk_state(self):
        from brain import mouth
        from brain.voice_manager import DEFAULT
        settings=DEFAULT|dict(id='synthetic',provider='kokoro_local',effect='clinical_ai')
        with patch.object(mouth.voice_manager,'get_active_profile',return_value=settings), patch('brain.kokoro_local.synthesize',side_effect=RuntimeError('missing')), patch.object(mouth,'_synthesize_builtin',return_value=b'\x01\x00'*50) as system:
            self.assertTrue(mouth.synthesize('Hello'))
        system.assert_called_once()
        x=np.random.default_rng(1).normal(0,.1,1000).astype(np.float32)
        whole=mouth.VoiceEffect('clinical_ai').process(x); effect=mouth.VoiceEffect('clinical_ai')
        self.assertTrue(np.allclose(whole,np.concatenate([effect.process(x[:300]),effect.process(x[300:])])) )
    def test_memory_and_models_are_git_ignored(self):
        import subprocess
        root=Path(__file__).resolve().parents[2]
        output=subprocess.check_output(['git','check-ignore','server/data/memory.db','server/models/tts/kokoro/kokoro-v1_0.pth'],cwd=root).decode()
        self.assertIn('memory.db',output); self.assertIn('kokoro-v1_0.pth',output)
    def test_feature_controls_and_ui_confirmation(self):
        from brain.feature_controls import handle
        from PySide6.QtWidgets import QApplication,QMenu,QMessageBox
        from brain.face_window import FaceWindow,Bridge
        app=QApplication.instance() or QApplication([])
        with self.patches():
            self.assertIn('Disabled',handle('web disable')['text']); self.assertIn('Disabled',handle('memory disable')['text'])
            handle('memory enable'); handle('memory add '+json.dumps({'fact':'likes EVE'})); self.assertIn('likes EVE',handle('memory search EVE')['text'])
            commands=[]; face=FaceWindow(Bridge(),commands.append); self.addCleanup(face.close)
            web,memory,camera=face.add_feature_menus(QMenu(face))
            self.assertTrue(any(a.text()=='Last Sources…' for a in web.actions()))
            self.assertTrue(any(a.text()=='Label Person…' for a in camera.actions()))
            with patch('brain.face_window.QMessageBox.question',return_value=QMessageBox.StandardButton.No): face.delete_memory_dialog()
            self.assertFalse(commands)
            with patch('brain.face_window.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes): face.delete_memory_dialog()
            self.assertEqual(commands[-1],'memory deleteall confirmed')
