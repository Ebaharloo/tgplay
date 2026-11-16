#!/usr/bin/env python3
"""test_theme - own test model for the dark look (tp.theme).

The window's whole look is one stylesheet and one palette; a broken format string
(an f-string brace left unexpanded) or a palette colour that no longer matches the
sheet shows up here instead of on the phone-sized window.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import theme  # noqa: E402

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def test_qss_is_fully_expanded():
    assert '{BG}' not in theme.QSS and '{PANEL}' not in theme.QSS and '{TEXT}' not in theme.QSS
    assert theme.PANEL in theme.QSS and theme.EDGE in theme.QSS
    # selectors the window actually relies on
    for sel in ('QPushButton', 'QLineEdit', 'QComboBox', 'QListWidget',
                'QHeaderView::section', 'QScrollBar:vertical', 'QTabBar::tab'):
        assert sel in theme.QSS, sel


def test_palette_matches_the_sheet():
    p = theme.palette()
    from PySide6 import QtGui as G
    assert p.color(G.QPalette.Window).name() == theme.BG
    assert p.color(G.QPalette.Base).name() == theme.PANEL
    assert p.color(G.QPalette.ButtonText).name() == theme.TEXT


def test_apply_sets_the_stylesheet_and_is_idempotent():
    from PySide6 import QtWidgets as W
    app = W.QApplication.instance() or W.QApplication([])
    theme.apply(app)
    assert app.styleSheet() == theme.QSS
    theme.apply(app)                       # safe to call twice
    assert app.styleSheet() == theme.QSS


if __name__ == '__main__':
    raise SystemExit(__import__('pytest').main([__file__, '-q']))
