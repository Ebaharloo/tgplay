"""tp.gui_qt - native desktop controller built on Qt (PySide6).

Same interface as tp.gui (available / controller / choose_url), but on KDE
Plasma a Qt app follows the desktop's Breeze colour scheme, widget style and
icons automatically - no hand-picked colours. Falls back to nothing special on
other desktops, where Qt still looks consistent.

Play runs in a background thread, so the window stays open: pick other
episodes, change the setup, Stop, and the anime's Simkl/MAL link is clickable.
Log lines from tp.log are mirrored into an in-window panel.
"""
import os
import queue
import threading
from typing import Callable, Dict, List, Optional

SKIP_MODES = ['off', 'all', 'names', 'auto']


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


def controller(title: str, link: Optional[str], groups: List[dict],
               labels: Dict[int, str], resume: Optional[int], opts: dict,
               mpv: List[str], play_fn: Callable, stop_fn=None, status_fn=None,
               one_shot: bool = False, audio: bool = False):
    """Open the window and keep it until the user closes it (or, with
    `one_shot`, until the first Play). `play_fn(chosen, opts, mpv)` runs in a
    background thread."""
    from PySide6 import QtWidgets as W, QtCore as C, QtGui as G
    from . import log as _log

    app = _app()
    nums = sorted(labels)
    state = {'closing': False, 'msg': ''}
    q: 'queue.Queue' = queue.Queue()
    prev_sink = _log.SINK
    _log.SINK = lambda s: q.put(str(s))

    win = W.QWidget()
    win.setWindowTitle('tgplay')
    win.resize(860, 760)
    _wi = _app_icon(G)
    if _wi is not None:
        win.setWindowIcon(_wi)
    root = W.QVBoxLayout(win)
    root.setContentsMargins(12, 10, 12, 10)
    root.setSpacing(8)

    head = W.QLabel(f'<b>{title}</b>')
    hf = head.font(); hf.setPointSize(hf.pointSize() + 2); head.setFont(hf)
    root.addWidget(head)
    if link:
        lb = W.QLabel(f'<a href="{link}">{link}</a>')
        lb.setOpenExternalLinks(True)
        lb.setTextInteractionFlags(C.Qt.TextBrowserInteraction)
        root.addWidget(lb)

    # --- options -------------------------------------------------------
    box = W.QGroupBox('Options')
    form = W.QGridLayout(box)
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(4)

    glabels = [str(g['label']) for g in groups]
    quality = W.QComboBox()
    quality.addItems(glabels)
    quality.setEditable(False)
    if glabels:
        want = next((l for l in glabels
                     if opts.get('f') and str(opts['f']).lower() in l.lower()),
                    glabels[0])
        quality.setCurrentText(want)

    audio_box = None
    if audio:
        audio_box = W.QComboBox()
        audio_box.addItems(['dub', 'sub', 'auto'])
        audio_box.setEditable(False)
        audio_box.setCurrentText(opts.get('audio')
                                 if opts.get('audio') in ('dub', 'sub', 'auto')
                                 else 'dub')

    skip = W.QComboBox()
    skip.addItems(SKIP_MODES)
    skip.setEditable(False)
    skip.setCurrentText(opts.get('skip') if isinstance(opts.get('skip'), str)
                        else ('all' if opts.get('skip') else 'off'))
    toggle = W.QCheckBox('toggle key T')
    toggle.setChecked(bool(opts.get('skip_toggle')))
    full = W.QCheckBox('fullscreen')
    full.setChecked('--fullscreen' in mpv)

    r = 0
    if glabels:
        form.addWidget(W.QLabel('Server' if audio else 'Quality'), r, 0)
        form.addWidget(quality, r, 1, 1, 3)
        r += 1
    if audio_box is not None:
        form.addWidget(W.QLabel('Audio'), r, 0)
        form.addWidget(audio_box, r, 1, 1, 3)
        r += 1
    form.addWidget(W.QLabel('Skip'), r, 0)
    form.addWidget(skip, r, 1)
    form.addWidget(toggle, r, 2)
    form.addWidget(full, r, 3)
    r += 1

    nxt = W.QCheckBox('Pre-download next episode')
    nxt.setChecked(bool(opts.get('next')))
    nowait = W.QCheckBox('start it at cut point')
    nowait.setChecked(bool(opts.get('nowait')))
    form.addWidget(nxt, r, 0, 1, 2)
    form.addWidget(nowait, r, 2, 1, 2)
    r += 1

    cut = W.QLineEdit(str(opts.get('cut') or ''))
    cut.setFixedWidth(70)
    extra = W.QLineEdit(' '.join(x for x in mpv if x != '--fullscreen'))
    form.addWidget(W.QLabel('Cut last N s'), r, 0)
    form.addWidget(cut, r, 1)
    form.addWidget(W.QLabel('Extra mpv flags'), r, 2)
    form.addWidget(extra, r, 3)
    root.addWidget(box)

    # --- episodes ------------------------------------------------------
    ebox = W.QGroupBox(f'Episodes ({len(nums)})')
    ev = W.QVBoxLayout(ebox)
    table = W.QTableWidget(len(nums), 2)
    table.setHorizontalHeaderLabels(['#', 'Episode name'])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
    table.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    for i, n in enumerate(nums):
        it0 = W.QTableWidgetItem(str(n))
        it0.setData(C.Qt.UserRole, n)
        it0.setTextAlignment(C.Qt.AlignRight | C.Qt.AlignVCenter)
        table.setItem(i, 0, it0)
        table.setItem(i, 1, W.QTableWidgetItem(labels.get(n, f'Episode {n}')))
    hdr = table.horizontalHeader()
    hdr.setSectionResizeMode(0, W.QHeaderView.ResizeToContents)
    hdr.setSectionResizeMode(1, W.QHeaderView.Stretch)
    ev.addWidget(table)
    root.addWidget(ebox, 1)

    if resume in labels:
        row = nums.index(resume)
        table.selectRow(row)
        table.setCurrentCell(row, 1)
        table.scrollToItem(table.item(row, 1))

    status = W.QLabel('idle')
    root.addWidget(status)

    # --- log panel -----------------------------------------------------
    lbox = W.QGroupBox('Log')
    lv = W.QVBoxLayout(lbox)
    logbox = W.QPlainTextEdit()
    logbox.setReadOnly(True)
    logbox.setMaximumBlockCount(2000)
    logbox.setFixedHeight(150)
    mono = G.QFontDatabase.systemFont(G.QFontDatabase.FixedFont)
    logbox.setFont(mono)
    lv.addWidget(logbox)
    if _log.HISTORY:
        logbox.setPlainText('\n'.join(list(_log.HISTORY)))
        logbox.verticalScrollBar().setValue(
            logbox.verticalScrollBar().maximum())
    root.addWidget(lbox)

    # --- behaviour -----------------------------------------------------
    def current_sel() -> List[int]:
        rows = sorted({i.row() for i in table.selectedIndexes()})
        return [nums[r] for r in rows]

    def focus_num() -> Optional[int]:
        r = table.currentRow()
        return nums[r] if 0 <= r < len(nums) else None

    def apply_opts():
        o = dict(opts)
        if glabels:
            o['f'] = quality.currentText()
        if audio_box is not None:
            o['audio'] = audio_box.currentText()
        sm = skip.currentText()
        o['skip'] = False if sm == 'off' else sm
        o['skip_toggle'] = bool(toggle.isChecked())
        o['next'] = 0.60 if nxt.isChecked() else False
        o['nowait'] = bool(nowait.isChecked())
        c = cut.text().strip()
        o['cut'] = int(c) if c.isdigit() else None
        flags = extra.text().split()
        if full.isChecked() and '--fullscreen' not in flags:
            flags.append('--fullscreen')
        return o, flags

    def play(chosen: List[int]):
        if play_fn is None or not chosen:
            return
        o, flags = apply_opts()
        state['msg'] = 'starting…'
        if one_shot:
            play_fn(chosen, o, flags)
            do_close()
            return

        def run():
            try:
                play_fn(chosen, o, flags)
                state['msg'] = ''
            except Exception as ex:
                state['msg'] = f'error: {ex}'
        threading.Thread(target=run, daemon=True).start()

    def from_here():
        f = focus_num()
        if f is not None:
            play([n for n in nums if n >= f])

    def only_sel():
        s = current_sel()
        f = focus_num()
        play(s if s else ([f] if f is not None else nums))

    def do_all():
        play(nums)

    def do_stop():
        if stop_fn:
            try:
                stop_fn()
            except Exception:
                pass
        state['msg'] = 'stopped'

    def do_close():
        state['closing'] = True
        try:
            _log.SINK = prev_sink
        except Exception:
            pass
        win.close()

    table.doubleClicked.connect(lambda _i: from_here())

    bar = W.QHBoxLayout()
    b_from = W.QPushButton('▶  Play from here')
    b_sel = W.QPushButton('▶  Only selected')
    b_all = W.QPushButton('▶  All')
    b_stop = W.QPushButton('■  Stop')
    b_close = W.QPushButton('Close')
    b_from.clicked.connect(from_here)
    b_sel.clicked.connect(only_sel)
    b_all.clicked.connect(do_all)
    b_stop.clicked.connect(do_stop)
    b_close.clicked.connect(do_close)
    for b in (b_from, b_sel, b_all, b_stop):
        bar.addWidget(b)
    bar.addStretch(1)
    bar.addWidget(b_close)
    root.addLayout(bar)

    def refresh_status():
        if state['closing']:
            return
        txt = ''
        if status_fn:
            try:
                txt = status_fn() or ''
            except Exception:
                txt = ''
        if state.get('msg'):
            txt = state['msg']
        status.setText(txt or 'idle')

    def drain():
        if state['closing']:
            return
        lines = []
        while True:
            try:
                lines.append(q.get_nowait())
            except queue.Empty:
                break
        if lines:
            logbox.appendPlainText('\n'.join(lines))
            logbox.verticalScrollBar().setValue(
                logbox.verticalScrollBar().maximum())

    status_timer = C.QTimer()
    status_timer.timeout.connect(refresh_status)
    status_timer.start(1000)
    log_timer = C.QTimer()
    log_timer.timeout.connect(drain)
    log_timer.start(250)

    def _cleanup(*_):
        for t in (status_timer, log_timer):
            try:
                t.stop()
            except Exception:
                pass
    win.destroyed.connect(_cleanup)

    win.show()
    try:
        win.raise_()
        win.activateWindow()
    except Exception:
        pass

    mode = os.environ.get('AGP_GUI_TEST')   # test hook
    if mode == 'play':
        C.QTimer.singleShot(300, from_here)
    elif mode == 'all':
        C.QTimer.singleShot(300, do_all)
    elif mode == 'stop':
        C.QTimer.singleShot(300, do_stop)
    elif mode == 'close':
        C.QTimer.singleShot(300, do_close)

    app.exec()


def choose_url(recent: List[str], search_fn=None) -> Optional[str]:
    """Pick a recent link, search (when `search_fn(query)` is given), or paste
    a link. `search_fn` returns ``[{'title','url','source'}]``."""
    from PySide6 import QtWidgets as W, QtCore as C, QtGui as G
    app = _app()
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
            if t:
                res['url'] = t
        win.accept()

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
