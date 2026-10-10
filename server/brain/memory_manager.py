"""Explicit local textual facts. No images, embeddings or conversation archive."""
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from .ui_preferences import PreferenceStore

STOP=set('the a an is are was were what who how do does did my your me i you about remember please that this it and of in to for with likes like favorite times plus minus divided multiplied equals calculate compute square'.split())

def tokens(text): return [t for t in re.findall(r'[\w]+',text.casefold()) if len(t)>1 and not t.isdecimal() and t not in STOP][:20]

def text(value,maximum=500):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum or any(ord(c)<32 for c in value): raise ValueError('Use nonempty plain text within the length limit.')
    return value.strip()


class MemoryManager:
    def __init__(self,path=None,preferences=None):
        self.path=Path(path) if path else Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'VirtualRocky'/'memory.db'
        self.preferences=preferences or PreferenceStore(); self._lock=threading.RLock(); self.local=threading.local()
    @property
    def enabled(self): return self.preferences.load().get('memory_enabled',True) is not False
    def set_enabled(self,on):
        with self._lock: self.preferences.save({'memory_enabled':bool(on)})
    def begin_turn(self,question): self.local.question=question; self.local.relevant=False
    def clear_turn(self): self.local.question=''; self.local.relevant=False
    def _allowed(self,action,local=False):
        if not self.enabled: raise ValueError('Memory is disabled; no retrieval or writes were performed.')
        q=getattr(self.local,'question','')
        pattern=r'\b(?:remember|save (?:this|that)|memorize)\b' if action=='write' else r'\b(?:forget|delete|remove).*(?:memory|fact|remembered)|\bforget\b'
        if not local and not re.search(pattern,q,re.I): raise ValueError('An explicit user memory request is required.')
    @contextmanager
    def _db(self,enabled_check=True):
        if enabled_check and not self.enabled: raise ValueError('Memory is disabled.')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=5)
        db.execute('PRAGMA secure_delete=ON')
        db.executescript('''CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY,name TEXT NOT NULL, normalized TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS aliases(alias TEXT PRIMARY KEY,person_id INTEGER NOT NULL REFERENCES people(id));
        CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY,subject TEXT NOT NULL,fact TEXT NOT NULL,created REAL NOT NULL,UNIQUE(subject,fact));''')
        try:
            with db: yield db
        finally:
            db.close()
    def _person(self,db,name,aliases=(),create=False):
        name=text(name,100)
        row=db.execute('SELECT p.id,p.name FROM people p LEFT JOIN aliases a ON a.person_id=p.id WHERE p.normalized=? OR a.alias=?',(name.casefold(),name.casefold())).fetchone()
        if not row and create:
            cursor=db.execute('INSERT INTO people(name,normalized) VALUES (?,?)',(name,name.casefold())); row=(cursor.lastrowid,name)
        if row and create:
            for alias in aliases:
                alias=text(alias,100).casefold()
                conflict=db.execute('SELECT person_id FROM aliases WHERE alias=?',(alias,)).fetchone()
                named=db.execute('SELECT id FROM people WHERE normalized=?',(alias,)).fetchone()
                if (conflict and conflict[0]!=row[0]) or (named and named[0]!=row[0]): raise ValueError('Alias already belongs to someone else; use their full name.')
                db.execute('INSERT OR IGNORE INTO aliases(alias,person_id) VALUES (?,?)',(alias,row[0]))
        return row
    def person(self,name,aliases=(),local=False):
        if not isinstance(aliases,list) and not isinstance(aliases,tuple): raise ValueError('Aliases must be a list.')
        if len(aliases)>10: raise ValueError('At most ten aliases.')
        if not local: self._allowed('write')
        elif not self.enabled: raise ValueError('Memory is disabled.')
        with self._lock,self._db() as db:
            row=self._person(db,name,aliases,True)
            return dict(id=row[0],name=row[1])
    def remember(self,fact,subject='user',local=False,person=False):
        self._allowed('write',local)
        fact=text(fact); subject=text(subject,100)
        with self._lock,self._db() as db:
            if person:
                row=self._person(db,subject,create=True); subject=row[1]
            db.execute('INSERT OR IGNORE INTO facts(subject,fact,created) VALUES (?,?,?)',(subject,fact,time.time()))
            return dict(id=db.execute('SELECT id FROM facts WHERE subject=? AND fact=?',(subject,fact)).fetchone()[0],subject=subject,fact=fact)
    def recall(self,query,limit=5):
        if not self.enabled: return []
        query=text(query,200); words=tokens(query)
        if not words: return []
        limit=min(8,max(1,int(limit)))
        with self._lock,self._db() as db:
            people=db.execute('SELECT name,normalized FROM people UNION SELECT p.name,a.alias FROM people p JOIN aliases a ON a.person_id=p.id').fetchall()
            names={name for name,alias in people if re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',query.casefold())}
            if names:
                rows=db.execute('SELECT id,subject,fact FROM facts WHERE subject IN ('+','.join('?' for _ in names)+') ORDER BY id DESC LIMIT ?',(*names,limit)).fetchall()
            else:
                clause=' OR '.join('(lower(subject) LIKE ? OR lower(fact) LIKE ?)' for _ in words)
                args=[v for word in words for v in ('%'+word+'%','%'+word+'%')]
                rows=db.execute('SELECT id,subject,fact FROM facts WHERE '+clause+' ORDER BY id DESC LIMIT ?',(*args,limit)).fetchall()
            return [dict(id=row[0],subject=row[1],fact=row[2]) for row in rows]
    def list_people(self):
        if not self.enabled: return []
        with self._lock,self._db() as db:
            return [dict(id=id,name=name,aliases=[a[0] for a in db.execute('SELECT alias FROM aliases WHERE person_id=?',(id,))]) for id,name in db.execute('SELECT id,name FROM people ORDER BY name LIMIT 50')]
    def forget(self,memory_id,local=False):
        self._allowed('forget',local)
        if type(memory_id) is not int or memory_id<1: raise ValueError('Use a positive memory ID.')
        with self._lock,self._db() as db: return db.execute('DELETE FROM facts WHERE id=?',(memory_id,)).rowcount>0
    def delete_all(self,confirmed=False):
        if not confirmed: raise ValueError('Local confirmation is required to delete all memory.')
        with self._lock,self._db(enabled_check=False) as db:
            db.executescript('DELETE FROM facts; DELETE FROM aliases; DELETE FROM people;')
        with self._lock,self._db(enabled_check=False) as db: db.execute('VACUUM')
    def status(self):
        return 'Memory: '+('Enabled' if self.enabled else 'Disabled')+'\nLocal database: '+str(self.path)+'\nOnly relevant retrieved text is shared with the selected model. No face identity data is stored.'
    def tool(self,name,args):
        try:
            if name=='remember_fact': result=self.remember(args.get('fact'),args.get('subject','user'))
            elif name=='remember_person_fact': result=self.remember(args.get('fact'),args.get('person'),person=True)
            elif name=='recall_memory': result=self.recall(args.get('query'))
            elif name=='forget_memory': result={'deleted':self.forget(args.get('id'))}
            elif name=='list_people': result=self.list_people()
            else: raise ValueError('Unknown memory tool.')
            return json.dumps(result,ensure_ascii=False),None
        except (ValueError,sqlite3.Error,OSError): return 'Memory request not completed: check that memory is enabled and explicitly requested; use valid names, facts or IDs.',None

manager=MemoryManager()
