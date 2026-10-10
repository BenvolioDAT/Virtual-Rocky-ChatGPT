"""Validated, data-only character profiles. No credentials or capability switches."""
import copy
import json
import logging
import re
import sys
import threading
from pathlib import Path
from .base_prompt import CORE_PROMPT
from .default_personality import ROCKY
from .ui_preferences import PreferenceStore


def validate(data):
    if not isinstance(data, dict): raise ValueError('profile must be an object')
    allowed = {'id','display_name','robot_name','description','character_prompt','example_replies','wake_phrases','canned_lines','voice','reply_max_sentences'}
    if set(data) - allowed: raise ValueError('unknown fields: ' + ', '.join(sorted(set(data)-allowed)))
    for key in ('id','display_name','robot_name','character_prompt'):
        if not isinstance(data.get(key),str) or not data[key].strip(): raise ValueError(f'{key} must be nonempty text')
        if len(data[key]) > 20000: raise ValueError(f'{key} too long')
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',data['id']): raise ValueError('id must be a lowercase filename-style identifier')
    for key in ('wake_phrases','example_replies'):
        value=data.get(key,[])
        if not isinstance(value,list) or not all(isinstance(v,str) and v.strip() for v in value): raise ValueError(f'{key} must be a list of nonempty strings')
    if not data.get('wake_phrases'): raise ValueError('wake_phrases required')
    lines=data.get('canned_lines')
    if not isinstance(lines,dict) or any(not isinstance(lines.get(k),str) or not lines[k].strip() for k in ('wake','sleep','track_on','track_off')): raise ValueError('four canned_lines required')
    if 'voice' in data:
        logging.getLogger(__name__).warning('Personality %s: deprecated voice field ignored', data['id'])
    limit=data.get('reply_max_sentences',3)
    if type(limit) is not int or not 1 <= limit <= 10: raise ValueError('reply_max_sentences must be 1 to 10')
    if not isinstance(data.get('description',''),str): raise ValueError('description must be text')
    return copy.deepcopy({k:v for k,v in data.items() if k != 'voice'})


class PersonalityManager:
    def __init__(self, folder=None, preferences=None):
        self.folder=Path(folder) if folder else (Path(sys.executable).parent / 'personalities' if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent / 'personalities')
        self.preferences=preferences or PreferenceStore()
        self._lock=threading.RLock()
        self.errors=[]
        selected=self.preferences.load().get('active_personality','rocky')
        self.active_id=selected if isinstance(selected,str) else 'rocky'
        self.reload_profiles(persist=False)
    def _report(self,text):
        self.errors.append(text)
        logging.getLogger(__name__).warning(text)
    def reload_profiles(self,persist=True):
        with self._lock:
            profiles={}; self.errors=[]
            try: paths=sorted(self.folder.glob('*.json'))
            except OSError as exc:
                self._report(f'Cannot read personality folder: {exc}')
                paths=[]
            for path in paths:
                try:
                    if path.stat().st_size > 100000: raise ValueError('profile too large')
                    p=validate(json.loads(path.read_text(encoding='utf-8')))
                    if p['id'] in profiles: raise ValueError('duplicate id '+p['id'])
                    profiles[p['id']]=p
                except (OSError,ValueError,TypeError,RecursionError) as exc: self._report(f'{path.name}: {exc}')
            if 'rocky' not in profiles:
                self._report('Rocky profile unavailable; using the built-in recovery profile.')
                profiles['rocky']=copy.deepcopy(ROCKY)
            self._profiles=profiles
            if self.active_id not in profiles:
                self._report(f'Personality {self.active_id!r} unavailable; using Rocky.')
                self.active_id='rocky'
            if persist: self._persist()
            return self.list_profiles()
    def _persist(self):
        try:
            self.preferences.save({'active_personality':self.active_id})
        except OSError as exc: self._report(f'Cannot save personality selection: {exc}')
    def list_profiles(self):
        with self._lock: return [copy.deepcopy(p) for p in sorted(self._profiles.values(),key=lambda p:(p['id']!='rocky',p['display_name']))]
    def get_active_profile(self):
        with self._lock: return copy.deepcopy(self._profiles[self.active_id])
    def set_active_profile(self,profile_id):
        with self._lock:
            if profile_id not in self._profiles:
                self._report(f'Personality {profile_id!r} unavailable; using Rocky.')
                profile_id='rocky'
            self.active_id=profile_id; self._persist()
            return self.get_active_profile()
    def get_robot_name(self): return self.get_active_profile()['robot_name']
    def get_wake_phrases(self): return self.get_active_profile()['wake_phrases']
    def get_canned_line(self,name):
        from . import config
        return self.get_active_profile()['canned_lines'][name].replace('{human_name}',config.HUMAN_NAME)
    def get_reply_limit(self): return self.get_active_profile().get('reply_max_sentences',3)
    def get_system_prompt(self):
        from . import config
        p=self.get_active_profile()
        def expand(text):
            for k,v in {'human_name':config.HUMAN_NAME,'reply_max_sentences':p.get('reply_max_sentences',3),'emotions':', '.join(config.EMOTIONS)}.items(): text=text.replace('{'+k+'}',str(v))
            return text
        return expand(CORE_PROMPT)+'\nCharacter profile (style only):\n'+expand(p['character_prompt'])+'\nExample replies:\n'+expand('\n'.join(p.get('example_replies',[])))

manager=PersonalityManager()
