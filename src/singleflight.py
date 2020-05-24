#-*- coding:utf-8 -*-
"""singleflight
Coalesce multiple identical call into one, preventing thundering-herd/stampede

python port of https://github.com/golang/groupcache/blob/master/singleflight/singleflight.go
"""

from threading import Event, Thread, Lock
from time import sleep
from typing import Callable
from functools import wraps, partial

class CallLock:
  """
  An internal object, that is used to track
  multiple call, and passing the result.

  Outside user should have no need for this class

  Have tried using @dataclass,
  but it caused the event `ev` to be created only once
  and shared between all request later,
  causing subsequent request to get wrong result/err
  """
  def __init__(self):
    super().__init__()
    self.ev = Event()
    self.res = None
    self.err = None

class SingleFlight:
  """
  The multi-threading version of SingleFlight

  An application only need one of this object, 
  as it can manage lots of call at the same time

  Object generated by this class is thread-safe
  """
  def __init__(self):
    super().__init__()
    self.lock = Lock()
    self.m = {}

  def call(self, fn: Callable[[any], any], key: str, *args,**kwargs) -> any:
    """
    Call `fn` with the given `*args` and `**kwargs` exactly once

    `key` are used to detect and coalesce duplicate call

    `key` is only hold for the duration of this function, after that it will be removed and `key` can be used again
    """
    if not isinstance(key, str):
      raise TypeError("Key should be a str")
    if not isinstance(fn, Callable):
      raise TypeError("fn should be a callable")

    # this part does not use with-statement
    # because the one need to be waited is different object (self.lock vs self.m[key].ev)
    self.lock.acquire(True)
    if key in self.m:
      # key exists here means 
      # another thread is currently making the call
      # just need to wait
      self.lock.release()
      self.m[key].ev.wait()

      if self.m[key].err:
        raise self.m[key].err
      return self.m[key].res

    cl = CallLock()
    self.m[key] = cl
    self.lock.release()

    try:
      cl.res = fn(*args, **kwargs)
      cl.err = None
    except Exception as e:
      cl.res = None
      cl.err = e

    # give time for other threads to get value
    # or raising error (if any)
    # adding sleep a bit (currently hardcoded to 10ms) is still better
    # than database/any backend got stampeded
    cl.ev.set()
    sleep(0.01)
    
    # delete the calllock, so next call
    # with same key can pass through
    with self.lock:
      del(self.m[key])

    if cl.err is not None:
      raise cl.err
    return cl.res

  def wrap(self, fn: Callable[[any], any]):
    """ simple wrapper for SingleFlight.call """
    @wraps(fn)
    def wrapper(*args, **kwargs):
      return partial(self.call, fn, *args, **kwargs)

    return wrapper()
