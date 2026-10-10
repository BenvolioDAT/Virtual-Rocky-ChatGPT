"""Voice selection owns synthesis and tuning, never character identity."""
import copy
from .data_profiles import DataProfileManager, header, number
from .ui_preferences import PreferenceStore

DEFAULT=dict(id='default',display_name='Default System Voice',description='Operating system voice.',provider='system',fish_voice_id='',temperature=.4,top_p=.6,level=.12,highpass_hz=0,presence_db=0)

def validate(data):
    header(data,set(DEFAULT))
    data=copy.deepcopy(data)
    if data.get('provider') not in ('system','fish'): raise ValueError('provider must be system or fish')
    voice=data.setdefault('fish_voice_id','')
    if not isinstance(voice,str) or len(voice)>256 or any(ord(c)<32 for c in voice): raise ValueError('invalid fish_voice_id')
    for key,default,low,high in [('temperature',.4,0,1),('top_p',.6,0,1),('level',.12,.01,.4),('highpass_hz',0,0,600),('presence_db',0,-12,12)]: number(data,key,default,low,high)
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
