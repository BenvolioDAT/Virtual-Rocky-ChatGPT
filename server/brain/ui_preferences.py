"""Non-sensitive window preferences only. No credentials or image storage."""
import json
import os
from pathlib import Path

PRESETS = {'Tiny':(160,100), 'Small':(240,150), 'Normal':(320,200),
           'Large':(480,300), 'Huge':(640,400)}


def visible_position(x, y, width, height, displays):
    if not displays:
        return 0, 0
    if any(min(x+width, dx+dw)-max(x, dx) >= 32 and
           min(y+height, dy+dh)-max(y, dy) >= 32 for dx,dy,dw,dh in displays):
        return x,y
    dx,dy,dw,dh = displays[0]
    return dx+max(0,(dw-width)//2), dy+max(0,(dh-height)//2)


class PreferenceStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'VirtualRocky' / 'ui.json'
    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data,dict): return {}
            return {k:v for k,v in data.items() if k in ('x','y','width','height','always_on_top','preset')}
        except (OSError,ValueError): return {}
    def save(self, data):
        allowed = {k:v for k,v in data.items() if k in ('x','y','width','height','always_on_top','preset')}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(allowed),encoding='utf-8')
        os.replace(temp,self.path)
