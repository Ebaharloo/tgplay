"""Playlist._title: MPRIS/media-widget title picks the real episode name."""
import json

from tp.episodes import Episode
from tp.playlist import Playlist


class _Cfg:
    def __init__(self, d):
        self.ep_titles = d + '/ep_titles.json'
        self.translations = d + '/missing.json'


class _Prov:
    title = 'One Piece'


def _pl(tmp_path, mal_id):
    p = tmp_path / 'ep_titles.json'
    p.write_text(json.dumps({'21': {'1085': 'The Final Lesson'}}))
    pl = object.__new__(Playlist)
    pl.cfg, pl.provider, pl.mal_id = _Cfg(str(tmp_path)), _Prov(), mal_id
    return pl


def test_title_uses_cached_episode_name(tmp_path):
    assert _pl(tmp_path, 21)._title(Episode(1085, ''), 'file.mkv') \
        == 'One Piece - Ep 1085 - The Final Lesson'


def test_title_falls_back_to_file_name(tmp_path):
    pl = _pl(tmp_path, 21)
    assert pl._title(Episode(9, ''), 'file.mkv') == 'file.mkv'   # ep not cached
    pl.mal_id = None                                     # no pinned show
    assert pl._title(Episode(1085, ''), 'file.mkv') == 'file.mkv'
