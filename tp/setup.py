"""tp.setup - remember the last menu setup so the next menu is pre-filled.

Only the *menu* uses this: a plain flag run is untouched. CLI flags always win
over the saved values; the saved setup only fills in what you left unset.

The value normalization lives in tp.options (the one shared playback-options
model) — this module is just the ui.json file format on top of it.
"""
import json
import os
from typing import List, Tuple

from .options import PlaybackOptions, quality_key as _quality_key  # noqa: F401


def load(path, key: str = 'agp') -> dict:
    try:
        d = json.load(open(path))
    except Exception:
        return {}
    if not isinstance(d, dict):
        return {}
    if isinstance(d.get(key), dict):        # namespaced per source
        return d[key]
    if key == 'agp' and ('quality' in d or 'skip' in d or 'extra' in d):
        return d                            # legacy flat file belongs to agp
    return {}


def save(path, opts: dict, mpv: List[str], key: str = 'agp') -> dict:
    d = PlaybackOptions(opts, mpv).saved_shape()
    try:
        all_ = {}
        try:
            all_ = json.load(open(path))
            if not isinstance(all_, dict):
                all_ = {}
        except Exception:
            all_ = {}
        if key not in all_ and ('quality' in all_ or 'skip' in all_):
            all_ = {'agp': all_}            # migrate the legacy flat file
        all_[key] = d
        from .config import save_json
        save_json(path, all_)
    except Exception:
        pass
    return d


def apply(opts: dict, mpv: List[str], saved: dict) -> Tuple[dict, List[str]]:
    """Prefill `opts`/`mpv` from `saved`, never overriding a CLI value."""
    po = PlaybackOptions(opts, mpv)
    po.merge_saved(saved)
    return po.to_opts(), po.mpv()
