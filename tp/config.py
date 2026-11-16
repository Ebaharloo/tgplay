"""tp.config - filesystem paths + tunables as one injectable object.

No module-level globals: a `Config` instance is passed where needed, so tests
can point it at a sandbox HOME/tmp and the CLIs construct the real one.
"""
import os
import re

DEFAULT_CACHE_BUDGET = 2 * 1024 * 1024 * 1024   # /tmp is tmpfs (RAM)
DEFAULT_PROXY_PORT = 8898


def save_json(path, data):
    """Write JSON atomically: a crash mid-write must not eat the old file.

    The temp file name is unique per writer: worker threads write the same
    cache (relations.json, episodes.json) concurrently, and a shared `.tmp`
    name made one rename lose the race with ENOENT.
    """
    import json
    import os
    import tempfile
    d = os.path.dirname(path) or '.'
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + '.',
                               suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_json(path, default=None):
    import json
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


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
    def translations(self):
        return self._p('translations.json')

    @property
    def recent(self):
        return self._p('recent.json')

    @property
    def ui(self):
        return self._p('ui.json')

    @property
    def anilist_auth(self):
        return self._p('anilist.json')

    @property
    def simkl_auth(self):
        return self._p('simkl_auth.json')

    @property
    def anilist_ids(self):
        return self._p('anilist_ids.json')

    @property
    def characters(self):
        return self._p('characters.json')

    @property
    def posters(self):
        return self._p('posters.json')

    @property
    def relations(self):
        return self._p('relations.json')

    @property
    def episodes(self):
        return self._p('episodes.json')

    @property
    def watched(self):
        return self._p('watched.json')

    @property
    def simkl_queue(self):
        return self._p('pending_sync.json')

    @property
    def tg_session(self):
        # NB: no '.session' suffix - telethon appends it, and would otherwise
        # treat the path as the literal file.
        return os.environ.get('TG_SESSION') or os.path.join(self.conf, 'tg')

    # --- cache -------------------------------------------------------------
    def cache_path(self, name):
        os.makedirs(self.cache_dir, exist_ok=True)
        return f'{self.cache_dir}/{re.sub(r"[^A-Za-z0-9._-]", "_", name)}'

    def ensure(self):
        os.makedirs(self.conf, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        return self
