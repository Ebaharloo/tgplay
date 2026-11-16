"""tp.watched - the local per-episode watched store (no network, no Qt).

One JSON file (``~/.config/tgp/watched.json``), keyed by the strongest id the
session knows (Simkl, then MAL, else the title) so a later Simkl sync needs no
title matching::

    {"mal:51289": {"eps": [1, 2], "complete": false}}

Every episode list writes through here, and the same module renders the menu
rows as a pure function, so the label/checked/disabled mapping is testable
without Qt. Widgets call `change` and emit their own `on_watched_changed`.
"""
import os
import re
import time

from .config import load_json, save_json

KINDS = ('episode', 'season', 'season_unwatched', 'series')


def _path(cfg):
    return getattr(cfg, 'watched', None) or os.path.join(cfg.conf,
                                                         'watched.json')


def key_for(title, ids=None):
    """The store key for a show: simkl id, then mal id, else the title."""
    ids = ids or {}
    for k in ('simkl', 'mal'):
        if ids.get(k):
            return f'{k}:{ids[k]}'
    return 't:' + re.sub(r'[^a-z0-9]+', '', (title or '').lower())


def state(cfg, key):
    try:
        d = (load_json(_path(cfg), {}) or {}).get(key) or {}
    except Exception:
        d = {}
    at = {}
    try:                    # per-episode 'watched at' (epoch) for Simkl merge
        at = {int(k): float(v) for k, v in (d.get('at') or {}).items()}
    except Exception:
        at = {}
    return {'eps': {int(n) for n in (d.get('eps') or [])
                    if str(n).isdigit()},
            'complete': bool(d.get('complete')),
            'at': at}


def _put(cfg, key, st):
    p = _path(cfg)
    try:
        d = load_json(p, {}) or {}
    except Exception:
        d = {}
    at = {str(n): float(ts) for n, ts in (st.get('at') or {}).items()
          if n in st['eps']}
    d[key] = {'eps': sorted(st['eps']), 'complete': bool(st['complete']),
              'at': at}
    save_json(p, d)


def set_episode(cfg, key, num, watched=None):
    """Toggle (watched=None) or set one episode; returns its new state."""
    st = state(cfg, key)
    num = int(num)
    on = (num not in st['eps']) if watched is None else bool(watched)
    st['eps'] = (st['eps'] | {num}) if on else (st['eps'] - {num})
    # shortcut: an unmark leaves no tombstone, so a Simkl pull only ever adds
    # episodes; add one if a local unmark must beat a remote mark
    st['at'].pop(num, None)
    if on:
        st['at'][num] = time.time()
    _put(cfg, key, st)
    return on


def set_season(cfg, key, nums, watched):
    """Every episode of the current list at once; returns the new state."""
    st = state(cfg, key)
    nums = {int(n) for n in nums}
    st['eps'] = (st['eps'] | nums) if watched else (st['eps'] - nums)
    now = time.time()
    for n in nums:
        st['at'].pop(n, None)
        if watched:
            st['at'][n] = now
    _put(cfg, key, st)
    return bool(watched)


def set_complete(cfg, key, watched=None):
    """Toggle (watched=None) or set the whole-series complete flag."""
    st = state(cfg, key)
    on = (not st['complete']) if watched is None else bool(watched)
    st['complete'] = on
    _put(cfg, key, st)
    return on


def change(cfg, key, kind, num, nums, watched=None):
    """Apply one menu choice; returns `(kind, watched)` for the hook."""
    if kind == 'episode':
        return kind, set_episode(cfg, key, num, watched)
    if kind == 'series':
        return kind, set_complete(cfg, key, watched)
    if kind in ('season', 'season_unwatched'):
        return kind, set_season(cfg, key, nums,
                                kind == 'season' if watched is None
                                else watched)
    raise ValueError(f'unknown watched action {kind!r}')


def rows(st, num, nums):
    """Menu rows for one episode: `(kind, label, checked, enabled)`.

    `nums` is the episode list on screen (= the season). Nothing to mark
    watched/unwatched leaves that row disabled instead of a no-op click.
    """
    nums = {int(n) for n in nums}
    num = int(num)
    watched = num in st['eps']
    hit = len(nums & st['eps'])
    return [
        ('episode', 'Mark unwatched' if watched else 'Mark watched',
         watched, True),
        ('season', 'Mark whole season watched', False, hit < len(nums)),
        ('season_unwatched', 'Mark season unwatched', False, hit > 0),
        ('series',
         'Unmark complete' if st['complete'] else 'Mark series complete',
         bool(st['complete']), True),
    ]
