"""tp.options - the ONE shared model for playback options.

Every interface renders the same field specs and routes values through the
same normalizing `PlaybackOptions` object, so an option can never exist in
one window and silently vanish in another:

    Qt window            tp/gui_all.OptionsForm (built from `form_fields`)
    curses / plain form  tp/ui.gather (built from `form_fields`)
    remembered setup     tp/setup.py (ui.json, via `saved_shape`/`merge_saved`)
    CLI flags            tp/cli.parse (same legacy opts dict)

Complete field inventory (== setup.save keys == parse keys == both forms):

    quality  'f'    Server: (audio) / Quality — dynamic, per-session groups
    audio           dub / sub / auto (AnimeX only)
    episodes 'e','a' text 'a | 1-12,2-5,9' (curses menu only; sets e/a)
    skip            off / all / names / auto (dict value False or the mode)
    skip_toggle     bool — turn skip off in mpv with T
    next            False, or a float fraction (0.60 default) when pre-
                    downloading the next episode is enabled
    nowait          bool — start that download at the cut point
    cut             int or None — stop each episode N s early
    start           int or None — begin episode 1 here (not the resume point)
    end             int or None — stop episode 1 at this absolute position
    sync            'auto' / 'off' — push watch progress to Simkl
    fullscreen      bool — extra mpv flag (--fullscreen also lives in extras)
    extra           arbitrary extra mpv flags (list of str)

The dict contract stays the legacy shape at every boundary (opts dict +
mpv list) — this model just wraps/normalizes it in exactly one place.
"""
import math
from typing import Dict, List, Optional, Tuple

SKIP_MODES = ['off', 'all', 'names', 'auto']
AUDIO_MODES = ['dub', 'sub', 'auto']
FULLSCREEN_FLAG = '--fullscreen'
DEFAULT_NEXT = 0.60          # fraction where 'next' starts when enabled

_DEFAULT_OPTS = {'a': False, 'skip': False, 'skip_toggle': False, 'e': None,
                 'f': None, 'cut': None, 'start': None, 'end': None,
                 'next': False, 'nowait': False, 'sync': 'auto'}


def quality_key(label) -> Optional[str]:
    """Short key of a quality/server label for remembering ('x265', '720…')."""
    import re
    if not label:
        return None
    if re.search(r'x265', str(label), re.I):
        return 'x265'
    m = re.search(r'(\d{3,4})', str(label))
    return m.group(1) if m else str(label)


def _norm_skip(v):
    # 'off' stays an explicit string (GUI pick) so it is not confused with the
    # legacy unset False, which still means 'all'
    if isinstance(v, str):
        return v if v in SKIP_MODES else False
    return False


def _norm_next(v):
    if isinstance(v, bool):
        return DEFAULT_NEXT if v else False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return max(0.01, min(f, 0.99)) if f else False


def _norm_cut(v):
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    s = str(v or '').strip()
    return int(s) if s.isdigit() else None


def _norm_pos(v) -> Optional[int]:
    """Seconds from 90, '90', '1:30' or '1:02:03'; blank/garbage -> None."""
    if isinstance(v, int) and not isinstance(v, bool):
        return v if v >= 0 else None
    parts = str(v or '').strip().split(':')
    if not 1 <= len(parts) <= 3:
        return None
    try:
        secs = sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))
    except (ValueError, OverflowError):
        return None
    # 'inf' / '1e400' parse to a float but are not a usable position
    return int(secs) if secs >= 0 and math.isfinite(secs) else None


