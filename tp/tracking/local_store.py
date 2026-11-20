"""tp.tracking.local_store - watched.json + progress.json behind one facade.

watched.json keeps per-episode state WITH tombstones (an episode the user
unmarked here), so a remote pull cannot resurrect it. progress.json keeps the
local play position. No network, no Qt: every sync object writes through here.
"""
import os

from ..config import load_json, save_json
from .. import watched as _w

KINDS = _w.KINDS


def key_for(title, ids=None):
    """Store key for a show: simkl id, then mal id, else the title."""
    return _w.key_for(title, ids)


class LocalStore:
    def __init__(self, cfg):
        self.cfg = cfg

    # --- watched ----------------------------------------------------------
    def path(self):
        return _w._path(self.cfg)

    def state(self, key):
        return _w.state(self.cfg, key)

    def episodes(self, key):
        return self.state(key)['eps']

    def change(self, key, kind, num, nums, watched=None):
        """Apply one menu choice locally; `(kind, on)`."""
        return _w.change(self.cfg, key, kind, num, nums, watched)

    def set_episode(self, key, num, watched=None):
        return _w.set_episode(self.cfg, key, num, watched)

    def set_season(self, key, nums, watched):
        return _w.set_season(self.cfg, key, nums, watched)

    def tombstones(self, key):
        return self.state(key)['tomb']

    def rows(self, key):
        """Menu checkbox state for the loaded show (title-key independent)."""
        return self.state(key)

    def keyed(self):
        """Every stored show key, first-seen order."""
        return [k for k in (load_json(self.path(), {}) or {})]

    # --- progress (local resume position) ---------------------------------
    @property
    def progress_path(self):
        return self.cfg.progress

    def progress(self):
        d = load_json(self.progress_path, {}) or {}
        return d if isinstance(d, dict) else {}

    def save_progress(self, title, ep, pos=0):
        """progress.json `ep` is current-or-next, `pos` the seconds played."""
        d = self.progress()
        d[str(title)] = {'ep': int(ep), 'pos': float(pos or 0)}
        try:
            save_json(self.progress_path, d)
        except Exception:
            pass          # a read-only home must not kill playback
        return d[str(title)]

    def entry(self, title):
        return self.progress().get(str(title)) or {}

    def clear_progress(self, title):
        d = self.progress()
        gone = d.pop(str(title), None) is not None
        if gone:
            save_json(self.progress_path, d)
        return gone


def default_store(cfg):
    return LocalStore(cfg)
