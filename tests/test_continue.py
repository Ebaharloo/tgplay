#!/usr/bin/env python3
"""test_continue - the Continue-watching shelf (data + widget, no network).

Data: in-progress filtering, dedupe, newest-first order, poster URL forms,
AniList cover fallback, percentage.
Widget: cards render, click fires the resume callback, posters set, collapse.
Run: .venv/bin/python tests/test_continue.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import continuewatch as cw   # noqa: E402
from tp import history               # noqa: E402
from tp.config import Config         # noqa: E402

REM = [
    {'title': 'One Piece', 'next_ep': 518, 'watched': 517, 'total': 1184,
     'last_watched': '2026-10-20T10:00:00Z', 'poster': '15/1511453300c778c741',
     'mal': 21, 'simkl': 38636},
    {'title': 'KonoSuba', 'next_ep': 8, 'watched': 7, 'total': 10,
     'last_watched': '2026-10-21T09:00:00Z', 'poster': '',
     'mal': 30831, 'simkl': 1},
    {'title': 'One Piece', 'next_ep': 518, 'watched': 517, 'total': 1184,
     'last_watched': '2026-10-19T10:00:00Z', 'poster': '15/1511453300c778c741',
     'mal': 21, 'simkl': 38636},                       # split entry: dedupe
    {'title': 'Finished Show', 'next_ep': 13, 'watched': 12, 'total': 12,
     'last_watched': '2026-10-22T00:00:00Z', 'poster': '', 'mal': 5},
    {'title': 'Not Started', 'next_ep': 1, 'watched': 0, 'total': 12,
     'last_watched': '2026-10-22T00:00:00Z', 'poster': '', 'mal': 6},
]


class FakeArt:
    def covers(self, mal_ids):
        return {30831: 'https://anilist/cover.jpg'} if 30831 in mal_ids else {}


def test_items():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-cont-')).ensure()
    cw_ = cw.ContinueWatching(cfg, http=None, art=FakeArt())
    items = cw_.items(REM)
    assert [i['title'] for i in items] == ['KonoSuba', 'One Piece'], items
    k, op = items
    assert k['next_ep'] == 8 and k['pct'] == 70.0, k
    assert k['image'] == 'https://anilist/cover.jpg', k       # cover fallback
    assert op['image'] == ('https://simkl.in/posters/15/'
                           '1511453300c778c741_m.webp'), op   # simkl poster
    assert abs(op['pct'] - 43.7) < 0.1, op
    assert items[0]['mal'] == 30831 and items[0]['simkl'] == 1
    print('PASS shelf items: filter/dedupe/order/posters/pct')


def test_last_link_for_resume():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-cont-')).ensure()
    history.add(cfg, link='axp:old', name='One Piece')
    history.add(cfg, link='agp:new', name='ONE PIECE')
    history.add(cfg, link='axp:other', name='Other Show')
    assert history.last_link_for(cfg, 'One Piece') == 'agp:new'
    assert history.last_link_for(cfg, 'missing') is None
    print('PASS resume link: newest link for a show name')


def test_shelf_widget():
    from PySide6 import QtWidgets, QtCore, QtGui  # noqa: F401
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from tp.gui_qt import _app as qt_app
    qt_app()
    from tp.gui_all import ContinueShelf
    clicked = {}
    shelf = ContinueShelf(lambda it: clicked.setdefault('item', it),
                          lambda it, pos: None)
    items = [{'title': 'KonoSuba', 'next_ep': 8, 'watched': 7, 'total': 10,
              'pct': 70.0, 'image': 'u1'},
             {'title': 'One Piece', 'next_ep': 518, 'watched': 517,
              'total': 1184, 'pct': 43.7, 'image': 'u2'}]
    shelf.show()
    shelf.set_items(items)
    assert not shelf.isHidden(), 'populated shelf must be visible'
    shelf.sync(results_visible=True)
    assert not shelf.isHidden(), 'app state must never hide the shelf'
    assert shelf.count.text() == '2', shelf.count.text()
    assert 'in progress' in shelf.count.toolTip(), shelf.count.toolTip()
    card = shelf.row.itemAt(0).widget()
    assert card is not None and card.item['title'] == 'KonoSuba'
    ev = QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonPress, QtCore.QPointF(5, 5),
        QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
    card.mousePressEvent(ev)
    assert clicked['item']['title'] == 'KonoSuba', clicked
    pm = QtGui.QPixmap(300, 450)
    pm.fill(QtGui.QColor('#123456'))
    shelf.set_poster('u1', pm)
    shown = card.poster.pixmap()
    assert shown is not None, 'poster must be set'
    # scale-CROP to fill the label (QLabel would centre-clip a big pixmap)
    assert (shown.width(), shown.height()) == (
        card.poster.width(), card.poster.height()), shown.size()
    shelf._toggle()                                   # collapse
    assert not shelf.scroll.isVisible(), 'collapse hides the rail only'
    assert not shelf.isHidden(), 'collapsed shelf keeps its slot'
    shelf._toggle()
    shelf.set_items([])                               # empty keeps the slot
    assert not shelf.isHidden(), 'empty shelf keeps its slot'
    assert not shelf.scroll.isHidden(), 'empty shelf shows the rail again'
    print('PASS shelf widget: cards, click, poster, collapse, empty')


def main():
    test_items()
    test_last_link_for_resume()
    test_shelf_widget()
    print('CONTINUE OK')


if __name__ == '__main__':
    main()