class PlaybackOptions:
    """Normalized read/write view over the legacy opts dict + mpv list.

    All normalization lives here so the Qt form, the curses form, the saved
    setup and the CLI flags all agree on every option.
    """

    def __init__(self, raw: Dict = None, mpv: List[str] = None):
        o = dict(_DEFAULT_OPTS)
        o.update(raw or {})
        self._o: Dict = o
        self._mpv: List[str] = list(mpv or [])

    # --- individual options --------------------------------------------
    @property
    def quality(self):
        return self._o.get('f')

    @quality.setter
    def quality(self, v):
        self._o['f'] = v or None

    @property
    def audio(self):
        return self._o.get('audio')

    @audio.setter
    def audio(self, v):
        self._o['audio'] = v if v in AUDIO_MODES else None

    @property
    def audio_mode(self) -> str:
        """The audio to actually use (AnimeX always wants one)."""
        return self._o.get('audio') if self._o.get('audio') in AUDIO_MODES \
            else 'dub'

    @property
    def skip(self):
        return self._o.get('skip')

    @property
    def skip_mode(self) -> str:
        """The combobox value (off/all/names/auto)."""
        s = self._o.get('skip')
        return s if isinstance(s, str) and s in SKIP_MODES else 'off'

    def set_skip(self, mode: str):
        self._o['skip'] = mode if mode in SKIP_MODES else 'off'

    @property
    def skip_toggle(self) -> bool:
        return bool(self._o.get('skip_toggle'))

    def set_skip_toggle(self, v: bool):
        self._o['skip_toggle'] = bool(v)

    @property
    def next(self):
        return self._o.get('next')

    def set_next(self, v):
        self._o['next'] = _norm_next(v)

    @property
    def nowait(self) -> bool:
        return bool(self._o.get('nowait'))

    def set_nowait(self, v: bool):
        self._o['nowait'] = bool(v)

    @property
    def cut(self) -> Optional[int]:
        return _norm_cut(self._o.get('cut'))

    def set_cut(self, v):
        self._o['cut'] = _norm_cut(v)

    @property
    def start(self) -> Optional[int]:
        return _norm_pos(self._o.get('start'))

    @start.setter
    def start(self, v):
        self._o['start'] = _norm_pos(v)

    @property
    def end(self) -> Optional[int]:
        return _norm_pos(self._o.get('end'))

    @end.setter
    def end(self, v):
        self._o['end'] = _norm_pos(v)

    @property
    def sync(self) -> str:
        return 'off' if self._o.get('sync') == 'off' else 'auto'

    def set_sync(self, v: bool or str):
        if isinstance(v, str):
            self._o['sync'] = 'off' if v == 'off' else 'auto'
        else:
            self._o['sync'] = 'auto' if v else 'off'

    @property
    def all_eps(self) -> bool:
        return bool(self._o.get('a'))

    def set_all_eps(self, v: bool):
        self._o['a'] = bool(v)

    @property
    def eps_selector(self) -> Optional[str]:
        return self._o.get('e')

    def set_eps_selector(self, v: Optional[str]):
        self._o['e'] = (v or None)

    # --- mpv list -------------------------------------------------------
    @property
    def fullscreen(self) -> bool:
        return FULLSCREEN_FLAG in self._mpv

    def set_fullscreen(self, v: bool):
        if v and FULLSCREEN_FLAG not in self._mpv:
            self._mpv.append(FULLSCREEN_FLAG)
        elif not v and FULLSCREEN_FLAG in self._mpv:
            self._mpv = [x for x in self._mpv if x != FULLSCREEN_FLAG]

    @property
    def extras(self) -> List[str]:
        """Extra mpv flags WITHOUT the fullscreen marker."""
        return [x for x in self._mpv if x != FULLSCREEN_FLAG]

    def set_extras(self, words: List[str]):
        """Replace the extra flags; keep/remove the fullscreen marker."""
        want_full = self.fullscreen
        self._mpv = [w for w in (words or []) if w != FULLSCREEN_FLAG]
        if want_full:
            self._mpv.append(FULLSCREEN_FLAG)

    def with_extras(self, words: List[str], fullscreen: bool = None):
        """Set extras; optionally replace the fullscreen flag."""
        self._mpv = [w for w in (words or []) if w != FULLSCREEN_FLAG]
        if fullscreen is not None:
            if fullscreen and FULLSCREEN_FLAG not in self._mpv:
                self._mpv.append(FULLSCREEN_FLAG)
        elif self.fullscreen:
            self._mpv.append(FULLSCREEN_FLAG)
        return self

    def mpv(self) -> List[str]:
        return list(self._mpv)

    # --- bulk conversions ----------------------------------------------
    def to_opts(self) -> Dict:
        o = dict(self._o)
        o['skip'] = _norm_skip(o.get('skip'))
        o['next'] = _norm_next(o.get('next'))
        o['cut'] = _norm_cut(o.get('cut'))
        o['start'] = self.start
        o['end'] = self.end
        o['sync'] = self.sync
        return o

    def to_mpv(self) -> List[str]:
        return list(self._mpv)

    def saved_shape(self) -> Dict:
        """The ui.json entry this run would be remembered as (setup.load shape)."""
        return {'skip': self._o.get('skip') or False,
                'skip_toggle': bool(self._o.get('skip_toggle')),
                'next': self._o.get('next') or False,
                'nowait': bool(self._o.get('nowait')),
                'cut': self._o.get('cut'),
                'fullscreen': self.fullscreen,
                'extra': ' '.join(self.extras),
                'quality': quality_key(self._o.get('f')),
                'audio': self._o.get('audio') or 'dub',
                'sync': self._o.get('sync') or 'auto'}

    def merge_saved(self, saved: Dict) -> 'PlaybackOptions':
        """Prefill from remembered values; never overrides a CLI/user value."""
        s = saved or {}
        if s.get('skip') and not self._o.get('skip'):
            self._o['skip'] = s['skip']
        if s.get('skip_toggle') and not self._o.get('skip_toggle'):
            self._o['skip_toggle'] = True
        if s.get('next') and not self._o.get('next'):
            self._o['next'] = s['next']
        if s.get('nowait') and not self._o.get('nowait'):
            self._o['nowait'] = True
        if s.get('cut') is not None and self._o.get('cut') is None:
            self._o['cut'] = s['cut']
        if not self._o.get('f') and s.get('quality'):
            self._o['f'] = s['quality']
        if not self._o.get('audio') and s.get('audio'):
            self._o['audio'] = s['audio']
        if not self._o.get('sync') and s.get('sync'):
            self._o['sync'] = s['sync']
        if not self._mpv and s.get('extra'):   # user passed no flags
            self._mpv += str(s['extra']).split()
        if s.get('fullscreen') and FULLSCREEN_FLAG not in self._mpv:
            self._mpv.append(FULLSCREEN_FLAG)
        return self

    @classmethod
    def defaults(cls) -> 'PlaybackOptions':
        return cls(dict(_DEFAULT_OPTS))


