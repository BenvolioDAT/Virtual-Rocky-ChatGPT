"""Anonymous bounding-box continuity and explicit labels, in RAM for one session.

No face recognition, crops, embeddings, image hashes or cross-session matching.
Labels are dropped on missed detections or ambiguous box continuity.
"""
import copy
import re
import threading
import time
import uuid


def overlap(a,b):
    x=max(a[0],b[0]); y=max(a[1],b[1]); r=min(a[0]+a[2],b[0]+b[2]); bottom=min(a[1]+a[3],b[1]+b[3])
    intersection=max(0,r-x)*max(0,bottom-y)
    union=a[2]*a[3]+b[2]*b[3]-intersection
    return intersection/union if union>0 else 0


def introduction(question):
    match=re.search(r'\b(?i:this is|that.s|label (?:this|the) person(?: as)?)\s+([A-Z][a-zA-Z\'-]*(?:\s+[A-Z][a-zA-Z\'-]*){0,3})(?=[.!?,]|$)',question)
    return match[1] if match else None


class SessionPeople:
    def __init__(self,clock=time.monotonic):
        self.clock=clock; self._lock=threading.RLock(); self._next=0; self.reset()
    def reset(self):
        with self._lock: self.session=uuid.uuid4().hex; self._tracks={}; self._updated=0
    def update(self,boxes):
        now=self.clock()
        with self._lock:
            old=self._tracks if now-self._updated<=2 else {}
            new={}; boxes=[tuple(float(v) for v in b[:4]) for b in boxes[:20]]
            for box in boxes:
                matches=[id for id,t in old.items() if overlap(box,t['box'])>=.3]
                # Only one old box AND one new box can overlap; ambiguity loses labels.
                id=matches[0] if len(matches)==1 and sum(overlap(b,old[matches[0]]['box'])>=.3 for b in boxes)==1 else None
                if id is None:
                    self._next+=1; id=str(self._next)
                new[id]=dict(track_id=id,box=box,name=old.get(id,{}).get('name'))
            self._tracks=new; self._updated=now
    def visible(self):
        with self._lock:
            if self.clock()-self._updated>2: self._tracks={}
            return copy.deepcopy(sorted(self._tracks.values(),key=lambda t:t['box'][0]))
    def label(self,name,position=None,track_id=None):
        if not isinstance(name,str) or not name.strip() or len(name)>100: raise ValueError('Use a name of at most 100 characters.')
        with self._lock:
            visible=self.visible()
            if not visible: raise ValueError('No current anonymous face track is visible; turn on the camera and face tracking.')
            if track_id is not None: choices=[t for t in visible if t['track_id']==str(track_id)]
            elif position in ('left','right'): choices=[visible[0 if position=='left' else -1]]
            elif position=='center': choices=[visible[len(visible)//2]] if len(visible)%2 else []
            elif len(visible)==1: choices=visible
            else: raise ValueError('Which person? Specify left, center, right, or a visible track ID.')
            if len(choices)!=1: raise ValueError('That person is ambiguous or no longer visible.')
            self._tracks[choices[0]['track_id']]['name']=name.strip()
            return dict(track_id=choices[0]['track_id'],name=name.strip(),session_only=True)

manager=SessionPeople()
