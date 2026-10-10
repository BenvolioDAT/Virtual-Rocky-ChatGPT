"""Virtual-only colors and stroke width; emotions and animations stay shared."""
import copy
import re
from .data_profiles import DataProfileManager, header, number

CLASSIC=dict(id='classic',display_name='Classic Cyan',description='Original OLED appearance.',background='#050a0c',primary='#b4f9ee',secondary='#618680',line_width=3)

def validate(data):
    header(data,set(CLASSIC))
    data=copy.deepcopy(data)
    for key in ('background','primary','secondary'):
        if not isinstance(data.get(key),str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',data[key]): raise ValueError(key+' must be a #RRGGBB color')
    number(data,'line_width',3,1,8)
    return data

class FaceThemeManager(DataProfileManager):
    def __init__(self, folder=None, preferences=None):
        super().__init__('face_themes','active_face_theme',CLASSIC,validate,folder,preferences)
    list_themes=DataProfileManager.list_profiles
    get_active_theme=DataProfileManager.get_active_profile
    set_active_theme=DataProfileManager.set_active_profile
    reload_themes=DataProfileManager.reload_profiles

manager=FaceThemeManager()
