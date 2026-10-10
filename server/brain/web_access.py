"""Question-driven live information. No workers, background queries or page archive."""
import copy
import json
import re
import threading
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen
from .ui_preferences import PreferenceStore


def intent(question):
    q=question.lower()
    explicit=bool(re.search(r'\b(search the web|search online|look (?:this|it) up|look up|browse the web)\b',q))
    if not explicit and re.search(r'\b(screen|desktop|webcam|camera|my code|this code|my cpu)\b',q): return None
    if re.search(r'\b(weather|forecast|temperature outside)\b',q): return 'weather'
    changing=r'\b(latest|news|current events|today.s|who won|current (?:ceo|president|company|information|version|price)|what happened today|patch notes|stock price|share price|who is (?:the )?(?:ceo|president|mayor))\b'
    if explicit or re.search(changing,q) or re.search(r'\b(?:recent|new)\b.*\b(?:patches?|updates?|events?|changes|versions?)\b',q): return 'search'
    return None


def weather_location(question):
    match=re.search(r'\b(?:in|for|at)\s+(.+)',question,re.I)
    if not match: return ''
    return re.sub(r'\s+(?:today|tomorrow|right now|this week|for \d+ days).*$', '',match[1],flags=re.I).strip(' .?!')[:120]


def spoken_text(text):
    text=re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)',r'\1',text)
    text=re.sub(r'https?://\S+','',text)
    return re.sub(r'【[^】]*】|cite.*?','',text).strip()


class WeatherClient:
    def __init__(self, fetch=None, clock=time.monotonic):
        self.fetch=fetch or self._fetch; self.clock=clock
        self._lock=threading.RLock(); self._places={}; self._cache={}
    @staticmethod
    def _fetch(url):
        with urlopen(url,timeout=12) as response:
            data=response.read(200001)
            if len(data)>200000: raise ValueError('weather response too large')
            result=json.loads(data)
            if result.get('error'): raise ValueError('weather API rejected the request')
            return result
    def get_weather(self, location, days=3):
        if not isinstance(location,str) or not location.strip(): raise ValueError('Which city should I use for weather?')
        if len(location)>120 or type(days) is not int or not 1<=days<=7: raise ValueError('Use a city and 1 to 7 forecast days.')
        location=location.strip(); key=location.casefold()
        with self._lock:
            if key not in self._places:
                result=self.fetch('https://geocoding-api.open-meteo.com/v1/search?'+urlencode(dict(name=location,count=5,language='en',format='json')))
                places=result.get('results',[])
                if not places: raise ValueError('City not found; please include its region or country.')
                self._places[key]=places[0]
                if len(self._places)>32: self._places.pop(next(iter(self._places)))
            place=self._places[key]; now=self.clock()
            cached=self._cache.get((key,days))
            # Current + forecast travel together: use the shorter five-minute TTL.
            if cached and now-cached[0]<300: return copy.deepcopy(cached[1]) | {'cached':True}
            params=dict(latitude=place['latitude'],longitude=place['longitude'],timezone='auto',temperature_unit='fahrenheit',wind_speed_unit='mph',precipitation_unit='inch',forecast_days=days,
                current='temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,wind_direction_10m',
                daily='temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code')
            data=self.fetch('https://api.open-meteo.com/v1/forecast?'+urlencode(params))
            current=data['current']; daily=data['daily']
            result=dict(location=', '.join(str(place[k]) for k in ('name','admin1','country') if place.get(k)),timezone=data.get('timezone'),observation_time=current['time'],units={'temperature':'F','wind_speed':'mph','precipitation':'inch'},
                current={k:current.get(k) for k in ('temperature_2m','apparent_temperature','relative_humidity_2m','precipitation','wind_speed_10m','wind_direction_10m')},condition=condition(current.get('weather_code')),
                forecast=[dict(date=date,high=daily['temperature_2m_max'][i],low=daily['temperature_2m_min'][i],precipitation_probability=daily['precipitation_probability_max'][i],condition=condition(daily['weather_code'][i])) for i,date in enumerate(daily['time'][:days])],
                source='Open-Meteo (forecast model estimates, not a local sensor)',cached=False)
            self._cache[(key,days)]=(now,result)
            if len(self._cache)>32: self._cache.pop(next(iter(self._cache)))
            return copy.deepcopy(result)