# --- form field specs (shared by Qt + curses renderers) -------------------
def form_fields(*, groups: List[str] = None, audio: bool = False,
                show_eps: bool = False, opts: Dict = None,
                mpv: List[str] = None) -> List[Dict]:
    """Neutral render spec for ONE form session.

    - `groups`: the session's quality/server labels ([] -> row omitted,
      Telegram; the 'eps' row write a/e), `audio` adds dub/sub/auto.
      `show_eps` adds the episodes text row (terminal menu only).
    Values come from normalized playback options, so every row shows exactly
    what setup/CLI/last play delivered.
    """
    po = PlaybackOptions(opts, mpv)
    fields: List[Dict] = []
    if groups:                          # Telegram has no groups -> no row
        labels = [str(g) for g in groups]
        cur = next((i for i, l in enumerate(labels)
                    if po.quality and str(po.quality).lower() in l.lower()), 0)
        fields.append({'k': 'quality',
                       'label': 'Server' if audio else 'Quality',
                       'kind': 'choice', 'choices': labels, 'i': cur,
                       'help': ('Which AnimeX server to stream from.' if audio
                                else 'Which release to stream '
                                     '(higher = larger/slower).')})
    if audio:
        fields.append({'k': 'audio', 'label': 'Audio  (dub / sub / auto)',
                       'kind': 'choice', 'choices': AUDIO_MODES,
                       'i': AUDIO_MODES.index(po.audio_mode),
                       'help': 'dub = English dub (default); sub = original '
                               'audio + subtitles; auto = dub when available, '
                               'else sub.'})
    if show_eps:
        fields.append({'k': 'eps', 'label': 'Episodes  (1-12, 2-5,9, a = all)',
                       'kind': 'text',
                       'val': po.eps_selector or 'a',
                       'help': 'Episodes to play, back-to-back.'})
    fields += [
        {'k': 'skip', 'label': 'Skip intro / outro', 'kind': 'choice',
         'choices': SKIP_MODES, 'i': SKIP_MODES.index(po.skip_mode),
         'help': 'names = chapters titled Intro/Opening/Ending/Credits; '
                 'auto = guess from a short leading/trailing chapter; all = '
                 'names then the guess; off = play everything.'},
        {'k': 'toggle', 'label': 'Allow turning skip off in mpv with T',
         'kind': 'flag', 'val': po.skip_toggle,
         'help': 'Press T in mpv to toggle skipping if a guess was wrong.'},
        {'k': 'next', 'label': 'Pre-download the next episode',
         'kind': 'flag', 'val': bool(po.next),
         # untouched + checked -> keep the exact fraction (CLI --next=N wins)
         'was': bool(po.next), 'orig': (po.next if not isinstance(po.next, bool)
                                        else None),
         'help': 'Fetch the next episode in the background while this plays.'},
        {'k': 'nowait', 'label': '   start that download at the cut point',
         'kind': 'flag', 'val': po.nowait,
         'help': 'Start it at (duration - Cut) instead of 60%. Needs a Cut.'},
        {'k': 'start', 'label': 'Start at  (mm:ss or seconds)', 'kind': 'text',
         'val': '' if po.start is None else str(po.start),
         'help': 'Begin the first episode at this position instead of the '
                 'saved resume point. Blank = resume/normal.'},
        {'k': 'end', 'label': 'Finish at  (mm:ss or seconds)', 'kind': 'text',
         'val': '' if po.end is None else str(po.end),
         'help': 'Stop the first episode at this absolute position. '
                 'Blank = play to the end (or to Cut).'},
        {'k': 'cut', 'label': 'Cut the last N seconds', 'kind': 'text',
         'val': str(po.cut or ''),
         'help': 'Stop each episode N seconds early. Blank = full.'},
        {'k': 'sync', 'label': 'Sync progress to Simkl', 'kind': 'flag',
         'val': po.sync == 'auto',
         'help': 'Off = never push watch progress to Simkl for this run.'},
        {'k': 'full', 'label': 'Fullscreen', 'kind': 'flag',
         'val': po.fullscreen, 'help': 'Start mpv fullscreen.'},
        {'k': 'extra', 'label': 'Extra mpv flags', 'kind': 'text',
         'val': ' '.join(po.extras),
         'help': 'Any extra mpv flags, e.g. --volume 80.'},
    ]
    return fields


