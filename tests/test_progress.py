#!/usr/bin/env python3
"""test_progress - resume position is saved and read back correctly."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.config import Config        # noqa: E402
from tp.playlist import Playlist    # noqa: E402
from tp.cli import _resume_ep, _resume_pos  # noqa: E402


class _Dummy:
    pass


def test_progress_roundtrip():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-prog-')).ensure()
    pl = Playlist(_Dummy(), None, None, None, cfg)  # only storage is used
    pl._save('Mushen Ji', 64, 207)                  # closing mid ep64 @ 3:27
    assert pl.progress_for('Mushen Ji') == {'ep': 64, 'pos': 207}
    # the menu reads it back the same way
    assert _resume_ep(cfg, 'Mushen Ji') == 64
    assert _resume_pos(cfg, 'Mushen Ji') == 207
    # finished ep -> pointer at next, pos 0
    pl._save('Mushen Ji', 65, 0)
    assert _resume_ep(cfg, 'Mushen Ji') == 65
    assert _resume_pos(cfg, 'Mushen Ji') == 0
    print('PASS progress roundtrip + resume helpers')


def main():
    test_progress_roundtrip()
    print('PROGRESS OK')


if __name__ == '__main__':
    main()
