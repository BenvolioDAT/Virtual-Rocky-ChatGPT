"""Local voice regressions: fake model/archives, never download in tests."""
import asyncio
import io
import json
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock,patch

import numpy as np
from brain import glados_local,mouth
from brain.personality_manager import PersonalityManager,validate as personality_validate
from brain.voice_manager import VoiceManager,DEFAULT,validate
from brain.ui_preferences import PreferenceStore
from scripts import setup_glados_voice as setup

SERVER=Path(__file__).resolve().parents[1]
SETTINGS=validate(json.loads((SERVER/'voices/glados_local.json').read_text()))


class SwitchingTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.store=PreferenceStore(Path(temp.name)/'prefs.json')
        self.voices=VoiceManager(SERVER/'voices',self.store)
        self.people=PersonalityManager(SERVER/'personalities',self.store,voices=self.voices)
    def test_configured_defaults_and_both_directions(self):
        self.assertEqual(self.people.get_active_profile()['default_voice_id'],'rocky_voice')
        self.people.set_active_profile('glados')
        self.assertEqual(self.voices.active_id,'glados_local')
        self.assertEqual(self.voices.get_provider(),'glados_local')
        self.people.set_active_profile('rocky')
        self.assertEqual(self.voices.active_id,'rocky_voice')
    def test_manual_override_survives_same_identity_reload_and_restart(self):
        self.people.set_active_profile('glados'); self.voices.set_active_profile('default')
        self.people.set_active_profile('glados'); self.people.reload_profiles()
        restored=PersonalityManager(SERVER/'personalities',self.store,voices=self.voices)
        self.assertEqual(restored.active_id,'glados'); self.assertEqual(self.voices.active_id,'default')
    def test_character_without_default_keeps_voice(self):
        other=next(p['id'] for p in self.people.list_profiles() if 'default_voice_id' not in p)
        self.people.set_active_profile('glados'); self.people.set_active_profile(other)
        self.assertEqual(self.voices.active_id,'glados_local')
    def test_missing_preferred_profile_warns_without_overwriting(self):
        self.people._profiles['glados']['default_voice_id']='missing_voice'
        before=self.voices.active_id
        with self.assertLogs('brain.personality_manager',level='WARNING'): self.people.set_active_profile('glados')
        self.assertEqual(self.voices.active_id,before)
    def test_invalid_default_identifiers(self):
        profile=self.people.get_active_profile()
        for value in (None,[],False,'../voice','','Upper'):
            with self.subTest(value=value),self.assertRaises(ValueError): personality_validate(profile|{'default_voice_id':value})
    def test_console_and_status_use_central_selection(self):
        from brain import main
        with patch('brain.personality_manager.manager',self.people),patch('brain.voice_manager.manager',self.voices),patch.object(main,'brain',None),patch.object(main,'brain_workers',set()),patch.object(main,'turn_lock',asyncio.Lock()),patch.object(main,'send_to_robot',new=AsyncMock()):
            asyncio.run(main.handle_console_line('personality glados'))
            self.assertIn('Voice: GLaDOS Local',main.companion_status())
            self.assertIn('Voice provider: glados_local',main.personality_status())


