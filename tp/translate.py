"""tp.translate - zh -> en for episode names, cached forever.

Uses MyMemory (free, keyless). Every successful translation is stored in
`translations.json`, so a name is translated once and never again. Names that
fail (rate limit / offline) are simply retried on a later run.
"""
import json
import os
import re
import urllib.parse
from typing import Iterable, Optional

from .http import HttpClient, _quiet_close

_CJK = re.compile(r'[\u4e00-\u9fff]')
API = 'https://api.mymemory.translated.net/get'


def has_cjk(s: str) -> bool:
    return bool(_CJK.search(s or ''))


class Translator:
    def __init__(self, cache_path: str, http: Optional[HttpClient] = None):
        self.path = cache_path
        self.http = http or HttpClient(timeout=15)
        self._cache = self._load()

    def _load(self) -> dict:
        try:
            return json.load(open(self.path))
        except Exception:
            return {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            json.dump(self._cache, open(self.path, 'w'))
        except Exception:
            pass

    def get(self, text: str) -> Optional[str]:
        return self._cache.get((text or '').strip())

    def translate(self, text: str) -> Optional[str]:
        text = (text or '').strip()
        if not text or not has_cjk(text):
            return text or None
        if text in self._cache:
            return self._cache[text]
        en = None
        try:
            url = API + '?' + urllib.parse.urlencode(
                {'q': text, 'langpair': 'zh-CN|en'})
            r = self.http.open(self.http.request(url))
            try:
                d = json.load(r)
            finally:
                _quiet_close(r)
            t = ((d.get('responseData') or {}).get('translatedText') or '').strip()
            up = t.upper()
            if t and 'MYMEMORY WARNING' not in up and 'DISTINCT' not in up \
                    and len(t) < 200:
                en = t
        except Exception:
            en = None
        if en:
            self._cache[text] = en
            self._save()
            return en
        return None

    def ensure(self, texts: Iterable[str]):
        """Translate every CJK name that is not cached yet (best-effort)."""
        for t in texts:
            if has_cjk(t or ''):
                self.translate(t)
