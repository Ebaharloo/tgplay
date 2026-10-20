"""tp.gui_all - the unified window: search/link AND episodes/options in one page.

Now an OOP MainWindow. The top has a search field that queries AnimeGate +
AnimeX (or accepts any link / @channel). Picking a result loads a `Session`
into the SAME window, so you can jump between titles without the app closing
and reopening. Playback, Stop, resume, the shared options form (tp.options),
the Simkl sidebar and the log are all here.
"""
import os
import queue
import re
import tempfile
import threading
import time
from typing import Callable, List, Optional

from PySide6 import QtWidgets as W, QtCore as C, QtGui as G

from . import history
from . import log as _log
from .options import PlaybackOptions


class LogView(W.QTextBrowser):
    """The in-window log: coloured, icon-prefixed, timestamped lines.

    Lines arrive exactly as the terminal prints them (tp.log already tags
    each kind with an emoji - 🔎 search, 🎬 playing, 🔔 sync, ⬇ download...).
    Each kind gets a colour + the line is stamped with its clock time so
    you can read the story (and the gaps) of a session at a glance."""

    # leading-emoji -> css colour; first match wins
    KINDS = [
        ('❌', '#e06c75'),   # errors / failures
        ('🎬', '#98c379'),   # streaming started
        ('🏁', '#e5c07b'),   # playlist finished
        ('🔎', '#c678dd'),   # searches (with duration)
        ('📡', '#61afef'),   # session loaded
        ('🏷', '#56b6c2'),   # episode-name sync
        ('🔗', '#98c379'),   # fresh signed links
        ('⏭', '#c678dd'),   # skip flags
        ('🔜', '#98c379'),   # next prefetch trigger
        ('⬇', '#61afef'),   # downloads / prefetch
        ('🗃', '#d19a66'),   # cache mirror
        ('🔔', '#56b6c2'),   # tracker sync
        ('▶', '#98c379'),   # resume / start position
        ('👁', '#abb2bf'),   # watched fraction
        ('📅', '#61afef'),   # feed / calendar refresh
        ('📥', '#c678dd'),   # load timings
        ('🎞', '#e5c07b'),   # mpv window-up
        ('📺', '#56b6c2'),   # show link
        ('🅼', '#e06c7b'),   # MAL / simkl meta
        ('🆂', '#56b6c2'),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setMaximumHeight(150)
        try:
            self.setFont(G.QFontDatabase.systemFont(G.QFontDatabase.FixedFont))
        except Exception:
            pass
        self._max = 2500
        self._follow = True

    def _trim(self):
        """Keep the last ~2500 lines (QTextBrowser lacks the block cap)."""
        from PySide6 import QtGui
        doc = self.document()
        extra = doc.blockCount() - self._max
        if extra <= 0:
            return
        c = QtGui.QTextCursor(doc)
        c.movePosition(QtGui.QTextCursor.Start)
        for _ in range(extra):
            c.select(QtGui.QTextCursor.LineUnderCursor)
            c.removeSelectedText()
            c.deleteChar()               # drop the newline too

    def _color(self, line):
        for e, col in self.KINDS:
            if line.startswith(e):
                return col
        return '#abb2bf'

    def feed(self, line):
        import html
        import time as _t
        col = self._color(line)
        ts = _t.strftime('%H:%M:%S')
        # auto-scroll only if the user is at the bottom (don't yank view)
        sb = self.verticalScrollBar()
        self._follow = sb.value() >= sb.maximum() - 6
        self.append(
            f'<span style="color:#5c6370">{ts}</span>  '
            f'<span style="color:{col}">{html.escape(line)}</span>')
        self._trim()
        if self._follow:
            sb.setValue(sb.maximum())

    def seed(self, lines):
        import html
        import time as _t
        now = _t.strftime('%H:%M:%S')
        parts = []
        for line in lines:
            parts.append(f'<span style="color:#5c6370">{now}</span>  '
                         f'<span style="color:{self._color(line)}">'
                         f'{html.escape(line)}</span>')
        self.setHtml('<br>'.join(parts))


class CastDialog(W.QDialog):
    """Who's in this show: cast with CN/native names, roles, voice actors,
    avatars and a link per character.

    Cache-first: opens INSTANTLY from characters.json (the pinned MAL id is
    the key); the AniList/Bangumi refresh + avatar downloads run on a worker
    thread and land through a queue the same way the main window drains its
    log - the dialog never blocks the UI."""

    def __init__(self, service, mal_id, title, parent=None):
        super().__init__(parent)
        self._svc, self._mal, self._title = service, mal_id, title
        self.setWindowTitle(f'Cast · {title}')
        self.resize(820, 500)
        self._q: 'queue.Queue' = queue.Queue()
        self._pix = {}                       # image url -> QPixmap
        self._img_file = {}                  # image url -> local file (big)
        self._tmp = tempfile.mkdtemp(prefix='tgplay-cast-')
        self._all_rows: List[dict] = []
        self._rows: List[dict] = []
        self._anilist_show = None
        self._closing = False
        self.resize(900, 560)

        lay = W.QHBoxLayout(self)
        left = W.QVBoxLayout()
        bar = W.QHBoxLayout()
        self.search = W.QLineEdit()
        self.search.setPlaceholderText(
            'search name / native / voice actor / bio…')
        self.search.setClearButtonEnabled(True)
        bar.addWidget(self.search, 1)
        self.origin_cb = W.QComboBox()
        self.origin_cb.addItems(['All', 'Anime', 'Manga', 'Novel', 'CN',
                                 'Wiki'])
        bar.addWidget(self.origin_cb)
        left.addLayout(bar)
        self.lst = W.QListWidget()
        self.lst.setMinimumWidth(360)
        self.lst.setAlternatingRowColors(True)
        left.addWidget(self.lst, 1)
        self.count_lbl = W.QLabel('')
        self.count_lbl.setStyleSheet('color:#888;')
        left.addWidget(self.count_lbl)
        lay.addLayout(left)
        self.pane = W.QTextBrowser()
        self.pane.setOpenExternalLinks(True)
        self.pane.setHtml(self._hint())
        lay.addWidget(self.pane, 1)
        self.lst.currentRowChanged.connect(self._show_row)
        self.search.textChanged.connect(lambda _t: self._apply_filter())
        self.origin_cb.currentTextChanged.connect(
            lambda _t: self._apply_filter())

        rec = None
        if self._svc is not None:
            try:
                rec = self._svc.cached(mal_id=mal_id, title=title)
            except Exception:
                rec = None
        if rec:
            self._fill(rec)                  # instant, from cache
        else:
            self.lst.addItem('loading cast…')
        threading.Thread(target=self._work, daemon=True).start()
        self._poll = C.QTimer(self)
        self._poll.setInterval(120)
        self._poll.timeout.connect(self._drain)
        self._poll.start()

    @staticmethod
    def _hint():
        return ('<b>Cast</b><br><span style="color:#888">pick a character - '
                'bio, voice actor and a link to their page.<br>'
                'Chinese titles are boosted with Bangumi (CN voice actors).'
                '</span>')

    # --- worker (never touches widgets) --------------------------------
    def _work(self):
        try:
            rec = self._svc.fetch(mal_id=self._mal, title=self._title) \
                if self._svc is not None else None
        except Exception:
            rec = None
        self._q.put(('rec', rec))
        # avatars: cap the downloads (novel casts can be huge; the list is
        # filterable, and images for non-shown rows aren't worth fetching)
        for r in ((rec or {}).get('rows') or [])[:80]:
            u = r.get('image')
            if u and u not in self._pix:
                data = self._dl(u)
                if data:
                    self._q.put(('img', u, data))

    @staticmethod
    def _dl(url):
        import urllib.request
        try:
            req = urllib.request.Request(
                url, headers={'User-Agent': 'Mozilla/5.0 tgplay/1.0'})
            with urllib.request.urlopen(req, timeout=12) as r:
                return r.read()
        except Exception:
            return None

    # --- GUI thread ------------------------------------------------------
    def _drain(self):
        if self._closing:
            return
        while True:
            try:
                msg = self._q.get_nowait()
            except queue.Empty:
                return
            if msg[0] == 'rec':
                if msg[1]:
                    self._fill(msg[1])
                elif self.lst.count() == 1 and \
                        self.lst.item(0).text() == 'loading cast…':
                    self.lst.clear()
                    self.lst.addItem('no cast found on AniList/Bangumi')
            elif msg[0] == 'img':
                url, data = msg[1], msg[2]
                pm = G.QPixmap()
                if pm.loadFromData(data):
                    self._pix[url] = pm
                    try:                    # a file for the big portrait
                        p = os.path.join(self._tmp,
                                         f'{abs(hash(url))}.img')
                        with open(p, 'wb') as f:
                            f.write(data)
                        self._img_file[url] = p
                    except Exception:
                        pass
                    self._reicon(url)

    @staticmethod
    def _mkicon(pm):
        return G.QIcon(pm.scaled(44, 44, C.Qt.KeepAspectRatio,
                                 C.Qt.SmoothTransformation))

    def _fill(self, rec):
        self._all_rows = rec.get('rows') or []
        self._anilist_show = rec.get('anilist_id')
        self._apply_filter()

    def _apply_filter(self, *_):
        q = (self.search.text() if hasattr(self, 'search') else '').strip()
        origin = (self.origin_cb.currentText()
                  if hasattr(self, 'origin_cb') else 'All')
        want = {'Anime': 'anime', 'Manga': 'manga', 'Novel': 'novel',
                'CN': 'bangumi', 'Wiki': 'wiki'}.get(origin)
        rows = []
        for r in self._all_rows:
            origin_row = r.get('from') or 'anime'
            if want and origin_row != want:
                # never lose the anime's MAIN cast when filtering a source
                if not (origin_row == 'anime' and r.get('role') == 'main'):
                    continue
            if q:
                blob = ' '.join(str(r.get(k) or '') for k in
                                ('name', 'native', 'va', 'desc', 'from'))
                if q.casefold() not in blob.casefold():
                    continue
            rows.append(r)
        cur = None
        it = self.lst.currentItem()
        if it is not None and isinstance(it.data(C.Qt.UserRole), dict):
            cur = it.data(C.Qt.UserRole).get('cid')
        self._rows = rows
        self.lst.blockSignals(True)
        self.lst.clear()
        for r in rows:
            role = {'main': '★ main', 'supporting': 'supporting'}.get(
                r.get('role', ''), r.get('role') or '?')
            label = r['name']
            if r.get('native'):
                label += f"  ({r['native']})"
            src = {'anime': '', 'manga': ' · manga', 'novel': ' · novel',
                   'bangumi': ' · CN', 'wiki': ' · wiki'}.get(
                       r.get('from') or 'anime', '')
            line = f"{label}   ·   {role}{src}"
            if r.get('va'):
                line += f"   ·   {r['va']}"
            item = W.QListWidgetItem(line)
            item.setData(C.Qt.UserRole, r)
            item.setToolTip(r.get('url') or '')
            pm = self._pix.get(r.get('image') or '')
            if pm is not None:
                item.setIcon(self._mkicon(pm))
            self.lst.addItem(item)
            if cur and r.get('cid') == cur:
                self.lst.setCurrentRow(self.lst.count() - 1)
        self.lst.blockSignals(False)
        capped = len(rows) < len(self._all_rows)
        self.count_lbl.setText(
            f'{len(rows)} character(s)'
            + (f' · {len(self._all_rows)} loaded' if capped else ''))
        if not rows:
            self.lst.addItem('no matching character - clear the search')
            self.pane.setHtml(self._hint())
        elif self.lst.currentRow() < 0:
            self.lst.setCurrentRow(0)

    def _reicon(self, url):
        for i in range(self.lst.count()):
            it = self.lst.item(i)
            r = it.data(C.Qt.UserRole) if it is not None else None
            if isinstance(r, dict) and r.get('image') == url:
                pm = self._pix.get(url)
                if pm is not None:
                    it.setIcon(self._mkicon(pm))
        it = self.lst.currentItem()
        r = it.data(C.Qt.UserRole) if it is not None else None
        if isinstance(r, dict) and r.get('image') == url:
            self._show_row(self.lst.currentRow())

    def _show_row(self, row):
        it = self.lst.item(row) if 0 <= row < self.lst.count() else None
        r = it.data(C.Qt.UserRole) if it is not None else None
        if not isinstance(r, dict):
            return
        import html as _h
        head = '<h3>' + _h.escape(r['name'])
        if r.get('native'):
            head += (" <span style='color:#888'>"
                     + _h.escape(r['native']) + '</span>')
        head += '</h3>'
        bits = []
        if r.get('role'):
            bits.append('role: <b>' + _h.escape(r['role']) + '</b>')
        if r.get('fav'):
            bits.append(f"favourites: {r['fav']}")
        if r.get('va'):
            bits.append('voice actor: <b>' + _h.escape(r['va'])
                        + (' (' + _h.escape(r['va_lang']) + ')'
                           if r.get('va_lang') else '') + '</b>')
        if (r.get('from') or 'anime') != 'anime':
            bits.append('source: <b>' + _h.escape(r['from']) + '</b>')
        parts = [head]
        if bits:
            parts.append(' · '.join(bits))
        if r.get('desc'):
            parts.append('<p>' + _h.escape(r['desc']) + '</p>')
        links = []
        if r.get('url'):
            links.append('<a href="' + _h.escape(r['url'])
                         + '">character page ↗</a>')
        if self._anilist_show:
            links.append('<a href="https://anilist.co/anime/'
                         + str(self._anilist_show)
                         + '/characters">full cast on AniList ↗</a>')
        if links:
            parts.append(' &nbsp; &nbsp;'.join(links))
        body = '<br>'.join(parts)
        img = self._img_file.get(r.get('image') or '')
        if img:
            # big portrait in a box, the name/links sit next to it
            self.pane.setHtml(
                '<table cellspacing="0" cellpadding="6"><tr>'
                f'<td valign="top"><img src="file://{img}" width="200"></td>'
                f'<td valign="top">{body}</td></tr></table>')
        else:
            self.pane.setHtml(body)

    def done(self, r):                          # close: stop polling
        self._closing = True
        try:
            self._poll.stop()
        except Exception:
            pass
        super().done(r)


class StatusStrip(W.QWidget):
    """Connection lights: ● Simkl · ● AnimeGate · ● AniList (+ ↻).

    Green = connected, amber = optional/off, red = needs action. Click a
    light to do the fix (Simkl PIN sign-in, AnimeGate login page); ↻
    re-probes every service and reloads the calendar."""

    COLORS = {'ok': '#98c379', 'warn': '#e5c07b', 'bad': '#e06c75'}
    NAMES = {'simkl': 'Simkl', 'gate': 'AnimeGate', 'anilist': 'AniList'}

    def __init__(self, on_click, on_refresh, parent=None):
        super().__init__(parent)
        row = W.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self._clicked = on_click
        self._items = {}
        self._btns = {}
        for key, name in self.NAMES.items():
            b = W.QPushButton(f'● {name}')
            b.setFlat(True)
            b.setCursor(C.Qt.PointingHandCursor)
            b.setStyleSheet('border:none; background:transparent; '
                            'padding:2px 4px;')
            b.clicked.connect(lambda _c=False, k=key: self._click(k))
            self._btns[key] = b
            row.addWidget(b)
        row.addStretch(1)
        self.refresh_btn = W.QToolButton()
        self.refresh_btn.setText('↻')
        self.refresh_btn.setToolTip('check connections + reload calendar')
        self.refresh_btn.clicked.connect(lambda: on_refresh())
        row.addWidget(self.refresh_btn)
        self.set_items([])

    def set_items(self, items):
        for key, b in self._btns.items():
            it = next((x for x in items if x.get('key') == key), None)
            if it:
                self._items[key] = it
                col = self.COLORS.get(it.get('state'), '#abb2bf')
                b.setText(f"● {it.get('name', self.NAMES[key])}")
                b.setStyleSheet('border:none; background:transparent; '
                                f'padding:2px 4px; color:{col};')
                b.setToolTip(f"{it.get('name', key)}: {it.get('detail', '')}")
            else:
                self._items[key] = {'key': key,
                                    'name': self.NAMES[key],
                                    'state': 'warn',
                                    'detail': 'not checked yet'}
                b.setStyleSheet('border:none; background:transparent; '
                                'padding:2px 4px; color:#abb2bf;')
                b.setToolTip(f"{self.NAMES[key]}: not checked yet")

    def _click(self, key):
        it = self._items.get(key)
        if it:
            self._clicked(it)


class SimklConnectDialog(W.QDialog):
    """Sign in to Simkl with the device/PIN flow, without leaving the app.

    Shows the PIN page link + the code, polls Simkl on a worker thread and
    closes itself the moment you approve - the lights/calendar refresh right
    after. 'Open page' puts the link in your browser; 'Copy code' helps."""

    def __init__(self, account, parent=None):
        super().__init__(parent)
        self.acc = account
        self._q = queue.Queue()
        self._closing = False
        self.setWindowTitle('Connect Simkl')
        self.setMinimumWidth(460)
        lay = W.QVBoxLayout(self)
        self.status = W.QLabel('starting Simkl sign-in…')
        lay.addWidget(self.status)
        self.link = W.QLabel('')
        self.link.setTextInteractionFlags(C.Qt.TextBrowserInteraction)
        self.link.setOpenExternalLinks(True)
        lay.addWidget(self.link)
        self.code_lbl = W.QLabel('')
        f = self.code_lbl.font()
        f.setPointSize(f.pointSize() + 6)
        f.setBold(True)
        self.code_lbl.setFont(f)
        lay.addWidget(self.code_lbl)
        bar = W.QHBoxLayout()
        self.open_btn = W.QPushButton('🌐 Open pin page')
        self.copy_btn = W.QPushButton('⧉ Copy code')
        self.cancel_btn = W.QPushButton('Cancel')
        for b in (self.open_btn, self.copy_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self.cancel_btn)
        lay.addLayout(bar)
        self.open_btn.clicked.connect(self._open)
        self.copy_btn.clicked.connect(self._copy)
        self.cancel_btn.clicked.connect(self.reject)

        self._dev = None
        try:
            self._dev = account.start_device()
        except Exception:
            self._dev = None
        if not self._dev:
            self.status.setText('Simkl sign-in unavailable (no client id or '
                                'device flow refused).')
            for b in (self.open_btn, self.copy_btn):
                b.setEnabled(False)
            return
        self.link.setText(
            f'<a href="{self._dev["url"]}">{self._dev["url"]}</a>')
        self.code_lbl.setText(self._dev['code'] or '')
        self.status.setText('Approve this code on the Simkl page - the '
                            'dialog closes itself when done.')
        threading.Thread(target=self._poll, daemon=True).start()
        self._timer = C.QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

    def _open(self):
        try:
            import webbrowser
            webbrowser.open(self._dev['url'])
        except Exception:
            pass

    def _copy(self):
        try:
            W.QApplication.clipboard().setText(self._dev['code'] or '')
            self.status.setText('code copied - now paste it on the Simkl page')
        except Exception:
            pass

    def _poll(self):
        interval = max(2, int(self._dev.get('interval') or 5))
        deadline = time.time() + int(self._dev.get('expires') or 900)
        while time.time() < deadline and not self._closing:
            time.sleep(interval)
            if self._closing:
                return
            res = self.acc.poll_device(self._dev['device_code'])
            self._q.put(res)
            if res == 'ok':
                return

    def _drain(self):
        if self._closing:
            return
        while True:
            try:
                res = self._q.get_nowait()
            except queue.Empty:
                return
            if res == 'ok':
                self._closing = True
                try:
                    self._timer.stop()
                except Exception:
                    pass
                self.accept()
                return
            if res not in ('pending', 'authorization_pending', 'slow_down'):
                self.status.setText(f'Simkl said: {res} - start again')
                try:
                    self._timer.stop()
                except Exception:
                    pass

    def done(self, r):
        self._closing = True
        try:
            self._timer.stop()
        except Exception:
            pass
        super().done(r)


def _app_main() -> 'W.QApplication':
    from .gui_qt import _app as app
    return app()


def _app_icon() -> Optional[G.QIcon]:
    from .gui_qt import _app_icon as icon
    return icon(G)


def _fmt_ts(ts) -> str:
    """Friendly 'when was this opened' stamp for the history picker."""
    ts = int(ts or 0)
    if not ts:
        return '(old)'
    age = max(0, int(time.time()) - ts)
    if age < 60:
        return 'just now'
    if age < 3600:
        return f'{age // 60}m ago'
    if age < 86400:
        return f'{age // 3600}h ago'
    if age < 7 * 86400:
        return f'{age // 86400}d ago'
    return time.strftime('%Y-%m-%d', time.localtime(ts))


def _fmt_date(s) -> str:
    try:
        from datetime import datetime
        d = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
        return d.strftime('%a %d %b %Y')
    except Exception:
        return str(s)[:10]



class _SortItem(W.QTableWidgetItem):
    """Sorts by the numeric/string key in UserRole, not the shown text."""

    def __lt__(self, other):
        a = self.data(C.Qt.UserRole)
        b = other.data(C.Qt.UserRole)
        try:
            return float(a) < float(b)
        except Exception:
            return str(a) < str(b)


class SortableTable(W.QTableWidget):
    """No-edit, row-select, alternating, sortable table (sidebar style)."""

    def __init__(self, cols: List[str], parent=None):
        super().__init__(0, len(cols), parent)
        self.setHorizontalHeaderLabels(cols)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.setSelectionMode(W.QAbstractItemView.SingleSelection)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setMinimumWidth(340)
        self.horizontalHeader().setSectionResizeMode(
            len(cols) - 1, W.QHeaderView.Stretch)
        self.setSortingEnabled(True)


class OptionsForm(W.QWidget):
    """The Options group, rendered from the ONE shared spec (tp.options).

    Every option is in the same place in every UI: quality/server, audio,
    skip, skip-toggle, fullscreen, pre-download next (+ 'start at cut'),
    Simkl sync, cut seconds and extra mpv flags. The rows/wiring mirror the
    old hand-built grid exactly; values flow through PlaybackOptions.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.box = W.QGroupBox('Options')
        form = W.QGridLayout(self.box)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(4)

        def combo(items=()):
            cb = W.QComboBox()
            cb.setEditable(False)
            cb.addItems(list(items))
            return cb

        self.server_lbl = W.QLabel('Server')
        self.server = combo()
        self.audio_lbl = W.QLabel('Audio')
        self.audio_cb = combo(['dub', 'sub', 'auto'])
        self.skip_lbl = W.QLabel('Skip')
        self.skip = combo(['off', 'all', 'names', 'auto'])
        self.toggle = W.QCheckBox('toggle key T')
        self.full = W.QCheckBox('fullscreen')
        self.nxt = W.QCheckBox('Pre-download next episode')
        self.nowait = W.QCheckBox('start it at cut point')
        self.sync_cb = W.QCheckBox('Sync progress to Simkl')
        self.sync_cb.setChecked(True)
        self.sync_cb.setToolTip(
            'Off = never push watch progress to Simkl for this run')
        self.cut = W.QLineEdit()
        self.cut.setFixedWidth(70)
        self.extra = W.QLineEdit()

        form.addWidget(self.server_lbl, 0, 0)
        form.addWidget(self.server, 0, 1, 1, 3)
        form.addWidget(self.audio_lbl, 1, 0)
        form.addWidget(self.audio_cb, 1, 1, 1, 3)
        form.addWidget(self.skip_lbl, 2, 0)
        form.addWidget(self.skip, 2, 1)
        form.addWidget(self.toggle, 2, 2)
        form.addWidget(self.full, 2, 3)
        form.addWidget(self.nxt, 3, 0, 1, 2)
        form.addWidget(self.nowait, 3, 2, 1, 2)
        form.addWidget(self.sync_cb, 4, 0, 1, 4)
        form.addWidget(W.QLabel('Cut last N s'), 5, 0)
        form.addWidget(self.cut, 5, 1)
        form.addWidget(W.QLabel('Extra mpv flags'), 5, 2)
        form.addWidget(self.extra, 5, 3)

        lay = W.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.box)
        # the per-session 'next' fraction is remembered when the form is
        # first filled (so an --next=45 CLI value survives untouched clicks)
        self._next_was = False
        self._next_orig = None

    # --- session -> widgets --------------------------------------------
    def load(self, s):
        """Fill every widget from the Session's opts/mpv/groups.

        Same rules the old hand-built code used, via the shared model."""
        po = PlaybackOptions(s.opts, s.mpv) if s is not None \
            else PlaybackOptions.defaults()
        s_opts = s.opts if s is not None else {}
        labels = [str(g['label']) for g in s.groups] if s is not None else []
        self.server.blockSignals(True)
        self.server.clear()
        self.server.addItems(labels)
        if labels and po.quality:
            idx = next((i for i, l in enumerate(labels)
                        if str(po.quality).lower() in l.lower()), 0)
            self.server.setCurrentIndex(idx)
        self.server.blockSignals(False)
        for w in (self.server, self.server_lbl):
            w.setVisible(bool(labels))
        # audio (AnimeX only)
        for w in (self.audio_cb, self.audio_lbl):
            w.setVisible(bool(s is not None and s.audio))
        if s is not None and s.audio:
            self.audio_cb.setCurrentText(po.audio_mode)
        # skip / toggles / next / cut / extras
        self.skip.setCurrentText(
            s_opts.get('skip') if isinstance(s_opts.get('skip'), str)
            else ('all' if s_opts.get('skip') else 'off'))
        self.toggle.setChecked(bool(s_opts.get('skip_toggle')))
        self.full.setChecked(po.fullscreen)
        self.nxt.setChecked(bool(po.next))
        self.nowait.setChecked(po.nowait)
        self.sync_cb.setChecked(po.sync == 'auto')
        self.cut.setText(str(po.cut or ''))
        self.extra.setText(' '.join(po.extras))
        self._next_was = bool(po.next)
        self._next_orig = po.next if not isinstance(po.next, bool) else None

    # --- widgets -> legacy (opts, mpv) ---------------------------------
    def to_raw(self, s) -> tuple:
        po = PlaybackOptions(s.opts if s is not None else None)
        if self.server.isVisible():
            po.quality = self.server.currentText()
        if self.audio_cb.isVisible():
            po.audio = self.audio_cb.currentText()
        po.set_skip(self.skip.currentText())
        po.set_skip_toggle(self.toggle.isChecked())
        if self.nxt.isChecked():
            # untouched + checked keeps its exact fraction (--next=N)
            keep = self._next_orig if (self._next_was and self._next_orig) \
                else 0.60
            po.set_next(keep)
        else:
            po.set_next(False)
        po.set_nowait(self.nowait.isChecked())
        po.set_sync(self.sync_cb.isChecked())
        po.set_cut(self.cut.text().strip())
        po.with_extras(self.extra.text().split(),
                       fullscreen=self.full.isChecked())
        return po.to_opts(), po.mpv()


class MainWindow(W.QWidget):
    """The one tgplay window: search, sessions, options, sidebar, log."""

    def __init__(self, loader: Callable, cfg=None, one_shot: bool = False):
        super().__init__()
        self._loader = loader
        self._cfg = cfg
        self._one_shot = one_shot
        self.state: dict = {'session': None, 'closing': False, 'msg': '',
                            'loading': False, 'playing': False}

        from .http import HttpClient
        self._http = HttpClient()
        self._lq: 'queue.Queue' = queue.Queue()      # log lines
        self._rq: 'queue.Queue' = queue.Queue()      # search results
        self._libq: 'queue.Queue' = queue.Queue()    # sidebar payloads
        self._prev_sink = _log.SINK
        _log.SINK = lambda s: self._lq.put(str(s))

        self.setWindowTitle('tgplay')
        self.resize(1180, 820)
        ic = _app_icon()
        if ic is not None:
            self.setWindowIcon(ic)
        outer = W.QHBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(10)
        root = W.QVBoxLayout()
        root.setSpacing(8)
        outer.addLayout(root, 1)
        side = W.QVBoxLayout()
        side.setSpacing(8)
        outer.addLayout(side, 0)

        self._build_sidebar(side)
        self._build_search_row(root)
        self._build_header(root)
        self._build_options(root)
        self._build_episodes(root, outer)
        self._build_status(root)
        self._build_log(root)
        self._build_buttons(root)

        self._timers()
        self._connect()

    # --- widget construction -------------------------------------------
    def _build_sidebar(self, side: W.QLayout):
        self.status_strip = StatusStrip(self._status_clicked,
                                        self._probe_status)
        side.addWidget(self.status_strip)
        fbox = W.QGroupBox('Feed · calendar  (click a header to sort)')
        fv = W.QVBoxLayout(fbox)
        frow = W.QHBoxLayout()
        frow.addWidget(W.QLabel('Show'))
        self.feed_filter = W.QComboBox()
        self.feed_filter.addItems(['Calendar', 'Remaining', 'All'])
        frow.addWidget(self.feed_filter)
        frow.addStretch(1)
        fv.addLayout(frow)
        self.feed = SortableTable(['Date', 'Ep', 'Title'])
        fv.addWidget(self.feed)
        side.addWidget(fbox, 1)

        hbox = W.QGroupBox('History  (click a header to sort)')
        hv = W.QVBoxLayout(hbox)
        self.hist = SortableTable(['Watched', 'Prog', 'Title'])
        self.hist.setMaximumHeight(260)
        hv.addWidget(self.hist)
        side.addWidget(hbox, 0)

        self.side_btn = W.QPushButton('↻  refresh feed & history')
        side.addWidget(self.side_btn)

    def _build_search_row(self, root: W.QLayout):
        srow = W.QHBoxLayout()
        self.box = W.QLineEdit()
        self.box.setClearButtonEnabled(True)
        self.box.setPlaceholderText(
            'Search animegate + animex…  or paste a link / @channel')
        srow.addWidget(self.box, 1)
        self.hist_btn = W.QPushButton('🕘 History')
        self.hist_btn.setToolTip(
            'Your recent links and searches, with their date and source.\n'
            'Click a header (Date/Source/Link) to sort · ✕ removes one entry.')
        srow.addWidget(self.hist_btn)
        root.addLayout(srow)

        # history gets a real table (Date | Source | Link | ✕); the search
        # list keeps the plain look - a QStackedWidget swaps the two views.
        self.results = W.QListWidget()
        self.results.setMaximumHeight(170)

        self.hist_tbl = W.QTableWidget(0, 4)
        self.hist_tbl.setHorizontalHeaderLabels(['Date', 'Source', 'Link', ''])
        self.hist_tbl.verticalHeader().setVisible(False)
        self.hist_tbl.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.hist_tbl.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.hist_tbl.setSelectionMode(W.QAbstractItemView.SingleSelection)
        self.hist_tbl.setShowGrid(False)
        self.hist_tbl.setAlternatingRowColors(True)
        self.hist_tbl.setMaximumHeight(170)
        hh = self.hist_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, W.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, W.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, W.QHeaderView.Stretch)
        hh.setSectionResizeMode(3, W.QHeaderView.Fixed)
        self.hist_tbl.setColumnWidth(3, 30)
        self.hist_tbl.setSortingEnabled(True)

        self.res_stack = W.QStackedWidget()
        self.res_stack.addWidget(self.results)      # page 0: typeahead
        self.res_stack.addWidget(self.hist_tbl)     # page 1: history picker
        self.res_stack.setMaximumHeight(170)
        self.res_stack.setVisible(False)
        root.addWidget(self.res_stack)

    def _build_header(self, root: W.QLayout):
        self.head = W.QLabel('Search or paste a link to start')
        hf = self.head.font()
        hf.setPointSize(hf.pointSize() + 2)
        self.head.setFont(hf)
        hrow = W.QHBoxLayout()
        hrow.addWidget(self.head, 1)
        self.cast_btn = W.QPushButton('👥 Cast')
        self.cast_btn.setToolTip(
            'Characters: names (incl. Chinese), roles, voice actors and a '
            'link per character (AniList + Bangumi). Opens from cache, '
            'refreshes in the background.')
        self.cast_btn.setEnabled(False)
        hrow.addWidget(self.cast_btn)
        self.add_btn = W.QPushButton('＋ Simkl list')
        self.add_btn.setToolTip(
            'Add the current show to your Simkl Watching list '
            '(it then appears in the calendar)')
        hrow.addWidget(self.add_btn)
        root.addLayout(hrow)
        self.link_lbl = W.QLabel('')
        self.link_lbl.setTextInteractionFlags(C.Qt.TextBrowserInteraction)
        self.link_lbl.setOpenExternalLinks(True)
        root.addWidget(self.link_lbl)

    def _build_options(self, root: W.QLayout):
        self.opts_form = OptionsForm()
        root.addWidget(self.opts_form)

    def _build_episodes(self, root: W.QLayout, outer: W.QLayout):
        self.ebox = W.QGroupBox('Episodes')
        ev = W.QVBoxLayout(self.ebox)
        self.table = W.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['#', 'Episode name'])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, W.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, W.QHeaderView.Stretch)
        ev.addWidget(self.table)
        root.addWidget(self.ebox, 1)

    def _build_status(self, root: W.QLayout):
        self.status = W.QLabel('idle')
        root.addWidget(self.status)

    def _build_log(self, root: W.QLayout):
        lbox = W.QGroupBox('Log')
        lv = W.QVBoxLayout(lbox)
        self.logbox = LogView()
        lv.addWidget(self.logbox)
        if _log.HISTORY:
            self.logbox.seed(list(_log.HISTORY))
        root.addWidget(lbox)

    def _build_buttons(self, root: W.QLayout):
        bar = W.QHBoxLayout()
        self.b_from = W.QPushButton('▶  Play from here')
        self.b_sel = W.QPushButton('▶  Only selected')
        self.b_all = W.QPushButton('▶  All')
        self.b_stop = W.QPushButton('■  Stop')
        self.b_close = W.QPushButton('Close')
        for b in (self.b_from, self.b_sel, self.b_all, self.b_stop):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self.b_close)
        root.addLayout(bar)

    def _timers(self):
        # search debouncer + queue poller
        self.debounce = C.QTimer()
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(350)
        self.poll = C.QTimer()
        self.poll.setInterval(150)
        # sidebar refresh shortly after a sync lands (history/feed changed)
        self.side_timer = C.QTimer()
        self.side_timer.setSingleShot(True)
        self.side_timer.setInterval(1500)
        self.log_timer = C.QTimer()
        self.log_timer.timeout.connect(self._drain_log)
        self.log_timer.start(250)
        self.st_timer = C.QTimer()
        self.st_timer.timeout.connect(self._refresh_status)
        self.st_timer.start(1000)

    def _connect(self):
        self.box.textChanged.connect(self._on_text)
        self.box.returnPressed.connect(self._accept_typed)
        self.debounce.timeout.connect(
            lambda: self._run_search(self.box.text().strip()))
        self.poll.timeout.connect(self._drain_search)
        self.poll.start()
        self.results.itemClicked.connect(self._pick_result)
        self.results.itemActivated.connect(self._pick_result)
        self.results.setContextMenuPolicy(C.Qt.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self._results_menu)
        self.hist_btn.clicked.connect(lambda *_: self.show_history(force=True))
        self.hist_tbl.cellClicked.connect(self._hist_click)
        self.feed_filter.currentTextChanged.connect(
            lambda _t: self._render_feed())
        for t in (self.feed, self.hist):
            t.setContextMenuPolicy(C.Qt.CustomContextMenu)
            t.customContextMenuRequested.connect(
                lambda pos, tab=t: self._context(tab, pos))
        self.feed.itemDoubleClicked.connect(
            lambda it: self.load_entry(self._row_entry(self.feed, it)))
        self.hist.itemDoubleClicked.connect(
            lambda it: self.load_entry(self._row_entry(self.hist, it)))
        self.b_from.clicked.connect(self._from_here)
        self.b_sel.clicked.connect(self._only_sel)
        self.b_all.clicked.connect(lambda: self._do_play(self._all_nums()))
        self.b_stop.clicked.connect(self._do_stop)
        self.b_close.clicked.connect(self.close_window)
        self.add_btn.clicked.connect(self.add_current)
        self.cast_btn.clicked.connect(self._show_cast)
        self.side_btn.clicked.connect(self.load_side)
        self.poll.timeout.connect(self._drain_lib)

    # --- playback -------------------------------------------------------
    def _current_sel(self) -> List[int]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [int(self.table.item(r, 0).data(C.Qt.UserRole)) for r in rows
                if self.table.item(r, 0)]

    def _focus_num(self) -> Optional[int]:
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return int(it.data(C.Qt.UserRole)) if it else None

    def _all_nums(self) -> List[int]:
        return [int(self.table.item(r, 0).data(C.Qt.UserRole))
                for r in range(self.table.rowCount())]

    def _apply_opts(self):
        s = self.state['session']
        return self.opts_form.to_raw(s)          # shared options model

    def _do_play(self, chosen):
        s = self.state['session']
        if s is None or not chosen:
            return
        if self.state.get('playing'):
            return                                # one video at a time
        o, m = self._apply_opts()
        self.state['playing'] = True
        self.state['msg'] = 'starting…'
        if self._one_shot:
            try:
                s.play(chosen, o, m)
            finally:
                self.state['playing'] = False
            self.close_window()
            return

        def run():
            try:
                s.play(chosen, o, m)
                self.state['msg'] = ''
            except Exception as ex:
                self.state['msg'] = f'error: {ex}'
            finally:
                self.state['playing'] = False
        threading.Thread(target=run, daemon=True).start()

    def _from_here(self):
        f = self._focus_num()
        if f is not None:
            self._do_play([n for n in self._all_nums() if n >= f])

    def _only_sel(self):
        sel = self._current_sel()
        f = self._focus_num()
        self._do_play(sel if sel else
                      ([f] if f is not None else self._all_nums()))

    def _do_stop(self):
        s = self.state['session']
        if s:
            try:
                s.stop()
            except Exception:
                pass
        self.state['msg'] = 'stopped'

    def set_session(self, s):
        old = self.state['session']
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self.state['session'] = s
        self.state['msg'] = ''
        self.head.setText(s.title or 'tgplay')
        self.cast_btn.setEnabled(True)
        self.link_lbl.setText(
            f'<a href="{s.link}">{s.link}</a>' if s.link else '')
        self.opts_form.load(s)                    # shared options form
        # episodes
        nums = sorted(s.labels)
        self.table.setRowCount(0)
        self.table.setRowCount(len(nums))
        for i, n in enumerate(nums):
            it0 = W.QTableWidgetItem(str(n))
            it0.setData(C.Qt.UserRole, n)
            it0.setTextAlignment(C.Qt.AlignRight | C.Qt.AlignVCenter)
            self.table.setItem(i, 0, it0)
            self.table.setItem(i, 1, W.QTableWidgetItem(
                s.labels.get(n, f'Episode {n}')))
        self.ebox.setTitle(f'Episodes ({len(nums)})')
        if nums:
            row = nums.index(s.resume[0]) if (s.resume and
                                              s.resume[0] in s.labels) else 0
            self.table.selectRow(row)
            self.table.setCurrentCell(row, 1)
            self.table.scrollToItem(self.table.item(row, 1))

    def load_target(self, src, target):
        if self.state.get('loading'):
            return                          # ignore repeat clicks while loading
        self.state['loading'] = True
        nice = (history.name_of(self._cfg, target)
                if self._cfg is not None else None) or target
        self.state['msg'] = f'loading  {nice} …'
        try:
            self.head.setText(f'loading  {nice} …')
        except Exception:
            pass

        def work():
            # the whole loader (catalogue, MAL/simkl lookups, title wait)
            # runs OFF the UI thread - the window stays responsive
            try:
                with _log.span('load') as sp:
                    sp.result(f'"{nice}"')
                    s = self._loader(src, target)
                self._libq.put(('loaded', src, target, s, None))
            except Exception as ex:
                self._libq.put(('loaded', src, target, None, ex))
        threading.Thread(target=work, daemon=True).start()

    def _apply_loaded(self, src, target, s, ex):
        """GUI-thread completion of load_target (delivered via _libq)."""
        self.state['loading'] = False
        if ex is not None:
            dead = self._gate_dead(str(src), str(target), ex)
            self.state['msg'] = (f'AnimeGate session dead ({dead}) - links '
                                 'need a new login; re-choose after signing in'
                                 if dead else f'error: {ex}')
            # keep the results list visible: the user picks another
            # source / season from the same list (no random pick); the
            # app keeps working with the data it has (results, history,
            # last session) while authentication is down
            for r in range(self.results.count()):
                if self.results.item(r).data(C.Qt.UserRole) == str(target):
                    self.results.setCurrentRow(r)
                    break
            self.results.setVisible(True)
            self.res_stack.setVisible(True)
            self.res_stack.setCurrentWidget(self.results)
            if dead:
                self._gate_auth_flow(src, target, dead)
            return
        self.set_session(s)
        if self._cfg is not None:
            history.add(self._cfg, link=target, name=s.title)
        # success: tidy the results area (the session is up in its place)
        self.box.blockSignals(True)
        self.box.clear()
        self.box.blockSignals(False)
        self._fill_results([])
        self.state['msg'] = ''

    # --- auth health (AnimeGate cookie session) -------------------------
    _GATE_MARKERS = (r'logged out|cookie expired|no csrf token|'
                     r'no links \(logged|no firefox cookies|'
                     r'HTTP Error (401|403)')

    @classmethod
    def _gate_dead(cls, src: str, target: str, ex) -> Optional[str]:
        """A reason string when a load failed ONLY because the AnimeGate
        cookie session is dead (so the user is asked to re-authenticate)."""
        if 'animegate' not in f'{src} {target}'.lower():
            return None
        m = str(ex)
        return m if re.search(cls._GATE_MARKERS, m, re.I) else None

    def _gate_auth_flow(self, src, target, dead: str):
        """Ask the user to open the AnimeGate login page and re-authenticate;
        once signed in, one click reloads the show with fresh cookies.
        While auth stays unavailable the app works with its cache."""
        self.state['gate_last'] = (src, target)
        C.QTimer.singleShot(0, self._gate_nag)

    def _gate_nag(self):
        from .providers.animegate import GateAuth
        if self.state.get('gate_nagged'):
            return
        self.state['gate_nagged'] = True
        box = W.QMessageBox(self)
        box.setWindowTitle('AnimeGate login expired')
        box.setText('AnimeGate reports the browser session is logged out,\n'
                    'so its links are dead until you authenticate again.')
        box.setInformativeText(
            'Open the login page and sign in - tgplay re-reads the cookies\n'
            'on the next load. Until then it keeps working with the data it\n'
            'has (results, history, the last loaded show, cache).')
        b_open = box.addButton('🌐 Open AnimeGate login',
                               W.QMessageBox.AcceptRole)
        box.addButton('Continue with cache', W.QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_open:
            try:
                GateAuth().open_login()
            except Exception as ex:
                self.state['msg'] = f'error: {ex}'
            W.QMessageBox.information(
                self, 'After signing in…',
                'Log in to AnimeGate in Firefox, then press OK.\n'
                'The show reloads with fresh cookies.')
            self._gate_retry()

    def _gate_retry(self):
        """Re-run the last failed AGP target (fresh cookie read)."""
        last = self.state.get('gate_last')
        if last is not None:
            self.load_target(*last)

    def _gate_health(self):
        def work():
            try:
                from .providers.animegate import GateAuth
                ok, reason = GateAuth().alive()
            except Exception as ex:
                ok, reason = True, f'check failed ({ex})'
            self._libq.put(('gate-health', ok, reason))
        threading.Thread(target=work, daemon=True).start()

    # --- search ---------------------------------------------------------
    def _typed(self) -> str:
        """The search box text, normalized: '2 lines'/wrapping collapsed,
        a separator/newline-free single line."""
        return ' '.join(self.box.text().split()).strip()

    def _run_search(self, text):
        def work():
            try:
                from .finder import ShowFinder
                with _log.span('search') as s:
                    items = ShowFinder(self._cfg, self._http).find(
                        title=text) or []
                    s.result(f'{len(items)} hit(s)')
                self._rq.put(items)
            except Exception:
                self._rq.put([])
        threading.Thread(target=work, daemon=True).start()

    def _fill_results(self, items):
        self.results.clear()
        self.res_stack.setCurrentWidget(self.results)
        for e in items:
            kind = e.get('kind') or 'result'
            title = e.get('title', '')
            it = W.QListWidgetItem()
            if kind == 'query':
                it.setText(f'🔎  {title}     ·     recent search')
            else:
                url = e.get('url')
                tag = ' · ✓ same id' if e.get('matched') == 'id' else ''
                # show the anime name — the raw link stays in the tooltip
                # and in the right-click 'Copy link / Open in browser'
                it.setText(f"{title}     ·     {e.get('source', '')}{tag}")
                if url:
                    it.setToolTip(str(url))
            it.setData(C.Qt.UserRole, e.get('url'))
            it.setData(C.Qt.UserRole + 1, e.get('source'))
            it.setData(C.Qt.UserRole + 2, title)
            it.setData(C.Qt.UserRole + 3, kind)
            it.setData(C.Qt.UserRole + 4, e.get('ids') or {})
            self.results.addItem(it)
        self.results.setVisible(bool(items))
        self.res_stack.setVisible(bool(items))

    def _on_text(self):
        from .cli_all import route
        t = self._typed()
        if not t:
            self.show_history()
            return
        r = route(t)
        if r:
            self._fill_results(
                [{'title': t, 'url': r[1], 'source': r[0]}])
            return
        self.debounce.start()

    def _results_menu(self, pos):
        """Right-click a result row: copy / open its link without loading."""
        it = self.results.itemAt(pos)
        if it is None:
            return
        url = it.data(C.Qt.UserRole)
        if not url:
            return
        menu = W.QMenu(self.results)
        a_copy = menu.addAction('⧉  Copy link')
        a_open = menu.addAction('🔗  Open in browser')
        pick = menu.exec(self.results.viewport().mapToGlobal(pos))
        if pick is None:
            return
        try:
            if pick == a_copy:
                W.QApplication.clipboard().setText(str(url))
                self.state['msg'] = f'link copied: {url}'
            elif pick == a_open:
                G.QDesktopServices.openUrl(C.QUrl(str(url)))
        except Exception as ex:
            self.state['msg'] = f'error: {ex}'

    def _drain_search(self):
        try:
            items = self._rq.get_nowait()
        except queue.Empty:
            return
        self._fill_results(items)

    def _pick_result(self, item):
        if item is None:
            return
        kind = item.data(C.Qt.UserRole + 3)
        if kind == 'query':                     # replay a past search
            self.box.setText(str(item.data(C.Qt.UserRole + 2)))
            return
        src = item.data(C.Qt.UserRole + 1) or 'agp'
        target = item.data(C.Qt.UserRole)
        if target:
            from .cli_all import route
            q = self._typed()
            if self._cfg is not None and q and not route(q):
                history.add(self._cfg, query=q)
            elif self._cfg is not None and not q:
                history.add(self._cfg, link=target)  # record it NOW
            self._pin_ids(item, str(target))
            # keep the results list visible: if this source has nothing
            # playable (NoServersYet), the user picks the next row
            self.load_target(str(src), str(target))

    def _pin_ids(self, item, target: str):
        """Write the candidate's MAL id onto the link BEFORE loading, so
        open_session paints episode names from the RIGHT entry — not from a
        fuzzy title guess of some other season."""
        try:
            ids = item.data(C.Qt.UserRole + 4)
        except Exception:
            ids = None
        if not ids or self._cfg is None:
            return
        try:
            from .finder import ShowFinder
            ShowFinder(self._cfg, self._http).pin({'url': target, 'ids': ids})
        except Exception:
            pass

    def _accept_typed(self):
        from .cli_all import route
        t = self._typed()
        r = route(t)
        if r:
            self.load_target(r[0], r[1])
            return
        n = self.results.currentRow()
        if n < 0 and self.results.count():
            n = 0
        if n >= 0:
            self._pick_result(self.results.item(n))

    # --- local history picker ------------------------------------------
    def _hist_rows(self) -> List[dict]:
        items = history.recent(self._cfg) if self._cfg is not None else []
        filtered, seen = [], set()
        for e in items:                     # drop duplicate titles (same link
            if e['title'] in seen:          # can appear once per source)
                continue
            seen.add(e['title'])
            filtered.append(e)
        return filtered

    def show_history(self, force=False):
        sc = self.hist_tbl.horizontalHeader().sortIndicatorSection()
        so = self.hist_tbl.horizontalHeader().sortIndicatorOrder()
        self.hist_tbl.setSortingEnabled(False)
        self.hist_tbl.setRowCount(0)
        items = self._hist_rows()
        for e in items:
            r = self.hist_tbl.rowCount()
            self.hist_tbl.insertRow(r)
            it_d = _SortItem(_fmt_ts(e.get('ts')))
            it_d.setData(C.Qt.UserRole, str(e.get('ts') or 0))
            self.hist_tbl.setItem(r, 0, it_d)
            src = 'search' if e['kind'] == 'query' else str(
                e.get('source') or 'link')
            self.hist_tbl.setItem(r, 1, W.QTableWidgetItem(src))
            it_l = _SortItem(e['title'])
            it_l.setData(C.Qt.UserRole, e['title'])   # sort by the shown name
            it_l.setData(C.Qt.UserRole + 1, e)
            it_l.setToolTip(str(e.get('url') or e['title']))  # raw link here
            self.hist_tbl.setItem(r, 2, it_l)
            x = W.QToolButton()
            x.setText('✕')
            x.setToolTip('remove from history')
            x.clicked.connect(
                lambda _c=False, row=r, ent=e: self._hist_del(row, ent))
            self.hist_tbl.setCellWidget(r, 3, x)
        if not items:
            self.hist_tbl.insertRow(0)
            self.hist_tbl.setItem(0, 2, W.QTableWidgetItem('no history yet'))
        self.hist_tbl.setSortingEnabled(True)
        if sc < 0:
            self.hist_tbl.sortItems(0, C.Qt.DescendingOrder)  # newest first
        else:
            self.hist_tbl.sortItems(sc, so)       # keep the user's sort
        self.res_stack.setCurrentWidget(self.hist_tbl)
        self.res_stack.setVisible(bool(items) or force)

    def _hist_del(self, _row, e):
        try:
            if e['kind'] == 'query':
                history.remove(self._cfg, query=e['title'])
            else:
                history.remove(self._cfg, link=e['url'])
        except Exception:
            pass
        self.show_history(force=True)

    def _hist_click(self, row, col):
        if col == 3:
            return
        it = self.hist_tbl.item(row, 2)
        e = it.data(C.Qt.UserRole + 1) if it else None
        if not e:
            return
        if e['kind'] == 'query':                # replay a past search
            self.box.setText(e['title'])
            return
        if self._cfg is not None:
            history.add(self._cfg, link=e['url'])    # record NOW
        self.box.clear()
        self.load_target(str(e.get('source') or 'agp'), str(e['url']))

    # --- library / sidebar ----------------------------------------------
    def _goto_ep(self, ep):
        if not ep:
            return
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and int(it.data(C.Qt.UserRole)) == int(ep):
                self.table.selectRow(r)
                self.table.setCurrentCell(r, 1)
                return                       # select only; Play buttons start it

    def load_entry(self, e):
        if not e:
            return
        self.state['msg'] = f"searching “{e['title']}” on our sources…"

        def work():
            # the row carries real ids (mal/anilist/simkl): the finder
            # searches by them (AnimeX answers by id exactly) and by the
            # site's own name forms from the Simkl record - no title guess.
            try:
                from .finder import ShowFinder
                res = ShowFinder(self._cfg, self._http).find(entry=e)
            except Exception:
                res = None
            if not res:                      # fallback: old name search
                try:
                    from .library import search_variants
                    res = search_variants(e['title'], self._http)
                except Exception:
                    res = None
            self._libq.put(('show-results', e, res))
        threading.Thread(target=work, daemon=True).start()

    def _probe_status(self):
        """Check Simkl/AnimeGate/AniList on a worker and light them up."""
        def work():
            try:
                from .status import StatusProbe
                items = StatusProbe(self._cfg, self._http).check_all()
            except Exception:
                items = []
            self._libq.put(('status', items))
        threading.Thread(target=work, daemon=True).start()

    def _status_clicked(self, item):
        """A light was clicked: do the matching fix (or explain it)."""
        key = item.get('fix') or item.get('key')
        if key == 'simkl':
            self._simkl_connect()
        elif key == 'gate':
            from .providers.animegate import GateAuth
            box = W.QMessageBox(self)
            box.setWindowTitle('AnimeGate')
            box.setText('AnimeGate session: ' + str(item.get('detail')))
            box.setInformativeText(
                'Log in to animegate in your browser (Firefox), then press OK\n'
                'and click ↻ to refresh. Until then links may be dead.')
            b = box.addButton('🌐 Open login page', W.QMessageBox.AcceptRole)
            box.addButton('Close', W.QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is b:
                try:
                    GateAuth().open_login()
                except Exception as ex:
                    self.state['msg'] = f'error: {ex}'
        else:
            W.QMessageBox.information(
                self, 'AniList tracking',
                'AniList progress sync is optional.\n\n'
                'It is configured with:  tgplay login\n'
                '(or AGP_ANILIST_TOKEN in the environment).\n\n'
                'Everything else works without it.')

    def _simkl_connect(self):
        from .simkl_account import SimklAccount
        dlg = SimklConnectDialog(SimklAccount(self._cfg, self._http),
                                 parent=self)
        if dlg.exec() == W.QDialog.Accepted:
            self.state['msg'] = 'Simkl connected'
            _log.cprint('simkl: connected from the window')
            self._probe_status()
            self.load_side()

    def _show_cast(self):
        """Open the cast dialog for the current show (cache-first, instant).

        The MAL id pinned by the id-first finder keys the character lookup;
        the dialog opens from characters.json immediately and refreshes +
        loads avatars on a background worker (never blocks the window)."""
        s = self.state['session']
        if s is None:
            self.state['msg'] = 'load a show first'
            return
        try:
            from .characters import CharactersService
            from .bangumi import Bangumi
            svc = CharactersService(self._cfg, self._http, bangumi=Bangumi())
        except Exception:
            svc = None
        mal = getattr(s, 'mal_id', None) or getattr(s.provider, 'mal_id', None)
        try:
            CastDialog(svc, mal, s.title, parent=self).exec()
        except Exception as ex:
            self.state['msg'] = f'cast: {ex}'

    def add_current(self):
        s = self.state['session']
        if s is None:
            self.state['msg'] = 'load a show first'
            return
        self.state['msg'] = f'adding “{s.title}” to Simkl…'

        def work():
            try:
                from .metadata import Metadata
                from .simkl_account import SimklAccount
                mal = getattr(s.provider, 'mal_id', None)
                if not mal:
                    mal = Metadata(self._cfg, self._http).resolve_mal(
                        s.title, ask=False)
                ids = {'mal': mal} if mal else {'title': s.title}
                ok = SimklAccount(self._cfg, self._http).add_to_list(
                    ids, 'watching')
                self.state['msg'] = ('added to Simkl list' if ok
                                     else 'could not add to Simkl (logged in?)')
                if ok:
                    self._libq.put(('feed-refresh',))
            except Exception as ex:
                self.state['msg'] = f'add failed: {ex}'
        threading.Thread(target=work, daemon=True).start()

    def load_side(self):
        self.feed.setSortingEnabled(False)
        self.feed.setRowCount(0)
        self.hist.setSortingEnabled(False)
        self.hist.setRowCount(0)
        self.feed.insertRow(0)
        self.feed.setItem(0, 2, W.QTableWidgetItem('loading…'))

        def work():
            acc = None
            try:
                from .simkl_account import SimklAccount
                acc = (SimklAccount(self._cfg, self._http)
                       if self._cfg is not None else None)
                connected = bool(acc and acc.logged_in())
            except Exception as ex:
                connected = False
                _log.cprint(f'feed: Simkl check failed ({ex})')
            if not connected:
                _log.cprint('feed: Simkl not connected - click the Simkl '
                            'light (↻ area, above) to sign in')
                self._libq.put(('feed', None, None))
                return
            try:
                from .library import overview
                with _log.span('feed') as s:
                    ov = overview(self._cfg, self._http)
                    cal, rem, rc = ov['cal'], ov['rem'], ov['hist']
                    s.result(f'{len(cal)} upcoming · {len(rem)} to-watch '
                             f'· {len(rc)} watched')
            except Exception as ex:
                _log.cprint(f'feed: fetch failed ({ex}) - press ↻ to retry')
                cal, rem, rc = [], [], []
            if not (cal or rem or rc) and acc is not None:
                # empty library OR a rejected token look the same from the
                # API (it swallows errors) - one cheap check tells them apart
                if acc.user() is None:
                    _log.cprint('feed: Simkl token rejected/expired - click '
                                'the Simkl light to sign in again')
                    self._libq.put(('feed', None, None))
                    return
                _log.cprint('feed: Simkl is connected but the library/'
                            'calendar came back empty')
            self._libq.put(('feed', {'cal': cal, 'rem': rem}, rc))
        threading.Thread(target=work, daemon=True).start()

    def _render_feed(self):
        cal = self.state.get('cal')
        rem = self.state.get('rem')
        self.feed.setSortingEnabled(False)
        self.feed.setRowCount(0)
        if cal is None and rem is None:
            self.feed.insertRow(0)
            self.feed.setItem(0, 2, W.QTableWidgetItem(
                'Simkl not connected — click the ● Simkl light above'))
            self.feed.setSortingEnabled(True)
            return
        mode = self.feed_filter.currentText()
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
            r = self.feed.rowCount()
            self.feed.insertRow(r)
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
            self.feed.setItem(r, 0, c0)
            c1 = _SortItem(str(e.get('next_ep') or ''))
            c1.setData(C.Qt.UserRole, int(e.get('next_ep') or 0))
            self.feed.setItem(r, 1, c1)
            ttl = e['title']
            if k == 'upcoming' and e.get('ep_title'):
                ttl = f"{e['title']} · {e['ep_title']}"
            elif k == 'remaining' and e.get('total'):
                ttl = f"{e['title']}  ({e.get('watched')}/{e.get('total')})"
            self.feed.setItem(r, 2, W.QTableWidgetItem(ttl))
        if not rows:
            self.feed.insertRow(0)
            self.feed.setItem(0, 2, W.QTableWidgetItem(
                'nothing here — try another filter or ↻ refresh'))
        self.feed.setSortingEnabled(True)

    def _drain_lib(self):
        while True:
            try:
                msg = self._libq.get_nowait()
            except queue.Empty:
                return
            if msg[0] == 'feed-refresh':
                self.load_side()
            elif msg[0] == 'status':
                items = msg[1] or []
                self.status_strip.set_items(items)
                if items:
                    _log.cprint('status: ' + ' · '.join(
                        f"{i.get('name')} {i.get('state')}"
                        for i in items))
            elif msg[0] == 'loaded':
                # async completion of load_target (worker -> GUI thread)
                self._apply_loaded(msg[1], msg[2], msg[3], msg[4])
            elif msg[0] == 'feed':
                _, payload, rc = msg
                if payload is None:
                    self.state['cal'] = self.state['rem'] = None
                else:
                    self.state['cal'] = payload.get('cal')
                    self.state['rem'] = payload.get('rem')
                self._render_feed()
                self.hist.setSortingEnabled(False)
                self.hist.setRowCount(0)
                if payload is None:
                    self.hist.insertRow(0)
                    self.hist.setItem(0, 2, W.QTableWidgetItem(
                        'Simkl not connected — click the ● Simkl light above'))
                    continue
                for e in rc:
                    r = self.hist.rowCount()
                    self.hist.insertRow(r)
                    c0 = _SortItem(str(e.get('last_watched'))[:10])
                    c0.setData(C.Qt.UserRole, str(e.get('last_watched') or ''))
                    c0.setData(C.Qt.UserRole + 1, e)
                    self.hist.setItem(r, 0, c0)
                    c1 = _SortItem(f"{e['watched']}/{e['total']}")
                    c1.setData(C.Qt.UserRole, int(e.get('watched') or 0))
                    self.hist.setItem(r, 1, c1)
                    self.hist.setItem(r, 2, W.QTableWidgetItem(e['title']))
                if not rc:
                    self.hist.insertRow(0)
                    self.hist.setItem(0, 2, W.QTableWidgetItem('no history'))
                self.hist.setSortingEnabled(True)
                self.hist.sortItems(0, C.Qt.DescendingOrder)  # newest first
            elif msg[0] == 'show-results':
                # sidebar click: show ALL matches (both sources) in the
                # results list instead of auto-loading one — the user picks
                # the source they want (agp / axp)
                _, entry, res = msg
                if not res:
                    self.state['msg'] = (f"not found on our sources: "
                                         f"{entry['title']}")
                    return
                self.box.blockSignals(True)
                self.box.setText(' '.join(str(entry['title']).split()))
                self.box.blockSignals(False)
                self._fill_results(res)
                best = str(res[0].get('source', '?')).upper()
                self.state['msg'] = (f"{len(res)} result(s) for "
                                     f"“{entry['title']}” — best match: {best}"
                                     "  ·  click the one you want")

            elif msg[0] == 'gate-health':
                ok, reason = msg[1], msg[2]
                if not ok:
                    self.state['msg'] = f'AnimeGate auth: {reason}'
                    C.QTimer.singleShot(0, self._gate_nag)

    @staticmethod
    def _row_entry(table, item):
        try:
            return table.item(item.row(), 0).data(C.Qt.UserRole + 1)
        except Exception:
            return None

    def _set_status(self, e, status):
        ids = {k: e[k] for k in ('mal', 'anilist', 'simkl') if e.get(k)}
        if not ids:
            self.state['msg'] = 'no id to update on Simkl'
            return
        self.state['msg'] = f'setting Simkl → {status}…'

        def work():
            try:
                from .simkl_account import SimklAccount
                ok = SimklAccount(self._cfg, self._http).add_to_list(
                    ids, status)
                self.state['msg'] = (f'Simkl → {status}' if ok
                                     else 'Simkl update failed (logged in?)')
                if ok:
                    self._libq.put(('feed-refresh',))
            except Exception as ex:
                self.state['msg'] = f'Simkl update failed: {ex}'
        threading.Thread(target=work, daemon=True).start()

    def _context(self, table, pos):
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
            self.load_entry(e)
        elif pick in acts:
            self._set_status(e, acts[pick])
        elif a_simkl is not None and pick == a_simkl:
            self._open_url(f"https://simkl.com/anime/{e['simkl']}")
        elif a_mal is not None and pick == a_mal:
            self._open_url(f"https://myanimelist.net/anime/{e['mal']}")

    @staticmethod
    def _open_url(u):
        try:
            G.QDesktopServices.openUrl(C.QUrl(u))
        except Exception:
            pass

    # --- log / status ---------------------------------------------------
    def _drain_log(self):
        if self.state['closing']:
            return
        lines = []
        while True:
            try:
                lines.append(self._lq.get_nowait())
            except queue.Empty:
                break
        if lines:
            for ln in lines:
                self.logbox.feed(ln)
            if any(('synced:' in ln) or ('marked ep' in ln) for ln in lines):
                self.side_timer.start()          # auto-refresh feed/history

    def _refresh_status(self):
        if self.state['closing']:
            return
        s = self.state['session']
        txt = s.status() if s is not None else ''
        if self.state.get('msg'):
            txt = self.state['msg']
        self.status.setText(txt or 'idle')

    # --- closing --------------------------------------------------------
    def close_window(self):
        if self.state['closing']:
            return
        self.state['closing'] = True
        for t in (self.debounce, self.poll, self.log_timer, self.st_timer,
                  self.side_timer):
            try:
                t.stop()
            except Exception:
                pass
        try:
            if self.state['session'] is not None:
                self.state['session'].close()
        except Exception:
            pass
        try:
            if _log.SINK is not None:
                _log.SINK = self._prev_sink
        except Exception:
            pass
        self.close()
        try:
            W.QApplication.instance().quit()
        except Exception:
            pass

    def closeEvent(self, ev):
        self.close_window()
        ev.accept()

    # --- run ------------------------------------------------------------
    def run(self, initial=None) -> int:
        """Seed, show, load `initial`, honour the AGP_GUI_TEST hook, exec."""
        self.show_history()
        self.box.setFocus()
        self.show()
        try:
            self.raise_()
            self.activateWindow()
        except Exception:
            pass
        self.load_side()

        C.QTimer.singleShot(4000, self._gate_health)   # one background check
        C.QTimer.singleShot(600, self._probe_status)   # lights on startup
        mode = os.environ.get('AGP_GUI_TEST')
        if initial:
            self.load_target(initial[0], initial[1])
        if mode == 'play':
            C.QTimer.singleShot(300, lambda: self._when_ready(self._from_here))
        elif mode == 'all':
            C.QTimer.singleShot(
                300, lambda: self._when_ready(
                    lambda: self._do_play(self._all_nums())))
        elif mode == 'close':
            C.QTimer.singleShot(300, self.close_window)
        return W.QApplication.instance().exec()

    def _when_ready(self, fn, tries=40):
        """Run fn once the async load landed (or the window is closing)."""
        if self.state.get('session') is not None or self.state.get('closing'):
            fn()
        elif tries > 0:
            C.QTimer.singleShot(100, lambda: self._when_ready(fn, tries - 1))


def app(loader: Callable[[str, str], object], cfg=None, one_shot: bool = False,
        initial=None) -> int:
    """Open the unified window. `loader(src, target)` returns a Session."""
    _app_main()
    win = MainWindow(loader, cfg=cfg, one_shot=one_shot)
    win.destroyed.connect(lambda *_: (_log.__setattr__('SINK', win._prev_sink)))
    return win.run(initial=initial)


class UnifiedWindow:
    """The ONE window controller (OOP facade over the unified GUI).

    Every entry point opens `tgplay`'s window through this object: the
    launcher (`tgplay`), and the per-source CLIs (`agp`, `axp`). It replaces
    the retired per-source controllers (tp/gui_qt.controller, tp/gui.controller):
    one Session per source, loaded in place by `loader(src, target)`.
    """

    def __init__(self, loader, cfg=None, initial=None, one_shot: bool = False):
        self.loader = loader
        self.cfg = cfg
        self.initial = initial
        self.one_shot = one_shot

    def run(self) -> None:
        """Open the window and block until it closes."""
        return app(loader=self.loader, cfg=self.cfg,
                   one_shot=self.one_shot, initial=self.initial)