def condition(code):
    if code==0: return 'clear'
    if code in (1,2,3): return 'partly cloudy' if code in (1,2) else 'overcast'
    if code in (45,48): return 'fog'
    if code in (51,53,55,56,57): return 'drizzle'
    if code in (61,63,65,66,67,80,81,82): return 'rain'
    if code in (71,73,75,77,85,86): return 'snow'
    if code in (95,96,99): return 'thunderstorm'
    return 'unknown'


class WebAccess:
    def __init__(self, preferences=None, weather=None):
        self.preferences=preferences or PreferenceStore()
        self.weather=weather or WeatherClient()
        self._lock=threading.RLock(); self._support={}; self.last_sources=[]; self.last_answer=''; self.error=''; self.connection=None
        self.local=threading.local()
    @property
    def enabled(self): return self.preferences.load().get('web_enabled',True) is not False
    def set_enabled(self,on):
        self.preferences.save({'web_enabled':bool(on)})
        if not on:
            with self._lock: self.last_sources=[]; self.last_answer=''
    def set_location(self,location):
        if not isinstance(location,str) or len(location)>120: raise ValueError('Use a city/region of at most 120 characters.')
        self.preferences.save({'default_weather_location':location.strip()})
    def begin_turn(self,question):
        self.local.question=question; self.local.weather_used=False
        if intent(question):
            with self._lock: self.last_sources=[]; self.last_answer=''; self.error=''
    def clear_turn(self): self.local.question=''; self.local.weather_used=False
    def hosted_tools(self,connection):
        with self._lock:
            self.connection=connection
            return [{'type':'web_search'}] if self.enabled and self._support.get(connection)!='unsupported' else []
    def mark(self,connection,state,error=''):
        with self._lock: self.connection=connection; self._support[connection]=state; self.error=error
    def status(self):
        if not self.enabled: return 'Web Access: Disabled'
        with self._lock:
            state=self._support.get(self.connection,'unverified')
            return 'Web Access: '+{'supported':'Enabled (hosted search verified)','unsupported':'Unsupported by current provider/model','error':'Error','unverified':'Enabled (hosted search not yet verified)'}.get(state,state)+('\n'+self.error if self.error else '')
    def unavailable(self): return 'Live web search is unavailable with the current connection. I cannot verify that current information.'
    def collect(self,items,answer=''):
        sources=[]; searched=False
        for item in items:
            if not isinstance(item,dict): item=item.model_dump() if hasattr(item,'model_dump') else vars(item)
            if item.get('type')=='web_search_call':
                searched |= item.get('status')=='completed'
                sources.extend((item.get('action') or {}).get('sources') or [])
            if item.get('type')=='message':
                for part in item.get('content',[]):
                    if not isinstance(part,dict): part=vars(part)
                    for annotation in part.get('annotations',[]):
                        if not isinstance(annotation,dict): annotation=vars(annotation)
                        if annotation.get('type')=='url_citation': sources.append(annotation)
        safe=[]; seen=set()
        for source in sources:
            if not isinstance(source,dict): source=vars(source)
            url=source.get('url',''); parsed=urlsplit(url)
            if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or url in seen: continue
            seen.add(url); safe.append(dict(title=str(source.get('title') or parsed.hostname)[:200],domain=parsed.hostname,url=url[:2000]))
        with self._lock:
            if self.enabled: self.last_sources=safe[:20]; self.last_answer=answer[:6000]
        return searched
    def sources(self):
        with self._lock: return copy.deepcopy(self.last_sources) if self.enabled else []
    def get_weather(self,args):
        if not self.enabled: return 'Web Access is disabled; no weather request was made.',None
        if intent(getattr(self.local,'question',''))!='weather': return 'Weather is available only for an explicit weather question.',None
        if self.local.weather_used: return 'Weather was already supplied for this turn.',None
        self.local.weather_used=True
        location=args.get('location') or self.preferences.load().get('default_weather_location','')
        try:
            result=self.weather.get_weather(location,args.get('days',3))
            if not self.enabled: return 'Web Access was disabled; the pending weather result was discarded.',None
            self.collect([{'type':'message','content':[{'annotations':[dict(type='url_citation',url='https://open-meteo.com/',title='Open-Meteo weather data')]}]}])
            return json.dumps(result,ensure_ascii=False),None
        except ValueError as exc: return str(exc),None
        except Exception: return 'Weather service unavailable; no current weather was obtained. Try again later.',None

manager=WebAccess()
