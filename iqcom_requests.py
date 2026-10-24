"""Bounded public-metadata cache and in-flight request sharing; never persist credentials."""
import atexit
from concurrent.futures import Future
from contextlib import contextmanager
from functools import wraps
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

import urllib3


# No cookie jar or system proxy: each request supplies only its own credentials.
HTTP_POOL = urllib3.PoolManager(num_pools=8, maxsize=6, block=True)
atexit.register(HTTP_POOL.clear)


@contextmanager
def pooled_open(request, timeout=15, *, public_iqcom_page=False):
    """Stream bytes; only anonymous iq.com catalog pages may follow redirects."""
    if isinstance(request, str):
        request = urllib.request.Request(request)
    if public_iqcom_page and (request.get_method() != "GET" or request.data is not None or
                            any(key.lower() in ("cookie", "authorization", "proxy-authorization")
                                for key, _ in request.header_items())):
        raise ValueError("Only anonymous iq.com pages may follow redirects")
    response = None
    try:
        url = request.full_url
        for attempt in range(4):
            if public_iqcom_page:
                parsed = urlsplit(url)
                if (parsed.scheme != "https" or parsed.netloc != "www.iq.com" or
                        not parsed.path.startswith(("/play/", "/album/"))):
                    raise ValueError("iq.com page redirect is not allowed")
            response = HTTP_POOL.request(
                request.get_method(), url, body=request.data,
                headers=dict(request.header_items()), preload_content=False,
                decode_content=False, redirect=False, retries=False,
                timeout=urllib3.Timeout(connect=timeout, read=timeout), pool_timeout=timeout)
            if response.status not in (301, 302, 303, 307, 308) or not response.headers.get("Location"):
                break
            if not public_iqcom_page:
                raise ValueError("Session metadata redirects are not allowed")
            if attempt == 3:
                raise ValueError("Too many iq.com page redirects")
            url = urljoin(url, response.headers["Location"])
            response.close()
            response.release_conn()
            response = None
        if not 200 <= response.status < 300:
            raise urllib.error.HTTPError(url, response.status,
                                         response.reason, response.headers, None)
        yield response
    except urllib3.exceptions.HTTPError as exc:
        raise urllib.error.URLError(exc) from exc
    finally:
        if response is not None:
            # A fully read response already returned its connection to the pool;
            # an unread/oversized response must close before releasing the slot.
            response.close()
            response.release_conn()


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
            future.set_exception(exc)
            self._finish(key, future, error_ttl if isinstance(exc, Exception) else 0)
            raise
        future.set_result(value)
        self._finish(key, future, lifetime)
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
