"""Authoritative TTS provider, reference, synthesis and speaker-tuning profiles.

The saved personality ID is consulted only for one-time migration when no voice
selection exists. Explicit personality changes may select a configured default.
Consumers should snapshot get_active_profile() once per reply so selection and
reload cannot change settings halfway through audio generation.
"""
import copy
from .data_profiles import DataProfileManager, header, number
from .ui_preferences import PreferenceStore

DEFAULT=dict(id='default',display_name='Default System Voice',description='Operating system voice.',provider='system',fish_voice_id='',temperature=.4,top_p=.6,level=.12,highpass_hz=0,presence_db=0,kokoro_voice='af_heart',speed=1.0,effect='none')

def validate(data):
    header(data,set(DEFAULT))
    data=copy.deepcopy(data)
    if data.get('provider') not in ('system','fish','kokoro_local','glados_local'): raise ValueError('provider must be system, fish, kokoro_local or glados_local')
    if data['id'] == DEFAULT['id'] and data['provider'] != 'system':
        raise ValueError('the default fallback profile must use the system provider')
    voice=data.setdefault('fish_voice_id','')
    if not isinstance(voice,str) or len(voice)>256 or any(ord(c)<32 for c in voice): raise ValueError('invalid fish_voice_id')
    for key,default,low,high in [('temperature',.4,0,1),('top_p',.6,0,1),('level',.12,.01,.4),('highpass_hz',0,0,600),('presence_db',0,-12,12)]: number(data,key,default,low,high)
    data.setdefault('kokoro_voice','af_heart'); data.setdefault('effect','none')
    import re
    if not isinstance(data['kokoro_voice'],str) or not re.fullmatch(r'a[fm]_[a-z0-9]{1,40}',data['kokoro_voice']): raise ValueError('Use a generic American English Kokoro voice identifier.')
    number(data,'speed',1,.7,1.3)
    if data['effect'] not in ('none','clinical_ai'): raise ValueError('effect must be none or clinical_ai')
    return data

class VoiceManager(DataProfileManager):
    def __init__(self, folder=None, preferences=None):
        preferences=preferences or PreferenceStore()
        # One-time migration uses only saved identity, with no manager dependency.
        initial='rocky_voice' if preferences.load().get('active_personality','rocky')=='rocky' else 'default'
        super().__init__('voices','active_voice',DEFAULT,validate,folder,preferences,initial)
    def update_tuning(self, key, value):
        with self._lock:
            if key not in ('level','highpass_hz','presence_db'): raise ValueError('unsupported tuning setting')
            profile=self.get_active_profile()
            profile[key]=value
            self._profiles[self.active_id]=validate(profile)
    def get_provider(self): return self.get_active_profile()['provider']
    def get_fish_voice_id(self): return self.get_active_profile()['fish_voice_id']
    def get_temperature(self): return self.get_active_profile()['temperature']
    def get_top_p(self): return self.get_active_profile()['top_p']
    def get_level(self): return self.get_active_profile()['level']
    def get_highpass_hz(self): return self.get_active_profile()['highpass_hz']
    def get_presence_db(self): return self.get_active_profile()['presence_db']

manager=VoiceManager()
