"""Translate missing UI copy on the local service; never load legacy dictionaries."""
from __future__ import annotations
import json
import urllib.request
from urllib.parse import urlencode
from iqcom_requests import RequestCache

UI_TRANSLATIONS = RequestCache(capacity=256)


def validate_ui_texts(texts: object) -> list[str]:
    if (not isinstance(texts, list) or not 1 <= len(texts) <= 8 or
            any(not isinstance(text, str) or not text.strip() or len(text) > 500 for text in texts)):
        raise ValueError("UI translation requires 1-8 nonempty strings, at most 500 characters each")
    return texts


def translate_ui(texts: object) -> list[str]:
    values = validate_ui_texts(texts)
    def load():
        query = urlencode([("client", "dict-chrome-ex"), ("sl", "zh-CN"), ("tl", "vi")]
                          + [("q", text) for text in values])
        if len(query) > 8000:
            # Keep the same response order while bounding upstream URL size.
            return [translate_ui([text])[0] for text in values]
        request = urllib.request.Request("https://clients5.google.com/translate_a/t?" + query,
                                         headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read(128_001)
        if len(raw) > 128_000:
            raise ValueError("UI translation response too large")
        result = json.loads(raw)
        if (not isinstance(result, list) or len(result) != len(values) or
                any(not isinstance(text, str) or not text.strip() for text in result)):
            raise ValueError("Invalid UI translation response")
        return result
    return list(UI_TRANSLATIONS.run(tuple(values), load, ttl=3600, error_ttl=10))
