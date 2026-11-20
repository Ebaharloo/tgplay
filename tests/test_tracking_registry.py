"""Registry shape, the one-policy-per-feature rule, and the hygiene gates."""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from tp.tracking import POLICY, REGISTRY, FanoutSync, Tracking, get  # noqa: E402


def test_registry_names_one_class_per_service():
    assert set(REGISTRY) == {'watched', 'lists', 'ratings', 'scrobble',
                             'resume', 'calendar', 'history', 'cast'}
    assert get('simkl', 'watched').__name__ == 'SimklWatched'
    assert get('anilist', 'watched').__name__ == 'AniListWatched'
    assert get('local', 'watched').__name__ == 'LocalWatched'
    assert get('anilist', 'scrobble') is None      # Simkl is the scrobbler


def test_one_policy_per_feature():
    assert POLICY['watched'] == 'all'              # history -> every service
    assert POLICY['scrobble'] == 'first'           # one position, one writer


class _Svc:
    def __init__(self, name, fail=False):
        self.name, self.fail, self.calls = name, fail, []

    def enabled(self):
        return True

    def mark(self, n):
        if self.fail:
            raise RuntimeError('boom')
        self.calls.append(n)
        return self.name


def test_fanout_all_vs_first():
    a, b = _Svc('a'), _Svc('b')
    FanoutSync('watched', [a, b])('mark', 1)
    assert a.calls == [1] and b.calls == [1]
    a, b = _Svc('a'), _Svc('b')
    FanoutSync('scrobble', [a, b])('mark', 1)
    assert a.calls == [1] and b.calls == []
    a, b = _Svc('a', fail=True), _Svc('b', fail=True)
    assert FanoutSync('watched', [a, b])('mark', 1) == []   # failures logged


def test_gui_never_constructs_a_client_directly():
    src = open(os.path.join(ROOT, 'tp', 'gui_all.py')).read()
    assert 'SimklAccount(' not in src
    assert 'from .simkl_account import SimklAccount' not in src


def test_one_activities_stamp_file():
    acc = open(os.path.join(ROOT, 'tp', 'simkl_account.py')).read()
    cfg = open(os.path.join(ROOT, 'tp', 'config.py')).read()
    library = acc[acc.index('def library('):]
    assert 'cfg.simkl_activities' in library
    assert 'simkl_library' not in cfg          # the second stamp file is gone
    # and the pull gate uses the same file
    watched = open(os.path.join(ROOT, 'tp', 'tracking', 'watched.py')).read()
    assert 'cfg.simkl_activities' in watched


def test_tracking_facade_builds_every_feature(tmp_path):
    from tracking_fakes import Cfg
    t = Tracking(Cfg(tmp_path))
    assert set(t.features) == set(REGISTRY)
    assert t.watched.services                      # local always present
    t.stop()