def form_result(fields: List[Dict], opts: Dict, mpv: List[str] = None
                ) -> Optional[Tuple[Dict, List[str]]]:
    """Turn edited form fields back into the legacy (opts, mpv) pair.

    Every field spec round-trips through PlaybackOptions, so the outcome is
    exactly what setup/CLI/Simkl-sync flows expect.
    """
    by = {f['k']: f for f in fields}
    po = PlaybackOptions(opts, mpv)
    if 'quality' in by:
        po.quality = (by['quality'].get('choices')
                      or by['quality'].get('opts'))[by['quality']['i']]
    if 'audio' in by:
        po.audio = (by['audio'].get('choices')
                    or by['audio'].get('opts'))[by['audio']['i']]
    if 'eps' in by:
        e = (by['eps']['val'] or '').strip().lower()
        if e in ('', 'a', 'all'):
            po.set_all_eps(True)
            po.set_eps_selector(None)
        else:
            po.set_all_eps(False)
            po.set_eps_selector(e)
    if 'skip' in by:
        po.set_skip((by['skip'].get('choices')
                     or by['skip'].get('opts'))[by['skip']['i']])
    if 'toggle' in by:
        po.set_skip_toggle(bool(by['toggle']['val']))
    if 'next' in by:
        f = by['next']
        if f['val'] and f.get('was') and f.get('orig'):
            po.set_next(f['orig'])      # untouched + checked: exact fraction
        else:
            po.set_next(DEFAULT_NEXT if f['val'] else False)
    if 'nowait' in by:
        po.set_nowait(bool(by['nowait']['val']))
    if 'cut' in by:
        po.set_cut(by['cut']['val'])
    if 'start' in by:
        po.start = by['start']['val']
    if 'end' in by:
        po.end = by['end']['val']
    if 'sync' in by:
        po.set_sync(bool(by['sync']['val']))
    if 'full' in by or 'extra' in by:
        import shlex
        try:
            words = shlex.split(by.get('extra', {}).get('val') or '')
        except ValueError:                  # unbalanced quote: keep raw
            words = (by.get('extra', {}).get('val') or '').split()
        po.with_extras(words,
                       fullscreen=(bool(by['full']['val']) if 'full' in by
                                   else None))
    return po.to_opts(), po.mpv()
