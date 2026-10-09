"""tp.setup - remember the last menu setup so the next menu is pre-filled.

Only the *menu* uses this: a plain flag run is untouched. CLI flags always win
over the saved values; the saved setup only fills in what you left unset.
"""
import json
import os
import re
from typing import List, Tuple


def _quality_key(label) -> str:
    if not label:
        return None
    if re.search(r'x265', str(label), re.I):
        return 'x265'
    m = re.search(r'(\d{3,4})', str(label))
    return m.group(1) if m else str(label)


def load(path) -> dict:
    try:
        return json.load(open(path))
    except Exception:
        return {}


def save(path, opts: dict, mpv: List[str]) -> dict:
    d = {
        'skip': opts.get('skip') or False,
        'skip_toggle': bool(opts.get('skip_toggle')),
        'next': opts.get('next') or False,
        'nowait': bool(opts.get('nowait')),
        'cut': opts.get('cut'),
        'fullscreen': '--fullscreen' in mpv,
        'extra': ' '.join(x for x in mpv if x != '--fullscreen'),
        'quality': _quality_key(opts.get('f')),
        'audio': opts.get('audio') or 'dub',
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(d, open(path, 'w'))
    except Exception:
        pass
    return d


def apply(opts: dict, mpv: List[str], saved: dict) -> Tuple[dict, List[str]]:
    """Prefill `opts`/`mpv` from `saved`, never overriding a CLI value."""
    if not saved:
        return opts, mpv
    opts = dict(opts)
    mpv = list(mpv)
    if not opts.get('skip') and saved.get('skip'):
        opts['skip'] = saved['skip']
    if not opts.get('skip_toggle') and saved.get('skip_toggle'):
        opts['skip_toggle'] = True
    if not opts.get('next') and saved.get('next'):
        opts['next'] = saved['next']
    if not opts.get('nowait') and saved.get('nowait'):
        opts['nowait'] = True
    if opts.get('cut') is None and saved.get('cut'):
        opts['cut'] = saved['cut']
    if not opts.get('f') and saved.get('quality'):
        opts['f'] = saved['quality']
    if not opts.get('audio') and saved.get('audio'):
        opts['audio'] = saved['audio']
    if not mpv and saved.get('extra'):  # user passed no flags -> restore theirs
        mpv += saved['extra'].split()
    if saved.get('fullscreen') and '--fullscreen' not in mpv:
        mpv.append('--fullscreen')
    return opts, mpv
