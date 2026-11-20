"""Resume: cross-device read, clear, and the cached list."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tp.tracking.resume import ResumeSync                         # noqa: E402
from tracking_fakes import FakeSimkl                              # noqa: E402


def test_read_finds_the_episode_by_any_id():
    simkl = FakeSimkl()
    simkl.playbacks = [{'id': 900, 'simkl': 7, 'mal': 21, 'anilist': None,
                        'season': 1, 'episode': 3, 'progress': 42.5}]
    rs = ResumeSync(simkl)
    assert rs.read(3, {'mal': 21}) == {'percent': 42.5, 'id': 900}
    assert rs.read(4, {'mal': 21}) is None


def test_clear_deletes_once_and_drops_the_cache():
    simkl = FakeSimkl()
    simkl.playbacks = [{'id': 900, 'simkl': 7, 'mal': 21,
                        'episode': 3, 'progress': 42.5}]
    rs = ResumeSync(simkl)
    assert rs.clear(3, {'simkl': 7}) is True
    assert ('clear_playback', (900,)) in simkl.calls
    assert rs.read(3, {'simkl': 7}) is None
    assert rs.clear(3, {'simkl': 7}) is False       # already gone: no 2nd call


def test_logged_out_has_no_points():
    simkl = FakeSimkl()
    simkl.logged_in = lambda: False
    assert ResumeSync(simkl).read(1, {'mal': 1}) is None
