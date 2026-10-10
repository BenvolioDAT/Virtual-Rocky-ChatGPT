"""Local UI/console controls for web, memory and camera-session labels."""
import json
import sqlite3
from .web_access import manager as web
from .memory_manager import manager as memory
from .session_people import manager as people
from .capabilities import label_visible_person


def handle(line):
    command,_,arg=line.partition(' ')
    if command not in ('web','memory','people'): return None
    operation,_,value=arg.partition(' ')
    try:
        if command=='web':
            if operation in ('enable','disable'): web.set_enabled(operation=='enable')
            elif operation=='location': web.set_location(value)
            if operation=='sources': return dict(type='source_info',sources=web.sources(),answer=web.last_answer)
            return dict(type='feature_info',title='Web Access',text=web.status()+'\nWeather location: '+str(web.preferences.load().get('default_weather_location') or 'not configured')+'\nWeather attribution: Open-Meteo / GeoNames (https://open-meteo.com/)')
        if command=='people':
            if operation=='clear': people.reset()
            elif operation=='label':
                result,_=label_visible_person(json.loads(value),local=True)
                return dict(type='feature_info',title='Camera Session Label',text=result)
            return dict(type='feature_info',title='Camera Session People',text=json.dumps(people.visible(),ensure_ascii=False,indent=2)+'\nLabels expire when continuity is lost. No biometric recognition.')
        if operation in ('enable','disable'): memory.set_enabled(operation=='enable')
        elif operation=='add':
            args=json.loads(value); result=memory.remember(args['fact'],args.get('subject','user'),local=True,person=args.get('person',False))
            return dict(type='feature_info',title='Memory Saved',text=json.dumps(result,ensure_ascii=False))
        elif operation=='person':
            args=json.loads(value); result=memory.person(args['name'],args.get('aliases',[]),local=True)
            return dict(type='feature_info',title='Person Saved',text=json.dumps(result,ensure_ascii=False))
        elif operation=='people': return dict(type='feature_info',title='Known People',text=json.dumps(memory.list_people(),ensure_ascii=False,indent=2))
        elif operation=='search': return dict(type='feature_info',title='Memory Search',text=json.dumps(memory.recall(value),ensure_ascii=False,indent=2))
        elif operation=='forget': return dict(type='feature_info',title='Forget Memory',text='Deleted.' if memory.forget(int(value),local=True) else 'Memory ID not found.')
        elif operation=='deleteall' and value=='confirmed':
            memory.delete_all(confirmed=True)
            return dict(type='feature_info',title='Memory',text='All textual facts, people and aliases deleted.')
        return dict(type='feature_info',title='Memory',text=memory.status())
    except (ValueError,KeyError,OSError,sqlite3.Error) as exc:
        return dict(type='feature_info',title='Request not completed',text=str(exc))
