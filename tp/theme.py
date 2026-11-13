"""tp.theme - one dark look for the Qt window.

The window shipped with Qt's default Fusion look: square buttons, hard borders,
list rows with no hover. This module sets a small palette plus a stylesheet so
controls get rounded corners, soft hover tints and a slimmer scrollbar. Inline
`setStyleSheet` calls in gui_all still win for the widgets that use them.
"""
from PySide6 import QtGui as G
from PySide6 import QtWidgets as W

BG = '#17191c'
PANEL = '#1f2327'
TEXT = '#d7dbdf'
DIM = '#8b9299'
EDGE = '#2c3238'
HOVER = '#2b3137'

QSS = f"""
QPushButton, QToolButton {{
    background: {PANEL}; color: {TEXT}; border: 1px solid {EDGE};
    border-radius: 6px; padding: 5px 11px;
}}
QPushButton:hover, QToolButton:hover {{ background: {HOVER}; }}
QPushButton:pressed, QToolButton:pressed {{ background: #23282d; }}
QPushButton:disabled {{ color: {DIM}; background: #1b1e21; }}
QLineEdit, QSpinBox {{
    background: {PANEL}; color: {TEXT}; border: 1px solid {EDGE};
    border-radius: 6px; padding: 4px 8px; selection-background-color: #3a6ea5;
}}
QComboBox {{
    background: {PANEL}; color: {TEXT}; border: 1px solid {EDGE};
    border-radius: 6px; padding: 4px 4px 4px 7px;
    selection-background-color: #3a6ea5;
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid #3a6ea5; }}
QComboBox QAbstractItemView {{
    background: {PANEL}; color: {TEXT}; border: 1px solid {EDGE};
    selection-background-color: {HOVER};
}}
QListWidget, QTableWidget, QTreeWidget, QListView {{
    background: {PANEL}; color: {TEXT}; border: 1px solid {EDGE};
    border-radius: 6px; outline: 0;
}}
QListWidget::item, QTreeWidget::item, QTableWidget::item {{ padding: 3px 4px; }}
QListWidget::item:selected, QTreeWidget::item:selected,
QTableWidget::item:selected {{ background: #2f4a63; color: #ffffff; }}
QHeaderView::section {{
    background: #1b1e21; color: {DIM}; border: 0;
    border-bottom: 1px solid {EDGE}; padding: 3px 4px;
}}
QCheckBox {{ color: {TEXT}; spacing: 6px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border-radius: 3px;
    border: 1px solid #454d55; background: {PANEL};
}}
QCheckBox::indicator:hover {{ border-color: #3a6ea5; }}
QCheckBox::indicator:checked {{ background: #3a6ea5; border-color: #3a6ea5; }}
QCheckBox::indicator:disabled {{ border-color: #2c3238; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #3a4148; border-radius: 5px;
    min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #4a535b; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #3a4148; border-radius: 5px;
    min-width: 24px; }}
QSplitter::handle {{ background: {EDGE}; }}
QTabBar::tab {{ background: {PANEL}; color: {DIM}; padding: 4px 10px;
    border-radius: 6px; margin-right: 4px; }}
QTabBar::tab:selected {{ background: {HOVER}; color: {TEXT}; }}
"""


def palette() -> 'G.QPalette':
    p = G.QPalette()
    p.setColor(G.QPalette.Window, G.QColor(BG))
    p.setColor(G.QPalette.WindowText, G.QColor(TEXT))
    p.setColor(G.QPalette.Base, G.QColor(PANEL))
    p.setColor(G.QPalette.AlternateBase, G.QColor('#23282d'))
    p.setColor(G.QPalette.Text, G.QColor(TEXT))
    p.setColor(G.QPalette.Button, G.QColor(PANEL))
    p.setColor(G.QPalette.ButtonText, G.QColor(TEXT))
    p.setColor(G.QPalette.Highlight, G.QColor('#2f4a63'))
    p.setColor(G.QPalette.HighlightedText, G.QColor('#ffffff'))
    p.setColor(G.QPalette.ToolTipBase, G.QColor(PANEL))
    p.setColor(G.QPalette.ToolTipText, G.QColor(TEXT))
    p.setColor(G.QPalette.Disabled, G.QPalette.ButtonText, G.QColor(DIM))
    return p


def apply(app: 'W.QApplication') -> None:
    """Dark rounded controls. Safe to call twice."""
    app.setStyle('Fusion')
    app.setPalette(palette())
    app.setStyleSheet(QSS)
