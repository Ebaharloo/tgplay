"""tp.config - filesystem paths + tunables as one injectable object.

No module-level globals: a `Config` instance is passed where needed, so tests
can point it at a sandbox HOME/tmp and the CLIs construct the real one.
"""
import os
import re

DEFAULT_CACHE_BUDGET = 2 * 1024 * 1024 * 1024   # /tmp is tmpfs (RAM)
DEFAULT_PROXY_PORT = 8898


class Config:
    def __init__(self, home=None, cache_dir=None, proxy_port=None,
                 cache_budget=None, tmpdir=None):
        self.home = home or os.path.expanduser('~')
        self.conf = os.path.join(self.home, '.config', 'tgp')
        base = tmpdir or os.environ.get('TMPDIR') or '/tmp'
        self.cache_dir = cache_dir or os.path.join(base, 'agp-cache')
        self.proxy_port = int(proxy_port or os.environ.get('TG_TEST_PORT')
                              or DEFAULT_PROXY_PORT)
        self.cache_budget = cache_budget or DEFAULT_CACHE_BUDGET

    # --- config files ------------------------------------------------------
    def _p(self, name):
        return os.path.join(self.conf, name)

    @property
    def progress(self):
        return self._p('progress.json')

    @property
    def mal_ids(self):
        return self._p('mal_ids.json')

    @property
    def ep_titles(self):
        return self._p('ep_titles.json')

    @property
    def recent(self):
        return self._p('recent.json')

    @property
    def anilist_auth(self):
        return self._p('anilist.json')

    @property
    def anilist_ids(self):
        return self._p('anilist_ids.json')

    # --- cache -------------------------------------------------------------
    def cache_path(self, name):
        os.makedirs(self.cache_dir, exist_ok=True)
        return f'{self.cache_dir}/{re.sub(r"[^A-Za-z0-9._-]", "_", name)}'

    def ensure(self):
        os.makedirs(self.conf, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        return self