class ProviderTests(unittest.TestCase):
    def test_validation_accepts_provider_but_rejects_invalid(self):
        self.assertEqual(validate(SETTINGS)['provider'],'glados_local')
        with self.assertRaises(ValueError): validate(SETTINGS|{'provider':'shell'})
    def fake_api(self): return NS(GenerationConfig=lambda:NS())
    def test_lazy_cache_speed_and_pcm(self):
        model=NS(generate=Mock(return_value=NS(samples=np.ones(2205,dtype=np.float32)*.25,sample_rate=22050)))
        with patch.object(glados_local,'_tts',None),patch.object(glados_local,'load_model',return_value=model) as load,patch.dict('sys.modules',{'sherpa_onnx':self.fake_api()}):
            self.assertEqual(load.call_count,0)
            a=glados_local.synthesize('Original diagnostic.',SETTINGS|{'speed':.95})
            b=glados_local.synthesize('Second diagnostic.',SETTINGS)
            self.assertEqual(load.call_count,1); self.assertEqual(len(a),3200); self.assertEqual(len(b),3200)
            self.assertTrue(np.all(np.frombuffer(a,dtype='<i2')>0))
            self.assertEqual(model.generate.call_args_list[0].args[1].speed,.95)
    def test_failed_generation_discards_cache_for_repair(self):
        bad=NS(generate=Mock(side_effect=RuntimeError('failed')))
        good=NS(generate=Mock(return_value=NS(samples=np.ones(2205)*.1,sample_rate=22050)))
        with patch.object(glados_local,'_tts',None),patch.object(glados_local,'load_model',side_effect=[bad,good]) as load,patch.dict('sys.modules',{'sherpa_onnx':self.fake_api()}):
            with self.assertRaises(RuntimeError): glados_local.synthesize('Test.',SETTINGS)
            self.assertTrue(glados_local.synthesize('Retry.',SETTINGS)); self.assertEqual(load.call_count,2)
    def test_missing_assets_and_dependency_are_actionable(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError,'setup-glados'): glados_local.load_model(Path(folder))
        with patch.object(glados_local,'validate_assets'),patch.dict('sys.modules',{'sherpa_onnx':None}):
            with self.assertRaisesRegex(RuntimeError,'sherpa-onnx'): glados_local.load_model(Path('unused'))
    def test_initialization_uses_local_cpu_files(self):
        api=Mock(); api.OfflineTtsConfig.return_value.validate.return_value=True
        with patch.object(glados_local,'validate_assets'),patch.dict('sys.modules',{'sherpa_onnx':api}):
            glados_local.load_model(Path('local-model'))
        self.assertEqual(api.OfflineTtsModelConfig.call_args.kwargs['provider'],'cpu')
        self.assertIn('en_US-glados.onnx',api.OfflineTtsVitsModelConfig.call_args.kwargs['model'])
    def test_threads_serialize_model_access(self):
        active=0; largest=0; lock=threading.Lock()
        def generate(*args):
            nonlocal active,largest
            with lock: active+=1; largest=max(largest,active)
            __import__('time').sleep(.01)
            with lock: active-=1
            return NS(samples=np.ones(2205)*.1,sample_rate=22050)
        with patch.object(glados_local,'_tts',NS(generate=generate)),patch.dict('sys.modules',{'sherpa_onnx':self.fake_api()}):
            threads=[threading.Thread(target=glados_local.synthesize,args=('Test.',SETTINGS)) for _ in range(3)]
            for t in threads: t.start()
            for t in threads: t.join()
        self.assertEqual(largest,1)
    def test_glados_failure_uses_kokoro_without_changing_selection(self):
        pcm=(np.ones(1600)*4000).astype('<i2').tobytes()
        fallback=validate(DEFAULT|{'id':'glados_synthetic','provider':'kokoro_local'})
        with patch.object(mouth.voice_manager,'get_active_profile',return_value=SETTINGS),patch.object(mouth.voice_manager,'list_profiles',return_value=[fallback]),patch('brain.glados_local.synthesize',side_effect=RuntimeError('missing')),patch('brain.kokoro_local.synthesize',return_value=pcm) as kokoro,patch.object(mouth,'_synthesize_builtin') as system,patch.object(mouth.voice_manager,'set_active_profile') as selection:
            self.assertTrue(mouth.synthesize('Original diagnostic.')); kokoro.assert_called_once(); system.assert_not_called(); selection.assert_not_called()
    def test_both_local_failures_use_system_and_retry_next_utterance(self):
        pcm=(np.ones(1600)*4000).astype('<i2').tobytes()
        with patch.object(mouth.voice_manager,'get_active_profile',return_value=SETTINGS),patch('brain.glados_local.synthesize',side_effect=[RuntimeError('missing'),pcm]) as local,patch('brain.kokoro_local.synthesize',side_effect=RuntimeError('missing')),patch.object(mouth,'_synthesize_builtin',return_value=pcm) as system:
            self.assertTrue(mouth.synthesize('Test.')); self.assertTrue(mouth.synthesize('Retry.'))
            self.assertEqual(local.call_count,2); system.assert_called_once()
    def test_shared_processing_and_debug_save_remain_enabled(self):
        pcm=(np.ones(1600)*4000).astype('<i2').tobytes(); lev=mouth.Leveler(); lev.settings=SETTINGS
        with patch('brain.glados_local.synthesize',return_value=pcm),patch.object(lev,'process',wraps=lev.process) as process,patch.object(mouth.config,'DEBUG_SAVE_TTS',True),patch.object(mouth,'_save_clip') as save:
            output=b''.join(mouth.stream('Original diagnostic.',lev))
            process.assert_called_once_with(pcm); save.assert_called_once_with(output,'Original diagnostic.')
    def test_invalid_audio_rejected(self):
        for samples,rate in (([],22050),([float('nan')],22050),([[.1]],22050),([.1],0)):
            with self.assertRaises(ValueError): mouth.samples_to_pcm16k(samples,rate)


class SetupTests(unittest.TestCase):
    def archive(self,folder,name,kind=tarfile.REGTYPE,size=1):
        path=Path(folder)/'test.tar.bz2'
        with tarfile.open(path,'w:bz2') as tar:
            item=tarfile.TarInfo(name); item.type=kind; item.size=size if kind==tarfile.REGTYPE else 0
            tar.addfile(item,io.BytesIO(b'x'*size) if kind==tarfile.REGTYPE else None)
        return path
    def test_rejects_path_traversal_links_and_unexpected_files(self):
        for name,kind in (('../escape',tarfile.REGTYPE),('/escape',tarfile.REGTYPE),(setup.ROOT+'/../escape',tarfile.REGTYPE),(setup.ROOT+'/C:bad',tarfile.REGTYPE),(setup.ROOT+'/espeak-ng-data/link',tarfile.SYMTYPE),(setup.ROOT+'/tokens.txt',tarfile.LNKTYPE),(setup.ROOT+'/evil.exe',tarfile.REGTYPE),(setup.ROOT+'/espeak-ng-data/NUL',tarfile.REGTYPE)):
            with self.subTest(name=name,kind=kind),tempfile.TemporaryDirectory() as temp:
                archive=self.archive(temp,name,kind)
                with self.assertRaises(ValueError): setup.safe_extract(archive,Path(temp)/'out')
    def test_incomplete_package_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive=self.archive(temp,setup.ROOT+'/tokens.txt')
            with self.assertRaises(RuntimeError): setup.safe_extract(archive,Path(temp)/'out')
    def test_expansion_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            archive=self.archive(temp,setup.ROOT+'/tokens.txt',size=2)
            with patch.object(setup,'MAX_EXPANDED',1),self.assertRaises(ValueError): setup.safe_extract(archive,Path(temp)/'out')
    def test_existing_valid_install_skips_download(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(setup,'validate_assets'),patch.object(setup,'download') as download:
            setup.install(temp); download.assert_not_called()


if __name__=='__main__': unittest.main()
