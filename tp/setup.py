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
        'sync': opts.get('sync') or 'auto',
    }
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
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(all_, open(path, 'w'))
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
    if not opts.get('sync') and saved.get('sync'):
        opts['sync'] = saved['sync']
    if not mpv and saved.get('extra'):  # user passed no flags -> restore theirs
        mpv += saved['extra'].split()
    if saved.get('fullscreen') and '--fullscreen' not in mpv:
        mpv.append('--fullscreen')
    return opts, mpv
