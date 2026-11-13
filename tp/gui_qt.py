"""tp.gui_qt - shared Qt (PySide6) helpers + the URL picker dialog.

The per-source Qt window (controller) is retired: every GUI now routes through
the unified window (tp/gui_all.UnifiedWindow). What stays here is what the
rest of the app still needs: `available()` test, the shared `_app()` /
application icon helpers used by gui_all, and the `choose_url()` picker.
"""
import os
import queue
import threading
from typing import List, Optional


def available() -> bool:
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return False
    try:
        import PySide6  # noqa: F401
        return True
    except Exception:
        return False


def _app():
    from PySide6 import QtWidgets as W, QtGui as G
    app = W.QApplication.instance()
    if app is None:
        app = W.QApplication([])
    app.setApplicationName('tgplay')
    app.setApplicationDisplayName('tgplay')
    try:
        app.setDesktopFileName('tgplay')   # taskbar/dock grouping on Wayland
    except Exception:
        pass
    ic = _app_icon(G)
    if ic is not None:
        app.setWindowIcon(ic)
    try:
        from . import theme
        theme.apply(app)
    except Exception:
        pass                       # a theme failure must never block the GUI
    return app


def _app_icon(G):
    try:
        from . import icon as _icon
        p = _icon.png(256)
        if p and os.path.exists(p):
            return G.QIcon(p)
    except Exception:
        pass
    return None


def choose_url(recent: List[str], search_fn=None) -> Optional[str]:
    """Pick a recent link, search (when `search_fn(query)` is given), or paste
    a link. `search_fn` returns ``[{'title','url','source'}]``."""
    from PySide6 import QtWidgets as W, QtCore as C, QtGui as G
    res: dict = {}
    recents = list(dict.fromkeys(recent))[:15]

    win = W.QDialog()
    win.setWindowTitle('tgplay - which anime?')
    win.resize(760, 540)
    _wi = _app_icon(G)
    if _wi is not None:
        win.setWindowIcon(_wi)
    v = W.QVBoxLayout(win)
    lbl = W.QLabel('Which anime do you want to watch?')
    f = lbl.font(); f.setPointSize(f.pointSize() + 1); lbl.setFont(f)
    v.addWidget(lbl)

    box = W.QLineEdit()
    box.setPlaceholderText('Search anime…' if search_fn
                           else 'Paste an anime link…')
    box.setClearButtonEnabled(True)
    v.addWidget(box)

    status = W.QLabel('')
    v.addWidget(status)

    lst = W.QListWidget()
    lst.setAlternatingRowColors(True)
    v.addWidget(lst, 1)

    def fill(entries):
        lst.clear()
        for e in entries:
            if isinstance(e, dict):
                it = W.QListWidgetItem(
                    f"{e.get('title', '')}     ·     {e.get('source', '')}")
                it.setData(C.Qt.UserRole, e.get('url'))
            else:
                it = W.QListWidgetItem(str(e))
                it.setData(C.Qt.UserRole, str(e))
            lst.addItem(it)
        if lst.count():
            lst.setCurrentRow(0)

    def show_recents():
        fill(recents)
        status.setText(f'{len(recents)} recent' if recents else 'type to search')

    show_recents()

    results: 'queue.Queue' = queue.Queue()

    def run_search(text):
        def work():
            try:
                results.put(search_fn(text) or [])
            except Exception:
                results.put([])
        threading.Thread(target=work, daemon=True).start()

    debounce = C.QTimer()
    debounce.setSingleShot(True)
    debounce.setInterval(350)
    poll = C.QTimer()
    poll.setInterval(150)

    def on_text():
        t = box.text().strip()
        if not t:
            show_recents()
            return
        if '://' in t or t.lower().startswith('axp:'):
            fill([t])
            status.setText('press OK to use this link')
            return
        if search_fn:
            status.setText('searching…')
            debounce.start()

    def drain():
        try:
            items = results.get_nowait()
        except queue.Empty:
            return
        fill(items)
        status.setText(f'{len(items)} result(s)' if items else 'no results')

    box.textChanged.connect(on_text)
    debounce.timeout.connect(lambda: run_search(box.text().strip()))
    poll.timeout.connect(drain)
    poll.start()

    def ok():
        it = lst.currentItem()
        if it is not None and it.data(C.Qt.UserRole):
            res['url'] = str(it.data(C.Qt.UserRole))
        else:
            t = box.text().strip()
            if '://' in t or t.lower().startswith('axp:'):
                res['url'] = t
        if 'url' in res:
            win.accept()
        else:                        # no result yet -> don't close
            status.setText('no result yet — press Cancel to close')

    def cleanup(*_):
        for t in (debounce, poll):
            try:
                t.stop()
            except Exception:
                pass

    lst.itemDoubleClicked.connect(lambda _i: ok())
    box.returnPressed.connect(ok)
    win.destroyed.connect(cleanup)

    bar = W.QHBoxLayout()
    b_ok = W.QPushButton('OK'); b_ok.clicked.connect(ok)
    b_cancel = W.QPushButton('Cancel'); b_cancel.clicked.connect(win.reject)
    bar.addWidget(b_ok)
    bar.addStretch(1)
    bar.addWidget(b_cancel)
    v.addLayout(bar)

    box.setFocus()
    try:
        win.raise_()
        win.activateWindow()
    except Exception:
        pass
    win.exec()
    return res.get('url')
