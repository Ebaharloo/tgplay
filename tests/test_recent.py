#!/usr/bin/env python3
"""test_recent - the 'Recently aired' rail (pure data, no Qt, no network).

PLAN-RECENT F6 cases 1-10: window, clamps, started-or-followed, new-season
flag, dedupe, sort/limit, days_ago, base-title table, posters.
Run: env -u PYTHONPATH .venv/bin/python -m pytest tests/test_recent.py -q
"""
import os
import sys
import tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tp import recent as R              # noqa: E402
from tp.config import Config, load_json  # noqa: E402


def _day(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat() + 'T00:00:00Z'


def _row(title, n=0, watched=5, total=12, next_ep=6, status='watching',
         poster='p/1', mal=1, last_watched=None, air_date='day', simkl=1):
    return {'title': title, 'simkl': simkl, 'mal': mal, 'status': status,
            'watched': watched, 'total': total, 'next_ep': next_ep,
            'air_date': _day(n) if air_date == 'day' else air_date,
            'last_watched': last_watched, 'poster': poster}


class FakeArt:
    def __init__(self):
        self.calls = []

    def covers(self, mal_ids):
        self.calls.append(list(mal_ids))
        return {m: f'https://anilist/cover{m}.jpg' for m in mal_ids}


def _cfg():
    return Config(home=tempfile.mkdtemp(prefix='tgplay-recent-')).ensure()


def _items(rows, art=None, **kw):
    return R.RecentlyAired(_cfg(), art=art or FakeArt()).items(rows, **kw)


# --- 1. window keeps only rows inside [today-days, today] -----------------
def test_1_window_keeps_three_of_five_rows():
    rows = [_row('A', 0), _row('B', 3), _row('C', 13),
            _row('D', 20), _row('E', -2)]           # E airs in the future
    got = _items(rows, days=14)
    assert [i['title'] for i in got] == ['A', 'B', 'C'], got


# --- 2. junk/0 days -> 14 -------------------------------------------------
def test_2_junk_days_falls_back_to_fourteen():
    rows = [_row('C', 13), _row('D', 20)]
    fourteen = [i['title'] for i in _items(rows, days=14)]
    assert fourteen == ['C'], fourteen
    assert [i['title'] for i in _items(rows, days=0)] == fourteen
    assert [i['title'] for i in _items(rows, days='junk')] == fourteen
    assert [i['title'] for i in _items(rows, days=99)] == fourteen


# --- 3. a started row with no/bad air date is dropped ---------------------
def test_3_started_row_without_air_date_is_dropped():
    rows = [_row('NoDate', watched=5, air_date=None),
            _row('BadDate', watched=5, air_date='not-a-date')]
    assert _items(rows) == []


# --- 4. new season of a watched show, flag on/off ------------------------
def test_4_new_season_toggle():
    rows = [_row('Dandadan', 3), _row('Dandadan Season 2', 0,
                                      watched=0, next_ep=1, status='hold')]
    known = ('Dandadan',)
    with_new = _items(rows, include_new_seasons=True, known_titles=known)
    assert [i['title'] for i in with_new] == ['Dandadan Season 2'], with_new
    assert with_new[0]['is_new_season'] is True, with_new[0]
    without = _items(rows, include_new_seasons=False, known_titles=known)
    assert [i['title'] for i in without] == ['Dandadan'], without


# --- 5. unfinished previous season: known_titles match sets the flag -----
def test_5_base_title_match_marks_new_season():
    rows = [_row('Xian Ni 2nd Season', 1, watched=0, next_ep=0,
                 status='watching')]
    got = _items(rows, known_titles=('Xian Ni',))
    assert [i['title'] for i in got] == ['Xian Ni 2nd Season'], got
    assert got[0]['is_new_season'] is True, got[0]
    assert got[0]['base'] == 'xian ni', got[0]


# --- 6. dedupe by base title, newest air date wins -----------------------
def test_6_dedupe_keeps_newest_air_date():
    rows = [_row('Renegade Immortal', 5, next_ep=3),
            _row('Renegade Immortal Part 2', 1, next_ep=1)]
    got = _items(rows)
    assert len(got) == 1, got
    assert got[0]['title'] == 'Renegade Immortal Part 2', got[0]
    assert got[0]['days_ago'] == 1, got[0]


# --- 7. sort (air_date desc, next_ep desc) + limit -----------------------
def test_7_sort_order_and_limit():
    rows = [_row('Older', 5), _row('Mid', 2),
            _row('TodayLow', 0, next_ep=2), _row('TodayHigh', 0, next_ep=9)]
    got = _items(rows, limit=3)
    assert [i['title'] for i in got] == ['TodayHigh', 'TodayLow', 'Mid'], got


# --- 8. days_ago ---------------------------------------------------------
def test_8_days_ago_today_and_n_days_back():
    got = _items([_row('Now', 0), _row('Five', 5)])
    by = {i['title']: i for i in got}
    assert by['Now']['days_ago'] == 0, by['Now']
    assert by['Five']['days_ago'] == 5, by['Five']


# --- 9. base-title normalisation table -----------------------------------
def test_9_base_title_table():
    assert R.base_title('One Piece (1999)') == 'one piece'
    assert R.base_title('One Piece Season 2') == 'one piece'
    assert R.base_title('Xian Ni 2nd Season') == 'xian ni'
    assert R.base_title('Renegade Immortal Part 2') == 'renegade immortal'
    assert R.base_title('  ') == ''


# --- 10. poster: Simkl path wins, AniList cover is the fallback ----------
def test_10_poster_simkl_then_anilist():
    art = FakeArt()
    got = _items([_row('HasPoster', poster='15/abc', mal=5),
                  _row('NoPoster', poster='', mal=7)], art=art)
    by = {i['title']: i for i in got}
    assert by['HasPoster']['image'] == (
        'https://simkl.in/posters/15/abc_m.webp'), by['HasPoster']
    assert by['NoPoster']['image'] == 'https://anilist/cover7.jpg', by['NoPoster']
    assert art.calls == [[7]], art.calls       # only ids missing a poster


# --- F0: relations drive "new season" (title match is only the fallback) ---
def test_11_relations_mark_new_season_and_nothing_else():
    watched = _row('Konosuba', 3, watched=10, total=10, next_ep=11,
                   simkl=100, mal=None, poster='')
    new = _row('Konosuba 2', 0, watched=0, next_ep=1, status='hold',
               simkl=200, mal=None, poster='')
    prequel_link = [{'relation_type': 'prequel', 'is_direct': True,
                     'ids': {'simkl': 100}}]
    # Simkl's per-show view: the new row carries a direct prequel to S1
    got = _items([watched, new], relations={200: prequel_link})
    assert 'Konosuba 2' in [i['title'] for i in got], got
    assert {i['title']: i['is_new_season'] for i in got}['Konosuba 2'] is True
    off = _items([watched, new], relations={200: prequel_link},
                 include_new_seasons=False)
    assert 'Konosuba 2' not in [i['title'] for i in off], off

    # same fact seen from the watched show: a direct sequel
    sequel_link = {100: [{'relation_type': 'sequel', 'is_direct': True,
                          'ids': {'simkl': 200}}]}
    got2 = _items([watched, new], relations=sequel_link)
    assert 'Konosuba 2' in [i['title'] for i in got2], got2

    # a prequel/side story of a watched show is NOT a new season
    not_new = {100: [{'relation_type': 'prequel', 'is_direct': True,
                      'ids': {'simkl': 200}},
                     {'relation_type': 'side_story', 'is_direct': True,
                      'ids': {'simkl': 200}}]}
    got3 = _items([watched, new], relations=not_new)
    assert [i['title'] for i in got3] == ['Konosuba'], got3
    assert got3[0]['is_new_season'] is False, got3[0]


# --- F0: episodes give the real air date and how far behind he is --------
def test_12_episodes_newest_air_and_behind():
    row = _row('Weekly', 9, watched=7, total=12, next_ep=8,
               simkl=300, mal=None, poster='')
    eps = {300: [{'episode': 7, 'date': _day(16), 'aired': True},
                 {'episode': 8, 'date': _day(9), 'aired': True},
                 {'episode': 9, 'date': _day(0), 'aired': True},
                 {'episode': 10, 'date': _day(-7), 'aired': False}]}
    # row.air_date is 9 days old (outside days=7); the newest AIRED episode
    # is today, so the show belongs to the 7-day window with behind = 9-7
    assert _items([row], days=7) == []           # no episodes map: fallback
    got = _items([row], days=7, episodes=eps)
    assert [i['title'] for i in got] == ['Weekly'], got
    assert got[0]['days_ago'] == 0 and got[0]['behind'] == 2, got[0]
    assert got[0]['air_date'] == _day(0)[:10], got[0]


# --- F0: relations/episodes cache honours the TTL, never raises ----------
class _FakeAcc:
    def __init__(self):
        self.calls = []

    def _api(self, path, params=None, method='GET', body=None):
        self.calls.append(path)
        if path.startswith('/anime/episodes/'):
            return [{'episode': 1, 'date': _day(0), 'aired': True}]
        return {'relations': [{'relation_type': 'sequel', 'is_direct': True,
                               'ids': {'simkl': 2}}]}


def test_13_extra_cache_ttl_and_failures(tmp_path):
    from tp.simkl_extra import EPISODES_TTL, SimklExtra
    from tp.config import save_json as _save
    cfg = Config(home=str(tmp_path)).ensure()
    acc = _FakeAcc()
    ex = SimklExtra(cfg, acc=acc)
    assert ex.relations(42)[0]['relation_type'] == 'sequel'
    assert ex.episodes(42)[0]['episode'] == 1
    assert len(acc.calls) == 2, acc.calls
    ex.relations(42)                              # cached: no new calls
    ex.episodes(42)
    assert len(acc.calls) == 2, acc.calls

    saved = load_json(cfg.episodes)               # age the episodes entry
    saved['42']['fetched'] -= EPISODES_TTL + 1
    _save(cfg.episodes, saved)
    ex.episodes(42)
    assert len(acc.calls) == 3 and acc.calls[-1].startswith('/anime/episodes/')

    class Boom(_FakeAcc):
        def _api(self, *a, **k):
            raise RuntimeError('api down')

    fresh = SimklExtra(Config(home=str(tmp_path / 'b')).ensure(), acc=Boom())
    assert fresh.relations(7) == [] and fresh.episodes(7) == []


# --- F3: settings live in ui.json and are clamped ------------------------
def test_settings_roundtrip_is_clamped():
    from tp.config import save_json
    cfg = _cfg()
    assert R.load_rails(cfg) == R.DEFAULT_RAILS
    saved = R.save_rails(cfg, {'recent': {'days': 99, 'limit': 999},
                               'sidebar': {'show_days': False, 'days': 0}})
    assert saved['recent']['days'] == 14, saved
    assert saved['recent']['limit'] == 50, saved
    assert saved['sidebar']['show_days'] is False, saved
    assert saved['sidebar']['days'] == 14, saved
    assert load_json(cfg.ui)['window']['rails'] == saved
    # split keeps its place next to rails
    save_json(cfg.ui, dict(load_json(cfg.ui),
                           window={'split': [900, 320], 'rails': saved}))
    R.save_rails(cfg, saved)
    win = load_json(cfg.ui)['window']
    assert win['split'] == [900, 320] and 'rails' in win, win
