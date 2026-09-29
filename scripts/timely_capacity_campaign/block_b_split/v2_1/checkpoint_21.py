"""Instrumentation-only immutable snapshots. Never serialize a live shared mapping."""
from dataclasses import dataclass
import json
import sys
import threading

@dataclass(frozen=True)
class Frozen:
    kind:str
    values:tuple

def freeze(value):
    # CPython builtin shallow copies hold the GIL. Recursion iterates only private
    # copies, never the thread-shared dict/list. No retry, sleeps or dropped keys.
    if isinstance(value,dict):
        private=dict.copy(value)
        return Frozen('dict',tuple((k,freeze(v)) for k,v in private.items()))
    if isinstance(value,list):return Frozen('list',tuple(freeze(v) for v in list.copy(value)))
    if isinstance(value,tuple):return Frozen('list',tuple(freeze(v) for v in value))
    if value is None or isinstance(value,(str,int,float,bool)):return value
    raise TypeError('Unsupported checkpoint object: '+type(value).__name__)

def thaw(value):
    if not isinstance(value,Frozen):return value
    if value.kind=='dict':return {k:thaw(v) for k,v in value.values}
    return [thaw(v) for v in value.values]

class Manifest(dict):
    """Lock only manifest publication/snapshot, never inference/queues/socket I/O."""
    def __init__(self,value):
        if sys.implementation.name!='cpython' or (hasattr(sys,'_is_gil_enabled') and not sys._is_gil_enabled()):
            raise RuntimeError('Snapshot strategy requires CPython with GIL')
        self.capture_lock=threading.RLock();super().__init__(value)
    def __setitem__(self,key,value):
        with self.capture_lock:dict.__setitem__(self,key,value)
    def update(self,*args,**kwargs):
        with self.capture_lock:dict.update(self,*args,**kwargs)
    def snapshot(self):
        with self.capture_lock:return freeze(self)

def serialize(data):
    frozen=data.snapshot() if isinstance(data,Manifest) else data if isinstance(data,Frozen) else freeze(data)
    # All locks are released before conversion and JSON encoding/I/O.
    return json.dumps(thaw(frozen),indent=2)+'\n'

def write_json(path,data):
    from pathlib import Path
    path=Path(path);text=serialize(data)
    temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(text);temporary.replace(path)

