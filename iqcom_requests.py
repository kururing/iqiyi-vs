"""Bounded public-metadata cache and in-flight request sharing; never persist credentials."""
from concurrent.futures import Future
from functools import wraps
import threading
import time


class RequestCache:
    def __init__(self, capacity=512):
        self.capacity = capacity
        self.lock = threading.Lock()
        self.cache = {}
        self.pending = {}

    def run(self, key, load, *, ttl=0, error_ttl=0, refresh=False):
        with self.lock:
            cached = self.cache.get(key)
            if not refresh and cached and cached[0] > time.monotonic():
                future, owner = cached[1], False
            elif key in self.pending:
                future, owner = self.pending[key], False
            else:
                future, owner = Future(), True
                self.pending[key] = future
        if not owner:
            return future.result()
        try:
            value = load()
            lifetime = ttl(value) if callable(ttl) else ttl
        except BaseException as exc:
            self._finish(key, future, error_ttl if isinstance(exc, Exception) else 0)
            future.set_exception(exc)
            raise
        self._finish(key, future, lifetime)
        future.set_result(value)
        return value

    def _finish(self, key, future, lifetime):
        with self.lock:
            if lifetime > 0:
                if len(self.cache) >= self.capacity and key not in self.cache:
                    oldest = min(self.cache, key=lambda item: self.cache[item][0])
                    self.cache.pop(oldest)
                self.cache[key] = (time.monotonic() + lifetime, future)
            else:
                self.cache.pop(key, None)
            self.pending.pop(key, None)


PUBLIC_METADATA = RequestCache(capacity=128)
LOOKUPS = RequestCache()


def singleflight(function):
    """Share only overlapping work; signed playback data is never cached here."""
    @wraps(function)
    def call(*args, **kwargs):
        key = (function.__name__, args, tuple(sorted(kwargs.items())))
        return LOOKUPS.run(key, lambda: function(*args, **kwargs))
    return call
