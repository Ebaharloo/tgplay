"""Local watched store: tombstones + the progress facade."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tp.tracking.local_store import LocalStore, key_for        # noqa: E402
from tracking_fakes import Cfg                                 # noqa: E402


def test_key_prefers_simkl_then_mal_then_title():
    assert key_for('X', {'simkl': 7, 'mal': 21}) == 'simkl:7'
    assert key_for('X', {'mal': 21}) == 'mal:21'
    assert key_for('Xian Ni!', None) == 't:xianni'


def test_unmark_leaves_a_tombstone_and_a_remark_clears_it(tmp_path):
    cfg = Cfg(tmp_path)
    st = LocalStore(cfg)
    st.set_episode('mal:21', 2, True)
    st.set_episode('mal:21', 2, False)
    s = st.state('mal:21')
    assert 2 not in s['eps'] and 2 in s['tomb']

    st.set_episode('mal:21', 2, True)
    s = st.state('mal:21')
    assert 2 in s['eps'] and 2 not in s['tomb']


def test_season_unwatch_tombstones_every_episode(tmp_path):
    st = LocalStore(Cfg(tmp_path))
    st.set_season('mal:21', [1, 2, 3], True)
    st.set_season('mal:21', [1, 2, 3], False)
    s = st.state('mal:21')
    assert s['eps'] == set() and set(s['tomb']) == {1, 2, 3}


def test_tombstones_survive_a_reload(tmp_path):
    cfg = Cfg(tmp_path)
    LocalStore(cfg).set_episode('t:x', 4, False)
    assert 4 in LocalStore(cfg).state('t:x')['tomb']


def test_progress_is_one_facade(tmp_path):
    cfg = Cfg(tmp_path)
    st = LocalStore(cfg)
    st.save_progress('Xian Ni', 4, 120)
    assert st.entry('Xian Ni') == {'ep': 4, 'pos': 120.0}
    assert st.clear_progress('Xian Ni') is True
    assert st.entry('Xian Ni') == {}
