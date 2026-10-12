"""tp.gui_all - the unified window: search/link AND episodes/options in one page.

The top has a search field that queries AnimeGate + AnimeX (or accepts any
link / @channel). Picking a result loads a `Session` into the SAME window, so
you can jump between titles without the app closing and reopening. Playback,
Stop, resume, options and the log are all here.
"""
import os
import queue
import threading
from typing import Callable

from . import log as _log


def _app():
    from .gui_qt import _app as app
    return app()


def _icon(G):
    from .gui_qt import _app_icon
    return _app_icon(G)


def app(loader: Callable[[str, str], object], cfg=None, one_shot: bool = False,
        initial=None):
    """Open the unified window. `loader(src, target)` returns a Session."""
    from PySide6 import QtWidgets as W, QtCore as C, QtGui as G
    from .search import search_all
    from .cli_all import route
    from . import history

    class _SortItem(W.QTableWidgetItem):
        """Sorts by the numeric/string key in UserRole, not the shown text."""
        def __lt__(self, other):
            a = self.data(C.Qt.UserRole)
            b = other.data(C.Qt.UserRole)
            try:
                return float(a) < float(b)
            except Exception:
                return str(a) < str(b)

    def _mk_table(cols):
        t = W.QTableWidget(0, len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        t.setSelectionMode(W.QAbstractItemView.SingleSelection)
        t.setShowGrid(False)
        t.setAlternatingRowColors(True)
        t.setMinimumWidth(340)
        t.horizontalHeader().setSectionResizeMode(len(cols) - 1,
                                                  W.QHeaderView.Stretch)
        t.setSortingEnabled(True)
        return t

    qapp = _app()
    from .http import HttpClient
    http = HttpClient()
    state: dict = {'session': None, 'closing': False, 'msg': '',
                   'loading': False, 'playing': False}

    win = W.QWidget()
    win.setWindowTitle('tgplay')
    win.resize(1180, 820)
    ic = _icon(G)
    if ic is not None:
        win.setWindowIcon(ic)
    outer = W.QHBoxLayout(win)
    outer.setContentsMargins(12, 10, 12, 10)
    outer.setSpacing(10)
    root = W.QVBoxLayout()
    root.setSpacing(8)
    outer.addLayout(root, 1)
    side = W.QVBoxLayout()
    side.setSpacing(8)
    outer.addLayout(side, 0)

    # --- right sidebar: feed / calendar (top) + history (bottom) --------
    fbox = W.QGroupBox('Feed · calendar  (click a header to sort)')
    fv = W.QVBoxLayout(fbox)
    frow = W.QHBoxLayout()
    frow.addWidget(W.QLabel('Show'))
    feed_filter = W.QComboBox()
    feed_filter.addItems(['Calendar', 'Remaining', 'All'])
    frow.addWidget(feed_filter)
    frow.addStretch(1)
    fv.addLayout(frow)
    feed = _mk_table(['Date', 'Ep', 'Title'])
    fv.addWidget(feed)
    side.addWidget(fbox, 1)
    hbox = W.QGroupBox('History  (click a header to sort)')
    hv = W.QVBoxLayout(hbox)
    hist = _mk_table(['Watched', 'Prog', 'Title'])
    hist.setMaximumHeight(260)
    hv.addWidget(hist)
    side.addWidget(hbox, 0)
    side_btn = W.QPushButton('↻  refresh feed & history')
    side.addWidget(side_btn)

    # --- search row -----------------------------------------------------
    srow = W.QHBoxLayout()
    box = W.QLineEdit()
    box.setClearButtonEnabled(True)
    box.setPlaceholderText('Search animegate + animex…  or paste a link / @channel')
    srow.addWidget(box, 1)
    hist_btn = W.QPushButton('🕘 History')
    hist_btn.setToolTip('Your recent links and searches in the app')
    srow.addWidget(hist_btn)
    root.addLayout(srow)

    results = W.QListWidget()
    results.setMaximumHeight(170)
    results.setVisible(False)
    root.addWidget(results)

    # --- header ---------------------------------------------------------
    head = W.QLabel('Search or paste a link to start')
    hf = head.font(); hf.setPointSize(hf.pointSize() + 2); head.setFont(hf)
    hrow = W.QHBoxLayout()
    hrow.addWidget(head, 1)
    add_btn = W.QPushButton('＋ Simkl list')
    add_btn.setToolTip('Add the current show to your Simkl Watching list '
                       '(it then appears in the calendar)')
    hrow.addWidget(add_btn)
    root.addLayout(hrow)
    link_lbl = W.QLabel('')
    link_lbl.setTextInteractionFlags(C.Qt.TextBrowserInteraction)
    link_lbl.setOpenExternalLinks(True)
    root.addWidget(link_lbl)

    # --- options --------------------------------------------------------
    obox = W.QGroupBox('Options')
    form = W.QGridLayout(obox)
    form.setHorizontalSpacing(10); form.setVerticalSpacing(4)
    server_lbl = W.QLabel('Server')
    server = W.QComboBox(); server.setEditable(False)
    audio_lbl = W.QLabel('Audio')
    audio_cb = W.QComboBox(); audio_cb.addItems(['dub', 'sub', 'auto'])
    audio_cb.setEditable(False)
    skip = W.QComboBox(); skip.addItems(['off', 'all', 'names', 'auto'])
    skip.setEditable(False)
    toggle = W.QCheckBox('toggle key T')
    full = W.QCheckBox('fullscreen')
    nxt = W.QCheckBox('Pre-download next episode')
    nowait = W.QCheckBox('start it at cut point')
    sync_cb = W.QCheckBox('Sync progress to Simkl')
    sync_cb.setChecked(True)
    sync_cb.setToolTip('Off = never push watch progress to Simkl for this run')
    cut = W.QLineEdit(); cut.setFixedWidth(70)
    extra = W.QLineEdit()
    r = 0
    form.addWidget(server_lbl, r, 0); form.addWidget(server, r, 1, 1, 3); r += 1
    form.addWidget(audio_lbl, r, 0); form.addWidget(audio_cb, r, 1, 1, 3); r += 1
    form.addWidget(W.QLabel('Skip'), r, 0); form.addWidget(skip, r, 1)
    form.addWidget(toggle, r, 2); form.addWidget(full, r, 3); r += 1
    form.addWidget(nxt, r, 0, 1, 2); form.addWidget(nowait, r, 2, 1, 2); r += 1
    form.addWidget(sync_cb, r, 0, 1, 4); r += 1
    form.addWidget(W.QLabel('Cut last N s'), r, 0); form.addWidget(cut, r, 1)
    form.addWidget(W.QLabel('Extra mpv flags'), r, 2); form.addWidget(extra, r, 3)
    root.addWidget(obox)

    # --- episodes -------------------------------------------------------
    ebox = W.QGroupBox('Episodes')
    ev = W.QVBoxLayout(ebox)
    table = W.QTableWidget(0, 2)
    table.setHorizontalHeaderLabels(['#', 'Episode name'])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
    table.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    hdr = table.horizontalHeader()
    hdr.setSectionResizeMode(0, W.QHeaderView.ResizeToContents)
    hdr.setSectionResizeMode(1, W.QHeaderView.Stretch)
    ev.addWidget(table)
    root.addWidget(ebox, 1)

    status = W.QLabel('idle')
    root.addWidget(status)

    # --- log ------------------------------------------------------------
    lbox = W.QGroupBox('Log')
    lv = W.QVBoxLayout(lbox)
    logbox = W.QPlainTextEdit()
    logbox.setReadOnly(True)
    logbox.setMaximumBlockCount(3000)
    logbox.setFixedHeight(150)
    try:
        logbox.setFont(G.QFontDatabase.systemFont(G.QFontDatabase.FixedFont))
    except Exception:
        pass
    lv.addWidget(logbox)
    if _log.HISTORY:
        logbox.setPlainText('\n'.join(list(_log.HISTORY)))
    root.addWidget(lbox)

    # --- buttons --------------------------------------------------------
    bar = W.QHBoxLayout()
    b_from = W.QPushButton('▶  Play from here')
    b_sel = W.QPushButton('▶  Only selected')
    b_all = W.QPushButton('▶  All')
    b_stop = W.QPushButton('■  Stop')
    b_close = W.QPushButton('Close')
    for b in (b_from, b_sel, b_all, b_stop):
        bar.addWidget(b)
    bar.addStretch(1); bar.addWidget(b_close)
    root.addLayout(bar)

    lq: 'queue.Queue' = queue.Queue()
    prev_sink = _log.SINK
    _log.SINK = lambda s: lq.put(str(s))

    rq: 'queue.Queue' = queue.Queue()
    libq: 'queue.Queue' = queue.Queue()

    # --- behavior -------------------------------------------------------
    def current_sel():
        rows = sorted({i.row() for i in table.selectedIndexes()})
        nums = [int(table.item(r, 0).data(C.Qt.UserRole)) for r in rows
                if table.item(r, 0)]
        return nums

    def focus_num():
        r = table.currentRow()
        it = table.item(r, 0) if r >= 0 else None
        return int(it.data(C.Qt.UserRole)) if it else None

    def all_nums():
        return [int(table.item(r, 0).data(C.Qt.UserRole))
                for r in range(table.rowCount())]

    def apply_opts():
        s = state['session']
        o = dict(s.opts) if s else {}
        if server.isVisible():
            o['f'] = server.currentText()
        if audio_cb.isVisible():
            o['audio'] = audio_cb.currentText()
        sm = skip.currentText()
        o['skip'] = False if sm == 'off' else sm
        o['skip_toggle'] = bool(toggle.isChecked())
        o['next'] = 0.60 if nxt.isChecked() else False
        o['nowait'] = bool(nowait.isChecked())
        o['sync'] = 'auto' if sync_cb.isChecked() else 'off'
        c = cut.text().strip()
        o['cut'] = int(c) if c.isdigit() else None
        m = extra.text().split()
        if full.isChecked() and '--fullscreen' not in m:
            m.append('--fullscreen')
        return o, m

    def do_play(chosen):
        s = state['session']
        if s is None or not chosen:
            return
        if state.get('playing'):
            return                          # one video at a time
        o, m = apply_opts()
        state['playing'] = True
        state['msg'] = 'starting…'
        if one_shot:
            try:
                s.play(chosen, o, m)
            finally:
                state['playing'] = False
            close()
            return

        def run():
            try:
                s.play(chosen, o, m)
                state['msg'] = ''
            except Exception as ex:
                state['msg'] = f'error: {ex}'
            finally:
                state['playing'] = False
        threading.Thread(target=run, daemon=True).start()

    def from_here():
        f = focus_num()
        if f is not None:
            do_play([n for n in all_nums() if n >= f])

    def only_sel():
        sel = current_sel()
        f = focus_num()
        do_play(sel if sel else ([f] if f is not None else all_nums()))

    def do_stop():
        s = state['session']
        if s:
            try:
                s.stop()
            except Exception:
                pass
        state['msg'] = 'stopped'

    def set_session(s):
        old = state['session']
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        state['session'] = s
        state['msg'] = ''
        head.setText(s.title or 'tgplay')
        link_lbl.setText(f'<a href="{s.link}">{s.link}</a>' if s.link else '')
        # server list
        labels = [str(g['label']) for g in s.groups]
        server.blockSignals(True)
        server.clear(); server.addItems(labels)
        if labels:
            want = s.opts.get('f')
            idx = next((i for i, l in enumerate(labels)
                        if want and str(want).lower() in l.lower()), 0)
            server.setCurrentIndex(idx)
        server.blockSignals(False)
        for w in (server, server_lbl):
            w.setVisible(bool(labels))
        # audio
        for w in (audio_cb, audio_lbl):
            w.setVisible(bool(s.audio))
        if s.audio:
            audio_cb.setCurrentText(s.opts.get('audio')
                                    if s.opts.get('audio') in ('dub', 'sub', 'auto')
                                    else 'dub')
        # options
        o = s.opts
        skip.setCurrentText(o.get('skip') if isinstance(o.get('skip'), str)
                            else ('all' if o.get('skip') else 'off'))
        toggle.setChecked(bool(o.get('skip_toggle')))
        nxt.setChecked(bool(o.get('next')))
        nowait.setChecked(bool(o.get('nowait')))
        sync_cb.setChecked(o.get('sync', 'auto') != 'off')
        cut.setText(str(o.get('cut') or ''))
        extra.setText(' '.join(x for x in s.mpv if x != '--fullscreen'))
        full.setChecked('--fullscreen' in s.mpv)
        # episodes
        nums = sorted(s.labels)
        table.setRowCount(0)
        table.setRowCount(len(nums))
        for i, n in enumerate(nums):
            it0 = W.QTableWidgetItem(str(n))
            it0.setData(C.Qt.UserRole, n)
            it0.setTextAlignment(C.Qt.AlignRight | C.Qt.AlignVCenter)
            table.setItem(i, 0, it0)
            table.setItem(i, 1, W.QTableWidgetItem(
                s.labels.get(n, f'Episode {n}')))
        ebox.setTitle(f'Episodes ({len(nums)})')
        if nums:
            row = nums.index(s.resume[0]) if (s.resume and s.resume[0] in s.labels) else 0
            table.selectRow(row)
            table.setCurrentCell(row, 1)
            table.scrollToItem(table.item(row, 1))

    # --- search ---------------------------------------------------------
    debounce = C.QTimer(); debounce.setSingleShot(True); debounce.setInterval(350)
    poll = C.QTimer(); poll.setInterval(150)

    def run_search(text):
        def work():
            try:
                rq.put(search_all(text, sources=('agp', 'axp')) or [])
            except Exception:
                rq.put([])
        threading.Thread(target=work, daemon=True).start()

    def fill_results(items):
        results.clear()
        for e in items:
            kind = e.get('kind') or 'result'
            title = e.get('title', '')
            if kind == 'query':
                label = f'🔎  {title}     ·     recent search'
            else:
                label = f"{title}     ·     {e.get('source', '')}"
            it = W.QListWidgetItem(label)
            it.setData(C.Qt.UserRole, e.get('url'))
            it.setData(C.Qt.UserRole + 1, e.get('source'))
            it.setData(C.Qt.UserRole + 2, title)
            it.setData(C.Qt.UserRole + 3, kind)
            results.addItem(it)
        results.setVisible(bool(items))

    def show_history():
        items = history.recent(cfg) if cfg is not None else []
        fill_results(items)

    def load_target(src, target):
        if state.get('loading'):
            return                          # ignore repeat clicks while loading
        state['loading'] = True
        state['msg'] = f'loading  {target} …'
        try:
            head.setText(f'loading  {target} …')
        except Exception:
            pass
        try:
            s = loader(src, target)
        except Exception as ex:
            state['msg'] = f'error: {ex}'
            state['loading'] = False
            return
        state['loading'] = False
        if cfg is not None:
            history.add(cfg, link=target)
        set_session(s)
        state['msg'] = ''

    def on_text():
        t = box.text().strip()
        if not t:
            show_history()
            return
        r = route(t)
        if r:
            fill_results([{'title': t, 'url': r[1], 'source': r[0]}])
            return
        debounce.start()

    def drain_search():
        try:
            items = rq.get_nowait()
        except queue.Empty:
            return
        fill_results(items)

    def pick_result(item):
        if item is None:
            return
        kind = item.data(C.Qt.UserRole + 3)
        if kind == 'query':                     # replay a past search
            box.setText(str(item.data(C.Qt.UserRole + 2)))
            return
        src = item.data(C.Qt.UserRole + 1) or 'agp'
        target = item.data(C.Qt.UserRole)
        if target:
            q = box.text().strip()
            if cfg is not None and q and not route(q):
                history.add(cfg, query=q)
            box.clear()
            fill_results([])
            load_target(str(src), str(target))

    def accept_typed():
        t = box.text().strip()
        r = route(t)
        if r:
            fill_results([])
            load_target(r[0], r[1])
            return
        n = results.currentRow()
        if n < 0 and results.count():
            n = 0
        if n >= 0:
            pick_result(results.item(n))

    box.textChanged.connect(on_text)
    debounce.timeout.connect(lambda: run_search(box.text().strip()))
    poll.timeout.connect(drain_search)
    poll.start()
    results.itemClicked.connect(pick_result)
    results.itemActivated.connect(pick_result)
    box.returnPressed.connect(accept_typed)

    # --- library / sidebar ----------------------------------------------
    def _goto_ep(ep):
        if not ep:
            return
        for r in range(table.rowCount()):
            it = table.item(r, 0)
            if it and int(it.data(C.Qt.UserRole)) == int(ep):
                table.selectRow(r)
                table.setCurrentCell(r, 1)
                return                       # select only; Play buttons start it

    def load_entry(e):
        if not e:
            return
        state['msg'] = f"finding “{e['title']}” on our sources…"

        def work():
            try:
                from .library import find_source
                res = find_source(e['title'], http)
            except Exception:
                res = None
            libq.put(('load', e, res))
        threading.Thread(target=work, daemon=True).start()

    def add_current():
        s = state['session']
        if s is None:
            state['msg'] = 'load a show first'
            return
        state['msg'] = f'adding “{s.title}” to Simkl…'

        def work():
            try:
                from .metadata import Metadata
                from .simkl_account import SimklAccount
                mal = getattr(s.provider, 'mal_id', None)
                if not mal:
                    mal = Metadata(cfg, http).resolve_mal(s.title, ask=False)
                ids = {'mal': mal} if mal else {'title': s.title}
                ok = SimklAccount(cfg, http).add_to_list(ids, 'watching')
                state['msg'] = ('added to Simkl list' if ok
                                else 'could not add to Simkl (logged in?)')
                if ok:
                    libq.put(('feed-refresh',))
            except Exception as ex:
                state['msg'] = f'add failed: {ex}'
        threading.Thread(target=work, daemon=True).start()

    def _fmt_date(s):
        try:
            from datetime import datetime
            d = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
            return d.strftime('%a %d %b %Y')
        except Exception:
            return str(s)[:10]

    def load_side():
        feed.setSortingEnabled(False)
        feed.setRowCount(0)
        hist.setSortingEnabled(False)
        hist.setRowCount(0)
        feed.insertRow(0)
        feed.setItem(0, 2, W.QTableWidgetItem('loading…'))

        def work():
            from .simkl_account import SimklAccount
            try:
                connected = SimklAccount(cfg).logged_in() if cfg is not None else False
            except Exception:
                connected = False
            if not connected:
                libq.put(('feed', None, None))
                return
            try:
                from .library import overview
                ov = overview(cfg, http)
                cal, rem, rc = ov['cal'], ov['rem'], ov['hist']
            except Exception:
                cal, rem, rc = [], [], []
            libq.put(('feed', {'cal': cal, 'rem': rem}, rc))
        threading.Thread(target=work, daemon=True).start()

    def render_feed():
        cal = state.get('cal')
        rem = state.get('rem')
        feed.setSortingEnabled(False)
        feed.setRowCount(0)
        if cal is None and rem is None:
            feed.insertRow(0)
            feed.setItem(0, 2, W.QTableWidgetItem('connect:  tgplay simkl login'))
            feed.setSortingEnabled(True)
            return
        mode = feed_filter.currentText()
        if mode == 'Calendar':
            rows = list(cal or [])
        elif mode == 'Remaining':
            rows = list(rem or [])
        else:                                   # All (de-duplicated)
            seen, rows = set(), []
            for e in list(cal or []) + list(rem or []):
                key = (e.get('simkl'), e.get('next_ep'))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(e)
        for e in rows:
            r = feed.rowCount(); feed.insertRow(r)
            k = e.get('kind')
            if k == 'upcoming':
                when = '📅  ' + _fmt_date(e['air_date'])
            elif k == 'aired':
                when = '✅  aired ' + str(e['air_date'])[:10]
            else:                               # remaining
                when = str(e.get('air_date') or '')[:10] or '—'
            c0 = _SortItem(when)
            c0.setData(C.Qt.UserRole, str(e.get('air_date') or '9999-99'))
            c0.setData(C.Qt.UserRole + 1, e)
            feed.setItem(r, 0, c0)
            c1 = _SortItem(str(e.get('next_ep') or ''))
            c1.setData(C.Qt.UserRole, int(e.get('next_ep') or 0))
            feed.setItem(r, 1, c1)
            ttl = e['title']
            if k == 'upcoming' and e.get('ep_title'):
                ttl = f"{e['title']} · {e['ep_title']}"
            elif k == 'remaining' and e.get('total'):
                ttl = f"{e['title']}  ({e.get('watched')}/{e.get('total')})"
            feed.setItem(r, 2, W.QTableWidgetItem(ttl))
        if not rows:
            feed.insertRow(0)
            feed.setItem(0, 2, W.QTableWidgetItem(
                'nothing here — try another filter or ↻ refresh'))
        feed.setSortingEnabled(True)

    def drain_lib():
        while True:
            try:
                msg = libq.get_nowait()
            except queue.Empty:
                return
            if msg[0] == 'feed-refresh':
                load_side()
            elif msg[0] == 'feed':
                _, payload, rc = msg
                if payload is None:
                    state['cal'] = state['rem'] = None
                else:
                    state['cal'] = payload.get('cal')
                    state['rem'] = payload.get('rem')
                render_feed()
                hist.setSortingEnabled(False)
                hist.setRowCount(0)
                if payload is None:
                    hist.insertRow(0)
                    hist.setItem(0, 2, W.QTableWidgetItem(
                        'connect:  tgplay simkl login'))
                    continue
                for e in rc:
                    r = hist.rowCount(); hist.insertRow(r)
                    c0 = _SortItem(str(e.get('last_watched'))[:10])
                    c0.setData(C.Qt.UserRole, str(e.get('last_watched') or ''))
                    c0.setData(C.Qt.UserRole + 1, e)
                    hist.setItem(r, 0, c0)
                    c1 = _SortItem(f"{e['watched']}/{e['total']}")
                    c1.setData(C.Qt.UserRole, int(e.get('watched') or 0))
                    hist.setItem(r, 1, c1)
                    hist.setItem(r, 2, W.QTableWidgetItem(e['title']))
                if not rc:
                    hist.insertRow(0)
                    hist.setItem(0, 2, W.QTableWidgetItem('no history'))
                hist.setSortingEnabled(True)
            elif msg[0] == 'load':
                _, entry, res = msg
                if res:
                    load_target(res[0], res[1])
                    C.QTimer.singleShot(
                        120, lambda ep=entry.get('next_ep'): _goto_ep(ep))
                else:
                    state['msg'] = f"not found on our sources: {entry['title']}"

    def _row_entry(table, item):
        try:
            return table.item(item.row(), 0).data(C.Qt.UserRole + 1)
        except Exception:
            return None

    def _open_url(u):
        try:
            G.QDesktopServices.openUrl(C.QUrl(u))
        except Exception:
            pass

    def _set_status(e, status):
        ids = {k: e[k] for k in ('mal', 'anilist', 'simkl') if e.get(k)}
        if not ids:
            state['msg'] = 'no id to update on Simkl'
            return
        state['msg'] = f'setting Simkl → {status}…'

        def work():
            try:
                from .simkl_account import SimklAccount
                ok = SimklAccount(cfg, http).add_to_list(ids, status)
                state['msg'] = (f'Simkl → {status}' if ok
                                else 'Simkl update failed (logged in?)')
                if ok:
                    libq.put(('feed-refresh',))
            except Exception as ex:
                state['msg'] = f'Simkl update failed: {ex}'
        threading.Thread(target=work, daemon=True).start()

    def _context(table, pos):
        it = table.itemAt(pos)
        if it is None:
            return
        e = table.item(it.row(), 0).data(C.Qt.UserRole + 1)
        if not e:
            return
        menu = W.QMenu(table)
        a_load = menu.addAction('▶   Search / load on our sources')
        sub = menu.addMenu('➕  Simkl list')
        acts = {}
        for label, st in (('Watching', 'watching'),
                          ('Plan to watch', 'plantowatch'),
                          ('Completed', 'completed'),
                          ('On hold', 'hold'),
                          ('Dropped', 'dropped')):
            acts[sub.addAction(label)] = st
        a_simkl = menu.addAction('🔗  Open on Simkl') if e.get('simkl') else None
        a_mal = menu.addAction('🔗  Open on MAL') if e.get('mal') else None
        pick = menu.exec(table.viewport().mapToGlobal(pos))
        if pick is None:
            return
        if pick == a_load:
            load_entry(e)
        elif pick in acts:
            _set_status(e, acts[pick])
        elif a_simkl is not None and pick == a_simkl:
            _open_url(f"https://simkl.com/anime/{e['simkl']}")
        elif a_mal is not None and pick == a_mal:
            _open_url(f"https://myanimelist.net/anime/{e['mal']}")

    for _t in (feed, hist):
        _t.setContextMenuPolicy(C.Qt.CustomContextMenu)
        _t.customContextMenuRequested.connect(
            lambda pos, t=_t: _context(t, pos))

    hist_btn.clicked.connect(show_history)
    add_btn.clicked.connect(add_current)
    side_btn.clicked.connect(load_side)
    feed_filter.currentTextChanged.connect(lambda _t: render_feed())
    feed.itemDoubleClicked.connect(lambda it: load_entry(_row_entry(feed, it)))
    hist.itemDoubleClicked.connect(lambda it: load_entry(_row_entry(hist, it)))
    poll.timeout.connect(drain_lib)

    # refresh the sidebar shortly after a sync lands (history/feed changed)
    side_timer = C.QTimer()
    side_timer.setSingleShot(True)
    side_timer.setInterval(1500)
    side_timer.timeout.connect(load_side)

    def drain_log():
        if state['closing']:
            return
        lines = []
        while True:
            try:
                lines.append(lq.get_nowait())
            except queue.Empty:
                break
        if lines:
            logbox.appendPlainText('\n'.join(lines))
            logbox.verticalScrollBar().setValue(
                logbox.verticalScrollBar().maximum())
            if any(('synced:' in ln) or ('marked ep' in ln) for ln in lines):
                side_timer.start()          # auto-refresh feed/history

    def refresh_status():
        if state['closing']:
            return
        s = state['session']
        txt = s.status() if s is not None else ''
        if state.get('msg'):
            txt = state['msg']
        status.setText(txt or 'idle')

    log_timer = C.QTimer(); log_timer.timeout.connect(drain_log); log_timer.start(250)
    st_timer = C.QTimer(); st_timer.timeout.connect(refresh_status); st_timer.start(1000)

    def close():
        state['closing'] = True
        for t in (debounce, poll, log_timer, st_timer, side_timer):
            try:
                t.stop()
            except Exception:
                pass
        try:
            if state['session'] is not None:
                state['session'].close()
        except Exception:
            pass
        try:
            _log.SINK = prev_sink
        except Exception:
            pass
        win.close()
        try:
            qapp.quit()
        except Exception:
            pass

    b_from.clicked.connect(from_here)
    b_sel.clicked.connect(only_sel)
    b_all.clicked.connect(lambda: do_play(all_nums()))
    b_stop.clicked.connect(do_stop)
    b_close.clicked.connect(close)
    win.destroyed.connect(lambda *_: (_log.__setattr__('SINK', prev_sink)))

    show_history()
    box.setFocus()
    win.show()
    try:
        win.raise_(); win.activateWindow()
    except Exception:
        pass
    load_side()

    mode = os.environ.get('AGP_GUI_TEST')
    if initial:
        load_target(initial[0], initial[1])
    if mode == 'play':
        C.QTimer.singleShot(300, from_here)
    elif mode == 'all':
        C.QTimer.singleShot(300, lambda: do_play(all_nums()))
    elif mode == 'close':
        C.QTimer.singleShot(300, close)

    qapp.exec()
