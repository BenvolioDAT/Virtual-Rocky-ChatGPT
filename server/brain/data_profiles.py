"""Shared loader for validated presentation data; independent preference keys."""
import copy
import json
import logging
import re
import sys
import threading
from pathlib import Path
from .ui_preferences import PreferenceStore


def header(data, allowed):
    if not isinstance(data, dict): raise ValueError('profile must be an object')
    if set(data)-allowed: raise ValueError('unknown fields: '+', '.join(sorted(set(data)-allowed)))
    if not isinstance(data.get('id'), str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', data['id']): raise ValueError('invalid id')
    for key in ('display_name', 'description'):
        if not isinstance(data.get(key, ''), str) or len(data.get(key, '')) > 2000: raise ValueError('invalid '+key)
    if not data.get('display_name', '').strip(): raise ValueError('display_name required')


def number(data, key, default, low, high):
    value=data.setdefault(key, default)
    if type(value) not in (int,float) or not low <= value <= high: raise ValueError(f'{key} must be between {low} and {high}')


class DataProfileManager:
    def __init__(self, directory, key, fallback, validator, folder=None, preferences=None, initial=None):
        self.folder=Path(folder) if folder is not None else (Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent)/directory
        self.preferences=preferences or PreferenceStore()
        self.key, self.fallback, self.validator=key, fallback, validator
        self._lock=threading.RLock()
        selected=self.preferences.load().get(key, initial or fallback['id'])
        self.active_id=selected if isinstance(selected,str) else fallback['id']
        self.reload_profiles()
    def _report(self, text):
        self.errors.append(text)
        logging.getLogger(__name__).warning(text)
    def reload_profiles(self):
        with self._lock:
            self.errors=[]; profiles={}
            try: paths=sorted(self.folder.glob('*.json'))
            except OSError as exc:
                paths=[]; self._report(str(exc))
            for path in paths:
                try:
                    if path.stat().st_size > 100000: raise ValueError('profile too large')
                    profile=self.validator(json.loads(path.read_text(encoding='utf-8')))
                    if profile['id'] in profiles: raise ValueError('duplicate id')
                    profiles[profile['id']]=profile
                except (OSError,ValueError,TypeError,RecursionError) as exc: self._report(f'{path.name}: {exc}')
            profiles.setdefault(self.fallback['id'], copy.deepcopy(self.fallback))
            self._profiles=profiles
            if self.active_id not in profiles:
                self._report(f'{self.active_id!r} unavailable; using {self.fallback["display_name"]}.')
                self.active_id=self.fallback['id']
            self._persist()
            return self.list_profiles()
    def _persist(self):
        try: self.preferences.save({self.key:self.active_id})
        except OSError as exc: self._report(f'Cannot save selection: {exc}')
    def list_profiles(self):
        with self._lock: return copy.deepcopy(sorted(self._profiles.values(),key=lambda p:(p['id']!=self.fallback['id'],p['display_name'])))
    def get_active_profile(self):
        with self._lock: return copy.deepcopy(self._profiles[self.active_id])
    def set_active_profile(self, profile_id):
        with self._lock:
            if profile_id not in self._profiles:
                self._report(f'{profile_id!r} unavailable; using {self.fallback["display_name"]}.')
                profile_id=self.fallback['id']
            self.active_id=profile_id
            self._persist()
            return self.get_active_profile()
