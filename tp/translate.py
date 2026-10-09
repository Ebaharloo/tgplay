"""tp.translate - zh -> en for episode names, cached forever.

Uses MyMemory (free, keyless). Every successful translation is stored in
`translations.json`, so a name is translated once and never again. Names that
fail (rate limit / offline) are simply retried on a later run.
"""
import json
import os
import re
import urllib.parse
from typing import Iterable, List, Optional

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
        """Translate every not-yet-cached CJK name, BATCHED (names joined by
        newlines, a few requests instead of one per name)."""
        todo = []
        for t in dict.fromkeys(texts):
            t = (t or '').strip()
            if t and has_cjk(t) and t not in self._cache:
                todo.append(t)
        batch, size = [], 0
        for t in todo:
            if batch and (size + len(t) + 1 > 400 or len(batch) >= 20):
                self._translate_batch(batch)
                batch, size = [], 0
            batch.append(t)
            size += len(t) + 1
        if batch:
            self._translate_batch(batch)

    def _translate_batch(self, names: List[str]) -> None:
        if len(names) == 1:
            self.translate(names[0])
            return
        try:
            url = API + '?' + urllib.parse.urlencode(
                {'q': '\n'.join(names), 'langpair': 'zh-CN|en'})
            r = self.http.open(self.http.request(url))
            try:
                d = json.load(r)
            finally:
                _quiet_close(r)
            out = ((d.get('responseData') or {}).get('translatedText') or '')
            parts = out.split('\n')
            if len(parts) == len(names) and not any(
                    'MYMEMORY WARNING' in p.upper() for p in parts):
                for src, en in zip(names, parts):
                    en = en.strip()
                    if en:
                        self._cache[src] = en
                self._save()
                return
        except Exception:
            pass
        # batch shape unusable -> leave for a later run (never hammer per-name)
