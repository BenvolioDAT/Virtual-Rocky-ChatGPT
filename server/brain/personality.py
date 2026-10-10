"""Compatibility facade; attributes always reflect the active profile."""
from . import personality_manager

def system_prompt(virtual=None):
    prompt = personality_manager.manager.get_system_prompt()
    if virtual is True:
        prompt += '\nActual body: virtual desktop companion. Your webcam is fixed and cannot turn; pupils can move.'
    elif virtual is False:
        prompt += '\nActual body: physical desk robot. Head movement is limited by the available tools and firmware.'
    return prompt

def __getattr__(name):
    if name == 'SYSTEM_PROMPT': return system_prompt()
    if name == 'LINES': return {k:personality_manager.manager.get_canned_line(k) for k in ('wake','sleep','track_on','track_off')}
    raise AttributeError(name)
