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
from typing import Callable, List, Optional, Tuple

from PySide6 import QtWidgets as W, QtCore as C, QtGui as G

from . import history
from . import log as _log
from . import watched as _watched
from .config import Config
from .options import PlaybackOptions, form_fields


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
        self.setMaximumHeight(112)
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
        # avatars: all rows that HAVE an image (novel wiki rosters can be
        # 250+ and Fandom only serves them with the wiki Referer set)
        for r in (rec or {}).get('rows') or []:
            if self._closing:
                return
            u = r.get('image')
            if u and u not in self._pix:
                data = self._dl(u, self._referer_for(r))
                if data:
                    self._q.put(('img', u, data))

    @staticmethod
    def _referer_for(row):
        """Fandom blocks direct image requests (403 'Just a moment...')
        unless the request carries the wiki's own Referer."""
        if (row or {}).get('from') == 'wiki' and (row or {}).get('wiki'):
            return f"https://{row['wiki']}.fandom.com/"
        return 'https://anilist.co/'

    @staticmethod
    def _dl(url, referer=None):
        import urllib.request
        try:
            headers = {'User-Agent': ('Mozilla/5.0 (X11; Linux x86_64) '
                                      'Gecko/20100101 Firefox/130.0'),
                       'Accept': 'image/avif,image/webp,image/*,*/*;q=0.8'}
            if referer:
                headers['Referer'] = referer
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as r:
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
        self.status.setText('Simkl opened in your browser - press AUTHORIZE '
                            'there. This dialog closes itself when done; '
                            'the code below is only a fallback.')
        self._open()                     # the browser IS the login flow
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


def _cover_pixmap(pm, w, h, dpr=1.0):
    """Scale-crop a poster so it FILLS w×h.

    A QLabel draws a larger pixmap at full size, centred, and clips the
    overflow - which is why posters looked like a zoomed centre crop."""
    if pm is None or pm.isNull():
        return pm
    tw, th = max(1, round(w * dpr)), max(1, round(h * dpr))
    scaled = pm.scaled(tw, th, C.Qt.KeepAspectRatioByExpanding,
                       C.Qt.SmoothTransformation)
    out = scaled.copy(max(0, (scaled.width() - tw) // 2),
                      max(0, (scaled.height() - th) // 2), tw, th)
    out.setDevicePixelRatio(dpr)
    return out


class _ShelfCard(W.QFrame):
    """One poster card in the Continue-watching rail."""

    def __init__(self, item, on_click, on_menu):
        super().__init__()
        self.item = item
        self._click, self._menu = on_click, on_menu
        self.setFrameShape(W.QFrame.NoFrame)
        self.setCursor(C.Qt.PointingHandCursor)
        self.setStyleSheet('QFrame:hover { background:#2a2e32; '
                           'border-radius:8px; }')
        lay = W.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(3)
        self.poster = W.QLabel()
        self.poster.setFixedSize(92, 138)
        self.poster.setStyleSheet('background:#1b1e20; border-radius:6px;')
        self.poster.setAlignment(C.Qt.AlignCenter)
        self.poster.setText('…')
        lay.addWidget(self.poster)
        title = item.get('title') or ''
        lbl = W.QLabel(self.fontMetrics().elidedText(
            title, C.Qt.ElideRight, 118))
        lbl.setFixedWidth(118)
        lbl.setToolTip(title)
        lay.addWidget(lbl)
        total = item.get('total') or 0
        # the card is 118 px wide: only one line fits, so a recent card shows
        # what a recent card is for (age + how far behind), not a repeat of
        # the progress bar right under it
        if item.get('days_ago') is not None:
            d = int(item['days_ago'])
            sub = 'today' if d <= 0 else f'{d}d'
            if item.get('behind'):
                sub += f" · +{int(item['behind'])}"
            elif total:
                sub += f' · ep {item.get("next_ep")}/{total}'
        else:
            sub = (f"ep {item.get('next_ep')}" +
                   (f"/{total}" if total else '') +
                   f" · {float(item.get('pct') or 0):.0f}%")
        s = W.QLabel()
        s.setFixedWidth(118)
        s.setStyleSheet('color:#888;')
        s.setToolTip(sub)
        s.setText(self.fontMetrics().elidedText(sub, C.Qt.ElideRight, 112))
        lay.addWidget(s)
        bar = W.QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(item.get('pct') or 0))
        bar.setTextVisible(False)
        bar.setFixedHeight(5)
        bar.setFixedWidth(118)
        lay.addWidget(bar)

    def set_poster(self, pm):
        self.poster.setPixmap(_cover_pixmap(
            pm, self.poster.width(), self.poster.height(),
            self.poster.devicePixelRatioF()))
        self.poster.setText('')

    def mousePressEvent(self, ev):
        if ev.button() == C.Qt.LeftButton:
            self._click(self.item)
        elif ev.button() == C.Qt.RightButton:
            self._menu(self.item, ev.globalPosition().toPoint())
        super().mousePressEvent(ev)


class ContinueShelf(W.QWidget):
    """The poster rail: 'Continue watching' | 'Recently aired', one click
    resumes.

    One fixed slot, two data lists: the exclusive rail buttons only change
    WHICH list the window feeds in (set_items draws whatever it is given),
    so nothing in the layout moves. The gear opens the rail settings.
    Data comes from tp/continuewatch (in progress) and tp/recent (recently
    aired). Click = resume via the last link you used for that show (falls
    back to the source chooser); right-click = choose a source explicitly."""

    MODES = (('continue', '▶  Continue watching', 'in progress'),
             ('recent', '🆕  Recently aired', 'recently aired'))

    def __init__(self, on_click, on_menu, parent=None, on_mode=None,
                 on_settings=None):
        super().__init__(parent)
        self._click, self._menu = on_click, on_menu
        self._on_mode, self._on_settings = on_mode, on_settings
        self.mode = 'continue'
        self._items = []
        self._cards = {}          # image url -> [cards]
        self._px = {}             # image url -> QPixmap (avoids re-download)
        self._collapsed = False
        outer = W.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        head = W.QHBoxLayout()
        self.rails = {}
        self._group = W.QButtonGroup(self)
        self._group.setExclusive(True)
        for key, label, _unit in self.MODES:
            b = W.QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setToolTip('Posters for ' + label.strip('▶🆕 ').lower())
            b.clicked.connect(lambda _c=False, k=key: self._pick(k))
            self._group.addButton(b)
            self.rails[key] = b
            head.addWidget(b)
        self.rails['continue'].setChecked(True)
        self.count = W.QLabel('')
        self.count.setStyleSheet('color:#888;')
        self.count.setFixedWidth(120)      # mode never shifts the gear/chevron
        head.addWidget(self.count)
        head.addStretch(1)
        self.gear = W.QToolButton()
        self.gear.setText('⚙')
        self.gear.setToolTip('poster rail settings')
        self.gear.clicked.connect(lambda: self._settings())
        head.addWidget(self.gear)
        self.toggle = W.QToolButton()
        self.toggle.setText('▾')
        self.toggle.setToolTip('collapse / expand the shelf')
        self.toggle.clicked.connect(self._toggle)
        head.addWidget(self.toggle)
        outer.addLayout(head)
        self.scroll = W.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(206)
        self.scroll.setVerticalScrollBarPolicy(C.Qt.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(C.Qt.ScrollBarAsNeeded)
        inner = W.QWidget()
        self.row = W.QHBoxLayout(inner)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(6)
        self.row.addStretch(1)
        self.scroll.setWidget(inner)
        outer.addWidget(self.scroll)

    def _unit(self) -> str:
        return next(u for k, _l, u in self.MODES if k == self.mode)

    def _pick(self, key):
        if key != self.mode:
            self.set_mode(key)

    def set_mode(self, key):
        """Switch rails: the window answers on_mode by feeding that list."""
        if key not in self.rails:
            key = 'continue'
        self.mode = key
        self.rails[key].setChecked(True)
        if self._on_mode is not None:
            self._on_mode(key)

    def _settings(self):
        if self._on_settings is not None:
            self._on_settings()

    def set_items(self, items):
        while self.row.count():
            it = self.row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        self._items = items or []
        self._cards = {}
        if not self._items:                 # keep the slot, say why it is empty
            empty = W.QLabel(
                'No new episodes in this window - widen the days in the gear '
                'settings' if self.mode == 'recent' else
                'Nothing in progress yet - play a show and it appears here')
            empty.setStyleSheet('color:#888; padding:16px;')
            self.row.addWidget(empty)
        for item in self._items:
            card = _ShelfCard(item, self._click, self._menu)
            u = item.get('image') or ''
            if u and u in self._px:
                card.set_poster(self._px[u])
            if u:
                self._cards.setdefault(u, []).append(card)
            self.row.addWidget(card)
        self.row.addStretch(1)
        self.count.setText(f'{len(self._items)}' if self._items else '')
        self.count.setToolTip(f'{len(self._items)} {self._unit()}'
                              if self._items else '')
        self.sync()

    def set_poster(self, url, pm):
        self._px[url] = pm
        for card in self._cards.get(url, []):
            card.set_poster(pm)

    def has_poster(self, url):
        return url in self._px

    def is_empty(self):
        return not self._items

    def _toggle(self):
        self._collapsed = not self._collapsed
        self.toggle.setText('▸' if self._collapsed else '▾')
        self.sync()

    def sync(self, results_visible=False):
        # only the user's own collapse toggle changes this slot; app state
        # never hides or grows it (that was the reflow bug)
        self.scroll.setVisible(not self._collapsed)


class RailsDialog(W.QDialog):
    """Rail + sidebar settings: three groups, OK saves, Cancel drops all.

    Values are clamped by tp.recent (days in 7/14/30, limit 1..50) before
    they reach ui.json, so a hand-edited file cannot break the rails.
    """

    def __init__(self, cfg, parent=None, focus=None, on_save=None):
        super().__init__(parent)
        from .recent import DAYS, load_rails
        self._cfg = cfg
        self._on_save = on_save
        self.rails = load_rails(cfg)
        self.setWindowTitle('Feed & poster settings')
        lay = W.QVBoxLayout(self)

        def spin(v):
            s = W.QSpinBox()
            s.setRange(1, 50)
            s.setValue(int(v))
            return s

        def days_cb(v):
            cb = W.QComboBox()
            cb.addItems([str(d) for d in DAYS])
            cb.setCurrentText(str(v))
            return cb

        cbox = W.QGroupBox('Continue watching')
        cf = W.QFormLayout(cbox)
        self.cont_limit = spin(self.rails['continue']['limit'])
        cf.addRow('Posters (limit)', self.cont_limit)

        rbox = W.QGroupBox('Recently aired')
        rf = W.QFormLayout(rbox)
        self.recent_days = days_cb(self.rails['recent']['days'])
        self.recent_limit = spin(self.rails['recent']['limit'])
        self.recent_new = W.QCheckBox('include new seasons of watched shows')
        self.recent_new.setChecked(
            self.rails['recent']['include_new_seasons'])
        rf.addRow('Window (days)', self.recent_days)
        rf.addRow('Posters (limit)', self.recent_limit)
        rf.addRow('', self.recent_new)

        sbox = W.QGroupBox('Sidebar')
        sf = W.QFormLayout(sbox)
        self.side_show = W.QCheckBox('show days since the episode aired')
        self.side_show.setChecked(self.rails['sidebar']['show_days'])
        self.side_days = days_cb(self.rails['sidebar']['days'])
        self.side_new = W.QCheckBox('include new seasons in Recent')
        self.side_new.setChecked(
            self.rails['sidebar']['include_new_seasons'])
        sf.addRow('', self.side_show)
        sf.addRow('Recent window (days)', self.side_days)
        sf.addRow('', self.side_new)

        for b in (cbox, rbox, sbox):
            lay.addWidget(b)
        bar = W.QHBoxLayout()
        bar.addStretch(1)
        self.ok_btn = W.QPushButton('OK')
        self.cancel_btn = W.QPushButton('Cancel')
        bar.addWidget(self.ok_btn)
        bar.addWidget(self.cancel_btn)
        lay.addLayout(bar)
        self.ok_btn.clicked.connect(self._ok)
        self.cancel_btn.clicked.connect(self.reject)
        if focus == 'sidebar':
            # a dialog this small needs no scrolling: focus says where you came in
            self.side_show.setFocus()

    def values(self) -> dict:
        return {'continue': {'limit': self.cont_limit.value()},
                'recent': {'days': int(self.recent_days.currentText()),
                           'include_new_seasons': self.recent_new.isChecked(),
                           'limit': self.recent_limit.value()},
                'sidebar': {'show_days': self.side_show.isChecked(),
                            'include_new_seasons': self.side_new.isChecked(),
                            'days': int(self.side_days.currentText())}}

    def apply(self):
        """Save (raises on a write failure) and tell the window to re-render."""
        from .recent import save_rails
        self.rails = save_rails(self._cfg, self.values())
        if self._on_save is not None:
            self._on_save(self.rails)
        return self.rails

    def _ok(self):
        try:
            self.apply()
        except Exception as ex:
            W.QMessageBox.warning(self, 'Settings',
                                  f'could not save the settings: {ex}')
            return
        self.accept()


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



def _fmt_size(b: int) -> str:
    """Episode file size, human readable ('2.1GB', '740MB'); '—' unknown."""
    b = int(b or 0)
    if not b:
        return '—'
    for unit, div in (('TB', 1024 ** 4), ('GB', 1024 ** 3), ('MB', 1024 ** 2),
                      ('KB', 1024)):
        if b >= div:
            return f'{b / div:.1f}{unit}'
    return f'{b}B'


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
        self.setMinimumWidth(250)
        self.horizontalHeader().setSectionResizeMode(
            len(cols) - 1, W.QHeaderView.Stretch)
        self.setSortingEnabled(True)


class OptionsForm(W.QWidget):
    """Union options panel, rendered from the ONE shared spec (tp.options).

    Every option keeps the same place in every source: quality/server, audio,
    skip, skip-toggle, fullscreen, pre-download next (+ 'start at cut'), Simkl
    sync, start at, finish at, cut seconds and extra mpv flags. Options the
    current source cannot use stay visible but disabled, so the panel never
    changes shape.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.box = W.QGroupBox('Playback options')
        form = W.QVBoxLayout(self.box)
        form.setSpacing(4)

        def combo(items=(), width=None):
            cb = W.QComboBox()
            cb.setEditable(False)
            cb.addItems(list(items))
            if width:
                cb.setMaximumWidth(width)
            return cb

        self.server_lbl = W.QLabel('Quality')
        self.server = combo(width=150)
        self.server.setToolTip('Server / rendition for this source (axp: '
                               'nero or yuki, agp: quality)')
        self.size_lbl = W.QLabel('Size')
        self.size_cb = combo(width=90)
        self.size_cb.setToolTip('Video size; follows the chosen quality')
        self.audio_lbl = W.QLabel('Audio')
        self.audio_cb = combo(['dub', 'sub', 'auto'], width=62)
        self.audio_cb.setToolTip('Audio track to ask the source for')
        self.skip_lbl = W.QLabel('Skip')
        self.skip = combo(['off', 'all', 'names', 'auto'], width=80)
        self.skip.setToolTip('off = never skip · all = chapters and ani-skip\n'
                             'names = only named intro/outro chapters\n'
                             'auto = only when the file carries the answer')
        self.toggle = W.QCheckBox('T toggle')
        self.toggle.setToolTip('Allow turning skip off in mpv with T')
        self.full = W.QCheckBox('fullscreen')
        self.full.setToolTip('Start mpv fullscreen (same as --fullscreen)')
        self.nxt = W.QCheckBox('next ep')
        self.nxt.setToolTip('Pre-download the next episode in the background')
        self.nowait = W.QCheckBox('at cut')
        self.nowait.setToolTip(
            'Start that download at (duration - Cut) instead of 60%')
        self.sync_cb = W.QCheckBox('Simkl sync')
        self.sync_cb.setChecked(True)
        self.sync_cb.setToolTip(
            'Off = never push watch progress to Simkl for this run')
        self.cut = W.QLineEdit()
        self.cut.setFixedWidth(70)
        self.cut.setPlaceholderText('0')
        self.cut.setToolTip('Stop every episode this many seconds before its '
                            'end. 0 or blank = play to the end.\n'
                            'Episode 1 uses Finish at instead when that is set.')
        self.start_at = W.QLineEdit()
        self.start_at.setFixedWidth(96)
        self.start_at.setPlaceholderText('sec or mm:ss')
        self.start_at.setToolTip('Begin the first episode here instead of the '
                                 'saved resume point.\n'
                                 'Seconds (180) or clock (3:00, 1:02:03). '
                                 'Blank = resume / normal.')
        self.finish_at = W.QLineEdit()
        self.finish_at.setFixedWidth(96)
        self.finish_at.setPlaceholderText('sec or mm:ss')
        self.finish_at.setToolTip('Stop the first episode at this absolute '
                                  'position.\n'
                                  'Seconds (600) or clock (10:00). '
                                  'Overrides Cut for episode 1. Blank = off.')
        self.extra = W.QLineEdit()
        self.extra.setPlaceholderText('--volume 80')
        self.extra.setToolTip('Anything else mpv accepts, space separated')
        self.samples = W.QPushButton('samples')
        self.samples.setToolTip('Insert a ready-made extra mpv flag')
        self._samples_menu()
        self.help_btn = W.QPushButton('?')
        self.help_btn.setFixedWidth(26)
        self.help_btn.setToolTip('What every option does')
        self.help_btn.clicked.connect(self._show_help)

        # row 1: per-source choices
        r1 = W.QHBoxLayout()
        r1.setSpacing(6)
        r1.addWidget(self.server_lbl)
        r1.addWidget(self.server, 1)
        r1.addWidget(self.size_lbl)
        r1.addWidget(self.size_cb, 0)
        r1.addWidget(self.audio_lbl)
        r1.addWidget(self.audio_cb)
        r1.addWidget(self.skip_lbl)
        r1.addWidget(self.skip)
        form.addLayout(r1)
        # row 2: run-wide flags
        r2 = W.QHBoxLayout()
        r2.setSpacing(10)
        for w in (self.toggle, self.full, self.sync_cb, self.nxt, self.nowait):
            r2.addWidget(w)
        r2.addStretch(1)
        form.addLayout(r2)
        # row 3: positions (own row so nothing is clipped)
        r3 = W.QHBoxLayout()
        r3.setSpacing(6)
        r3.addWidget(W.QLabel('Start at'))
        r3.addWidget(self.start_at)
        r3.addWidget(W.QLabel('Finish at'))
        r3.addWidget(self.finish_at)
        r3.addWidget(W.QLabel('Cut last N s'))
        r3.addWidget(self.cut)
        r3.addStretch(1)
        form.addLayout(r3)
        # row 4: free text
        r4 = W.QHBoxLayout()
        r4.setSpacing(6)
        r4.addWidget(W.QLabel('Extra mpv flags'))
        r4.addWidget(self.extra, 1)
        r4.addWidget(self.samples)
        r4.addWidget(self.help_btn)
        form.addLayout(r4)

        self.box.setMinimumWidth(560)     # room for every row: no clipping

        lay = W.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.box)
        # the per-session 'next' fraction is remembered when the form is
        # first filled (so an --next=45 CLI value survives untouched clicks)
        self._next_was = False
        self._next_orig = None
        self.server.currentIndexChanged.connect(self._on_source_changed)
        self.size_cb.currentIndexChanged.connect(self._on_size_changed)

    # --- samples / help ---------------------------------------------------
    SAMPLES = [
        ('Volume 80', '--volume 80'),
        ('Play at 1.25x', '--speed 1.25'),
        ('A/V delay 0.3 s', '--audio-delay=0.3'),
        ('Bigger subtitles', '--sub-font-size=48 --sub-border-size=3'),
        ('No window border', '--no-border'),
        ('Start muted', '--mute=yes'),
        ('More cache (300MB)', '--cache=yes --demuxer-max-bytes=300MiB'),
        ('Hardware decode', '--hwdec=auto-safe'),
        ('Loop this file', '--loop-file=inf'),
    ]

    def _samples_menu(self):
        menu = W.QMenu(self)
        for label, flags in self.SAMPLES:
            menu.addAction(label, lambda f=flags: self._add_flag(f))
        self.samples.setMenu(menu)

    def _add_flag(self, flags: str):
        now = self.extra.text().strip()
        if flags in now:
            return                      # already there: clicking twice is safe
        self.extra.setText(f'{now} {flags}'.strip())

    def _show_help(self):
        rows = [f"{f['label'].replace('  ', ' ')}:\n    {f.get('help', '')}"
                for f in form_fields() if f.get('help')]
        W.QMessageBox.information(self, 'Playback options — what each does',
                                  '\n\n'.join(rows))

    # --- session -> widgets --------------------------------------------
    def load(self, s):
        """Fill every widget from the Session's opts/mpv/groups.

        Same rules the old hand-built code used, via the shared model."""
        po = PlaybackOptions(s.opts, s.mpv) if s is not None \
            else PlaybackOptions.defaults()
        s_opts = s.opts if s is not None else {}
        labels = [str(g['label']) for g in s.groups] if s is not None else []
        # the session's Quality object renders the menu: axp splits its
        # labels into a server x size map, every other source lists labels
        q = getattr(s, 'quality', None)
        sources, axp_map = (q.menus(s.groups) if q is not None
                            else (labels, {}))
        is_axp = bool(axp_map)
        self.server.blockSignals(True)
        self.server.clear()
        self.server.addItems(sources)
        # size dropdown: all distinct renditions across every AnimeX server,
        # so the user can pick by size instead of by server name.
        all_quals = []
        for qs in axp_map.values():
            for q in qs:
                if q and q not in all_quals:
                    all_quals.append(q)
        self._axp_all_quals = all_quals
        self.size_cb.blockSignals(True)
        self.size_cb.clear()
        self.size_cb.addItems(all_quals or [''])
        self.size_cb.blockSignals(False)
        if sources and po.quality:
            # match either a full label or a bare source name
            key = str(po.quality).split()[0] if str(po.quality).split() else ''
            idx = next((i for i, l in enumerate(sources)
                        if key.lower() in l.lower() or
                        str(po.quality).lower() in l.lower()), 0)
            self.server.setCurrentIndex(idx)
            if is_axp:
                pref_q = None
                for q in all_quals:
                    if q.lower() in str(po.quality).lower():
                        pref_q = q
                        break
                if pref_q is None:
                    qs = axp_map.get(sources[idx], [])
                    pref_q = qs[0] if qs else None
                if pref_q is not None:
                    self.size_cb.setCurrentText(pref_q)
        self.server.blockSignals(False)
        self._axp_map = axp_map
        self._axp = is_axp
        # union panel: unusable-for-this-source rows stay in place, disabled
        has_server = bool(sources)
        self.server_lbl.setText('Source' if is_axp else 'Quality')
        for w in (self.server, self.server_lbl):
            w.setEnabled(has_server)
        self.server.setToolTip('' if has_server else
                               'This source offers no quality / server choice.')
        # size dropdown: only meaningful for AnimeX
        has_size = bool(is_axp and sources)
        self.size_lbl.setText('Size')
        for w in (self.size_cb, self.size_lbl):
            w.setEnabled(has_size)
        if not has_size:
            self.size_cb.setToolTip('Only AnimeX exposes rendition size.')
        has_audio = bool(s is not None and s.audio)
        for w in (self.audio_cb, self.audio_lbl):
            w.setEnabled(has_audio)
        if has_audio:
            self.audio_cb.setCurrentText(po.audio_mode)
        else:
            self.audio_cb.setToolTip('This source offers no dub / sub choice.')
        # skip / toggles / next / cut / extras
        self.skip.setCurrentText(
            s_opts.get('skip') if isinstance(s_opts.get('skip'), str)
            else 'all')
        self.toggle.setChecked(bool(s_opts.get('skip_toggle')))
        self.full.setChecked(po.fullscreen)
        self.nxt.setChecked(bool(po.next))
        self.nowait.setChecked(po.nowait)
        self.sync_cb.setChecked(po.sync == 'auto')
        self.cut.setText(str(po.cut or ''))
        self.start_at.setText('' if po.start is None else str(po.start))
        self.finish_at.setText('' if po.end is None else str(po.end))
        self.extra.setText(' '.join(po.extras))
        self._next_was = bool(po.next)
        self._next_orig = po.next if not isinstance(po.next, bool) else None

    def _on_source_changed(self, idx):
        if not getattr(self, '_axp', False):
            return
        src = self.server.currentText()
        qs = getattr(self, '_axp_map', {}).get(src, [])
        if qs:
            self.size_cb.blockSignals(True)
            if qs[0] in [self.size_cb.itemText(i)
                         for i in range(self.size_cb.count())]:
                self.size_cb.setCurrentText(qs[0])
            else:
                self.size_cb.addItem(qs[0])
                self.size_cb.setCurrentText(qs[0])
            self.size_cb.blockSignals(False)

    def _on_size_changed(self, idx):
        if not getattr(self, '_axp', False):
            return
        q = self.size_cb.currentText()
        for src, qs in getattr(self, '_axp_map', {}).items():
            if q in qs:
                if src != self.server.currentText():
                    self.server.blockSignals(True)
                    self.server.setCurrentText(src)
                    self.server.blockSignals(False)
                return

    def _sync_size_for_source(self, source, axp_map=None, preferred=None):
        axp_map = axp_map if axp_map is not None else getattr(self, '_axp_map', {})
        quals = axp_map.get(source, [])
        self.size_cb.blockSignals(True)
        self.size_cb.clear()
        self.size_cb.addItems(quals or [''])
        if preferred:
            # preferred is a full label or "source quality"
            for q in quals:
                if q and q.lower() in str(preferred).lower():
                    self.size_cb.setCurrentText(q)
                    break
        self.size_cb.blockSignals(False)

    # --- widgets -> legacy (opts, mpv) ---------------------------------
    def to_raw(self, s) -> tuple:
        po = PlaybackOptions(s.opts if s is not None else None)
        if self.server.isEnabled() and self.server.count():
            if getattr(self, '_axp', False):
                po.quality = (self.server.currentText() + ' ' +
                              self.size_cb.currentText()).strip()
            else:
                po.quality = self.server.currentText()
        if self.audio_cb.isEnabled():
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
        po.start = self.start_at.text().strip()
        po.end = self.finish_at.text().strip()
        import shlex
        try:
            words = shlex.split(self.extra.text())
        except ValueError:                       # unbalanced quote: keep raw
            words = self.extra.text().split()
        po.with_extras(words,
                       fullscreen=self.full.isChecked())
        return po.to_opts(), po.mpv()


class MainWindow(W.QWidget):
    """The one tgplay window: search, sessions, options, sidebar, log."""

    def __init__(self, loader: Callable, cfg=None, one_shot: bool = False):
        super().__init__()
        self._loader = loader
        self._cfg = cfg
        self._wcfg = cfg if cfg is not None else Config()
        # one hook for every watched change; Simkl sync attaches here later
        self.on_watched_changed = None
        self._one_shot = one_shot
        self.state: dict = {'session': None, 'closing': False, 'msg': '',
                            'loading': False, 'playing': False}

        from .http import HttpClient
        self._http = HttpClient()
        self._lq: 'queue.Queue' = queue.Queue()      # log lines
        self._rq: 'queue.Queue' = queue.Queue()      # search results
        self._libq: 'queue.Queue' = queue.Queue()    # sidebar payloads
        self._poster_pending = set()                 # shelf poster downloads
        # ONE tracking rig: the durable queue is the only write path, and the
        # registry decides which service gets each feature
        from .tracking import Tracking
        self._tr = Tracking(
            self._wcfg, self._http,
            on_status=lambda r: self._libq.put(('simkl-sync', r)))
        self._simkl_acc = self._tr.client
        self._simkl_queue = self._tr.queue
        self._syncer = self._tr.syncer
        from .simkl_account import STATUSES
        self.on_watched_changed = self._queue_watched
        self._prev_sink = _log.SINK
        _log.SINK = lambda s: self._lq.put(str(s))

        self.setWindowTitle('tgplay')
        self.setMinimumSize(1220, 940)
        self.resize(1360, 1000)
        ic = _app_icon()
        if ic is not None:
            self.setWindowIcon(ic)
        outer = W.QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        split = W.QSplitter(C.Qt.Horizontal, self)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(6)
        split.setStyleSheet('QSplitter::handle { background:#22262b; }')
        left = W.QWidget()
        root = W.QVBoxLayout(left)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        right = W.QWidget()
        right.setMinimumWidth(240)
        side = W.QVBoxLayout(right)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(8)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([1000, 320])
        self._split_h = split
        outer.addWidget(split)

        self._build_sidebar(side)
        # five fixed slots (owner-approved): nothing moves between states
        self._build_shelf(root)           # 1 posters
        self._build_search_options(root)  # 2 search | options
        self._build_lists(root)           # 3 results  \  splitter,
        self._build_show(root)            # 4 episodes /  drag to resize
        self._build_bottoms(root)         # 5 action bar

        self._apply_rails()               # Aired column per ui.json
        self._timers()
        self._connect()
        self._tab_chain()
        # restore after the first layout pass: sizes set before show() get
        # clamped by the not-yet-allocated splitter
        C.QTimer.singleShot(0, self._restore_window_state)
        self._split_h.splitterMoved.connect(
            lambda *_: self._sz_timer.start())      # debounced save
        C.QTimer.singleShot(0, self.box.setFocus)   # typing works immediately

    # --- widget construction -------------------------------------------
    def _build_sidebar(self, side: W.QLayout):
        def _refresh_all():
            self._probe_status()
            self._refresh_library()             # tooltip promises the calendar
        self.status_strip = StatusStrip(self._status_clicked, _refresh_all)
        side.addWidget(self.status_strip)
        fbox = W.QGroupBox('Feed · calendar  (click a header to sort)')
        fv = W.QVBoxLayout(fbox)
        frow = W.QHBoxLayout()
        frow.addWidget(W.QLabel('Show'))
        self.feed_filter = W.QComboBox()
        self.feed_filter.addItems(['Calendar', 'Today', 'Trending',
                                   'Remaining', 'All', 'Recent'])
        frow.addWidget(self.feed_filter)
        frow.addStretch(1)
        self.feed_gear = W.QToolButton()
        self.feed_gear.setText('⚙')
        self.feed_gear.setToolTip('feed & poster settings')
        self.feed_gear.clicked.connect(
            lambda: self._open_rails_dialog(focus='sidebar'))
        frow.addWidget(self.feed_gear)
        fv.addLayout(frow)
        self.feed = SortableTable(['Date', 'Ep', 'Title', 'Aired'])
        hh = self.feed.horizontalHeader()
        hh.setSectionResizeMode(2, W.QHeaderView.Stretch)
        hh.setSectionResizeMode(3, W.QHeaderView.ResizeToContents)
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

    def _build_shelf(self, root: W.QLayout):
        self._rails = {'continue': [], 'recent': []}   # one list per rail
        self.shelf = ContinueShelf(self._shelf_click, self._shelf_menu,
                                   on_mode=self._rail_mode,
                                   on_settings=self._open_rails_dialog)
        root.addWidget(self.shelf)

    # --- rail / sidebar settings (ui.json window.rails) -----------------
    def _rail_mode(self, mode):
        """A rail button was picked: feed the shelf THAT list only."""
        items = self._rails.get(mode) or []
        self.shelf.set_items(items)
        self._load_posters(items)

    def _recent_items(self, days, limit=None, include_new=True) -> List[dict]:
        """The Recent list cut to one view's window/flags (rail or sidebar)."""
        out = []
        for e in self.state.get('recent') or []:
            if e.get('days_ago', 10 ** 6) > days:
                continue
            started = bool(e.get('watched')) or (
                e.get('status') in ('watching', 'plantowatch')
                and (e.get('next_ep') or 0) >= 1)
            if not include_new and e.get('is_new_season') and not started:
                continue
            out.append(e)
        return out[:limit] if limit else out

    def _apply_rails(self, rails=None):
        from .recent import load_rails
        self._settings = rails or load_rails(self._cfg)
        self.feed.setColumnHidden(
            3, not self._settings['sidebar']['show_days'])

    def _open_rails_dialog(self, focus=None):
        if self._cfg is None:
            self.state['msg'] = 'settings need a config directory'
            return
        RailsDialog(self._cfg, self, focus=focus,
                    on_save=self._on_rails_saved).exec()

    def _on_rails_saved(self, rails):
        self._apply_rails(rails)
        self._refresh_library()      # new window/limits reach feed + rails

    def _build_search_options(self, root: W.QLayout):
        """Slot 2: search input + History (left), playback options (right)."""
        self.box = W.QLineEdit()
        self.box.setClearButtonEnabled(True)
        self.box.setMinimumHeight(34)
        self.box.setMinimumWidth(320)
        self.box.setPlaceholderText('Search or paste link')
        self.box.setToolTip('Search by name, paste a show link, or type '
                            '@channel for a Telegram channel  ·  /  focuses')
        # make the one place you type stand out from the dark panels
        self.box.setStyleSheet(
            'QLineEdit { background:#212832; border:1px solid #4a6b8a;'
            ' border-radius:7px; padding:5px 9px; }'
            'QLineEdit:focus { border:1px solid #86b0e0; background:#252d38; }')
        self.hist_btn = W.QPushButton('🕘 History')
        self.hist_btn.setToolTip(
            'Your recent links and searches, with their date and source.\n'
            'Click a header (Date/Source/Link) to sort · ✕ removes one entry.')
        srow = W.QHBoxLayout()
        srow.setSpacing(6)
        srow.addWidget(self.box, 1)
        srow.addWidget(self.hist_btn)
        self.search_hint = W.QLabel(
            'type a name, paste a link or @channel · Enter opens the source '
            'picker for the best match')
        self.search_hint.setStyleSheet('color:#888;')
        sbox = W.QVBoxLayout()
        sbox.setSpacing(4)
        sbox.addStretch(1)               # centre the field against the options
        sbox.addLayout(srow)
        sbox.addWidget(self.search_hint)
        sbox.addStretch(1)

        self.opts_form = OptionsForm()
        self.opts_form.setMinimumWidth(580)      # ~1 cm wider than its content
        band = W.QHBoxLayout()
        band.setSpacing(10)
        band.addLayout(sbox, 1)
        band.addWidget(self.opts_form, 0)
        root.addLayout(band)

    def _build_lists(self, root: W.QLayout):
        """Slot 3: search results / recent links - always in the same place."""
        self.list_head = W.QLabel('Results')
        hf = self.list_head.font()
        hf.setBold(True)
        self.list_head.setFont(hf)
        self.results = W.QListWidget()
        self.results.setMinimumHeight(150)

        self.hist_tbl = W.QTableWidget(0, 4)
        self.hist_tbl.setHorizontalHeaderLabels(['Date', 'Source', 'Link', ''])
        self.hist_tbl.verticalHeader().setVisible(False)
        self.hist_tbl.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.hist_tbl.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.hist_tbl.setSelectionMode(W.QAbstractItemView.SingleSelection)
        self.hist_tbl.setShowGrid(False)
        self.hist_tbl.setAlternatingRowColors(True)
        hh = self.hist_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, W.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, W.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, W.QHeaderView.Stretch)
        hh.setSectionResizeMode(3, W.QHeaderView.Fixed)
        self.hist_tbl.setColumnWidth(3, 30)
        self.hist_tbl.setSortingEnabled(True)

        self.res_stack = W.QStackedWidget()
        self.res_stack.addWidget(self.results)      # page 0: typeahead
        self.res_stack.addWidget(self.hist_tbl)     # page 1: recent links
        self.res_stack.setMinimumHeight(150)

        lbox = W.QVBoxLayout()
        lbox.setSpacing(4)
        lbox.addWidget(self.list_head)
        lbox.addWidget(self.res_stack, 1)

        split = W.QSplitter(C.Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(6)
        split.setStyleSheet('QSplitter::handle { background:#22262b; }')
        left = W.QWidget()
        left.setLayout(lbox)
        split.addWidget(left)
        self._split = split
        root.addWidget(split, 1)

    def _build_show(self, root: W.QLayout):
        """Slot 4: title + Cast + Simkl list, then the episode table."""
        self.head = W.QLabel('Search or paste a link to start')
        hf = self.head.font()
        hf.setPointSize(hf.pointSize() + 2)
        self.head.setFont(hf)
        self.cast_btn = W.QPushButton('👥 Cast')
        self.cast_btn.setToolTip(
            'Characters: names (incl. Chinese), roles, voice actors and a '
            'link per character (AniList + Bangumi). Opens from cache, '
            'refreshes in the background.')
        self.cast_btn.setEnabled(False)
        self.add_btn = W.QPushButton('＋ Simkl list')
        self.add_btn.setToolTip(
            'Add the current show to your Simkl Watching list '
            '(it then appears in the calendar)')
        hrow = W.QHBoxLayout()
        hrow.setSpacing(6)
        hrow.addWidget(self.head, 1)
        hrow.addWidget(self.cast_btn)
        hrow.addWidget(self.add_btn)
        self.link_lbl = W.QLabel('')
        self.link_lbl.setTextInteractionFlags(C.Qt.TextBrowserInteraction)
        self.link_lbl.setOpenExternalLinks(True)

        self.ebox = W.QGroupBox('Episodes')
        ev = W.QVBoxLayout(self.ebox)
        self.table = W.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['#', 'Episode name', 'Size'])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(140)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, W.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, W.QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, W.QHeaderView.ResizeToContents)
        ev.addWidget(self.table)

        sh = W.QVBoxLayout()
        sh.setSpacing(4)
        sh.addLayout(hrow)
        sh.addWidget(self.link_lbl)
        sh.addWidget(self.ebox, 1)
        show = W.QWidget()
        show.setLayout(sh)
        self._split.addWidget(show)
        self._split.setStretchFactor(0, 1)
        self._split.setStretchFactor(1, 1)
        self._split.setSizes([280, 380])

    def _build_bottoms(self, root: W.QLayout):
        """Slot 5: the only row at the bottom of the window."""
        self.status = W.QLabel('idle')
        bar = W.QHBoxLayout()
        bar.setSpacing(6)
        self.b_stop = W.QPushButton('■  Stop')
        self.b_close = W.QPushButton('Close')
        for b in (self.b_stop,):
            b.setEnabled(False)                  # enabled by set_session
            bar.addWidget(b)
        bar.addWidget(self.status, 1)
        bar.addWidget(self.b_close)
        root.addLayout(bar)

    def _tab_chain(self):
        """Keyboard order follows the visual flow, not widget creation order."""
        chain = [self.box, self.hist_btn, self.results, self.hist_tbl,
                 self.table, self.opts_form.server, self.opts_form.audio_cb,
                 self.opts_form.skip, self.opts_form.toggle, self.opts_form.full,
                 self.opts_form.sync_cb, self.opts_form.nxt,
                 self.opts_form.nowait, self.opts_form.start_at,
                 self.opts_form.finish_at, self.opts_form.cut,
                 self.opts_form.extra,
                 self.cast_btn, self.add_btn, self.b_stop, self.b_close,
                 self.feed, self.hist, self.side_btn]
        for a, b in zip(chain, chain[1:]):
            W.QWidget.setTabOrder(a, b)
        for seq in ('/', 'Ctrl+F'):          # jump back to search from anywhere
            sc = G.QShortcut(G.QKeySequence(seq), self)
            sc.activated.connect(self._focus_search)

    # --- window layout memory -------------------------------------------
    def _restore_window_state(self):
        """Left/sidebar widths from the last run (ui.json -> 'window')."""
        try:
            from .config import load_json
            d = load_json(self._cfg.ui) if self._cfg is not None else {}
            sizes = ((d or {}).get('window') or {}).get('split') or []
            sizes = [int(x) for x in sizes if int(x) > 0]
            if len(sizes) == 2:
                self._split_h.setSizes(sizes)
        except Exception:
            pass

    def _remember_window_state(self):
        if self._cfg is None:
            return
        try:
            from .config import load_json, save_json
            d = load_json(self._cfg.ui)
            if not isinstance(d, dict):
                d = {}
            win = d.get('window') if isinstance(d.get('window'), dict) else {}
            win['split'] = list(self._split_h.sizes())
            d['window'] = win                # keep rails (and anything older)
            save_json(self._cfg.ui, d)
        except Exception:
            pass

    def _focus_search(self):
        self.box.setFocus()
        self.box.selectAll()

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
        self._sz_timer = C.QTimer()
        self._sz_timer.setSingleShot(True)
        self._sz_timer.setInterval(600)
        self._sz_timer.timeout.connect(self._remember_window_state)
        self.side_timer.setInterval(1500)
        self.side_timer.timeout.connect(self._refresh_library)
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
        self.b_stop.clicked.connect(self._do_stop)
        self.table.setContextMenuPolicy(C.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._ep_menu)
        self.table.itemDoubleClicked.connect(self._ep_play_here)
        self.b_close.clicked.connect(self.close_window)
        self.add_btn.clicked.connect(self.add_current)
        self.cast_btn.clicked.connect(self._show_cast)
        self.side_btn.clicked.connect(self._refresh_library)
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
                # watch marks + Simkl progress moved: reload the rails, feed
                # and history instead of leaving yesterday's rows on screen
                self._libq.put(('refresh',))
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

    # --- episode actions (right-click + double-click) --------------------
    def _ep_menu(self, pos):
        """Right-click an episode: watched, play modes, copy links, pages."""
        it = self.table.itemAt(pos)
        r = it.row() if it is not None else self.table.currentRow()
        if r >= 0:
            self.table.selectRow(r)
        sel = self._current_sel()
        nums = self._all_nums()
        num = None
        if r >= 0 and self.table.item(r, 0) is not None:
            num = int(self.table.item(r, 0).data(C.Qt.UserRole))
        menu = W.QMenu(self.table)
        wacts = {}
        if num is not None:
            wkey = self._wkey()
            st = _watched.state(self._wcfg, wkey)
            warm = menu.addMenu('👁  Watched')
            for kind, label, checked, enabled in _watched.rows(st, num, nums):
                a = warm.addAction(label)
                a.setEnabled(enabled)
                if kind in ('episode', 'series'):
                    a.setCheckable(True)
                    a.setChecked(checked)
                wacts[a] = kind
            menu.addSeparator()
        a_here = menu.addAction('▶  Play from here to the end')
        a_sel = menu.addAction(f'▶  Play only selected ({len(sel)})'
                               if sel else '▶  Play only this episode')
        a_all = menu.addAction(f'▶  Play all ({self.table.rowCount()})')
        menu.addSeparator()
        a_copy = menu.addAction('⧉  Copy episode link')
        menu.addSeparator()
        links = menu.addMenu('🌐  Show pages')
        page_items = self._page_links(self._show_title())
        acts = {}
        for label, url in page_items:
            acts[links.addAction(label)] = url
        pick = menu.exec(self.table.viewport().mapToGlobal(pos))
        if pick is None:
            return
        if pick in wacts:
            self._mark_watched(wacts[pick], num, nums)
        elif pick is a_here:
            self._from_here()
        elif pick is a_sel:
            self._only_sel()
        elif pick is a_all:
            self._do_play(self._all_nums())
        elif pick is a_copy:
            self._copy_ep_link(r)
        elif pick in acts:
            G.QDesktopServices.openUrl(C.QUrl(acts[pick]))

    def _wkey(self) -> str:
        """Watched-store key of the loaded show: simkl/mal id, else title."""
        s = self.state['session']
        if s is None:
            return ''
        return _watched.key_for(s.title, {
            'simkl': getattr(s, 'simkl_id', None),
            'mal': getattr(s, 'mal_id', None)})

    def _mark_watched(self, kind, num, nums):
        """Store + repaint + the one hook; the queue is the only writer."""
        if num is None:
            return
        wkey = self._wkey()
        forced = {'season': True, 'season_unwatched': False,
                  'till_here': True}.get(kind)
        kind, on = self._tr.watched.change(wkey, kind, num, nums, forced)
        self._paint_watched()
        if self.on_watched_changed is not None:
            self.on_watched_changed(kind, on,
                                    {'key': wkey, 'num': num,
                                     'nums': list(nums)})

    # --- Simkl sync (queue first, push on a worker) ----------------------
    def _sync_ids(self, key: str) -> dict:
        """Queue/pull ids from a store key ('simkl:1', 'mal:2', 't:title')."""
        k, _, v = (key or '').partition(':')
        if k in ('simkl', 'mal', 'anilist') and v.isdigit():
            return {k: int(v)}
        s = self.state['session']
        mal = getattr(s, 'mal_id', None) or getattr(
            getattr(s, 'provider', None), 'mal_id', None)
        simkl = getattr(s, 'simkl_id', None)
        ids = {'mal': mal} if mal else {}
        if simkl:
            ids['simkl'] = simkl
        return ids

    def _queue_watched(self, kind, watched, info):
        """A local watched change: queue it for every service (no network)."""
        ids = self._sync_ids(info.get('key') or '')
        if not ids:
            self.state['msg'] = 'watched locally; Simkl needs a Simkl/MAL id'
            return
        n = self._tr.watched.queue_change(kind, watched, info, ids)
        if not n:
            self.state['msg'] = 'watched locally; Simkl is not connected'
        self._syncer.wake()

    def _paint_watched(self):
        """Repaint the rows from the store: watched = tick + dim name."""
        if self.state['session'] is None:
            return
        eps = _watched.state(self._wcfg, self._wkey())['eps']
        dim = G.QColor('#8b9299')
        for i in range(self.table.rowCount()):
            it0 = self.table.item(i, 0)
            if it0 is None:
                continue
            n = int(it0.data(C.Qt.UserRole))
            on = n in eps
            it0.setText(f'✓ {n}' if on else str(n))
            it = self.table.item(i, 1)
            if it is not None:
                it.setForeground(G.QBrush(dim) if on else G.QBrush())

    def _ep_play_here(self, item):
        if item is not None:
            self.table.selectRow(item.row())
        self._from_here()

    def _copy_ep_link(self, row):
        s = self.state['session']
        it = self.table.item(row, 0) if row >= 0 else None
        num = int(it.data(C.Qt.UserRole)) if it is not None else None
        if s is None or num is None:
            return

        def work():
            try:
                st = s.provider.stream(num)
                url = getattr(st, 'url', None) or ''
                title = s.title
                self._libq.put(('copied-ep', url, title, num))
            except Exception as ex:
                self._libq.put(('copied-ep', '', f'link failed ({ex})', num))
        self.state['msg'] = f'resolving ep{num} link…'
        threading.Thread(target=work, daemon=True).start()

    def _show_title(self):
        s = self.state['session']
        return (s.title if s is not None else '') or ''

    def _page_links(self, title, ids=None, mal=None):
        """Simkl / AniList / MAL / Fandom pages for a show (search when the
        id is not pinned). No network: ids or a search URL."""
        from urllib.parse import quote
        ids = dict(ids or {})
        s = self.state['session']
        mal = mal or ids.get('mal') or ids.get('malId') or ids.get('mal_id')
        if not mal and s is not None:
            mal = getattr(s, 'mal_id', None)
        al = ids.get('anilist') or ids.get('anilist_id') or ids.get('al')
        simkl = ids.get('simkl') or ids.get('simkl_id')
        q = quote(title or '')
        out = []
        if simkl:
            out.append(('Simkl', f'https://simkl.com/anime/{simkl}/'))
        elif q:
            out.append(('Simkl search', f'https://simkl.com/search/?q={q}'))
        if al:
            out.append(('AniList', f'https://anilist.co/anime/{al}'))
        elif q:
            out.append(('AniList search',
                        f'https://anilist.co/search/anime?search={q}'))
        if mal:
            out.append(('MyAnimeList', f'https://myanimelist.net/anime/{mal}'))
        elif q:
            out.append(('MyAnimeList search',
                        f'https://myanimelist.net/anime.php?q={q}'))
        if q:
            out.append(('Fandom search', f'https://www.fandom.com/?s={q}'))
        return out

    def _do_stop(self):
        s = self.state['session']
        if s:
            try:
                s.stop()
            except Exception:
                pass
        self.state['msg'] = 'stopped' if s else 'nothing playing'
        self.state['msg_until'] = time.time() + 5

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
        self.b_stop.setEnabled(True)
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
            self.table.setItem(i, 2, W.QTableWidgetItem(
                '—' if (getattr(s, 'sizes', None) is not None
                        and not s.sizes.capable) else '…'))
        self.ebox.setTitle(f'Episodes ({len(nums)})')
        self._paint_watched()                     # tick + dim the watched rows
        if nums:
            row = nums.index(s.resume[0]) if (s.resume and
                                              s.resume[0] in s.labels) else 0
            self.table.selectRow(row)
            self.table.setCurrentCell(row, 1)
            self.table.scrollToItem(self.table.item(row, 1))
        self._probe_sizes(s)

    def _probe_sizes(self, s):
        """Fill the Size column from the provider (AGP probes its signed
        CDN links in a background thread; Telegram/TGP know right away;
        AnimeX is HLS - no size)."""
        if s is None:
            return
        sz = getattr(s, 'sizes', None)
        if sz is not None and not sz.capable:
            return                       # HLS sources have no size to probe
        nums = sorted(s.labels)

        def work():
            for n in nums:
                if self.state.get('closing') or \
                        self.state['session'] is not s:
                    return                          # the show changed / closed
                try:
                    sz = int(s.provider.size(n) or 0)
                except Exception:
                    sz = 0
                self._libq.put(('size', s, n, sz))
        threading.Thread(target=work, daemon=True).start()

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
            auth, dead = self._auth_dead(str(src), str(target), ex)
            self.state['msg'] = (
                f'{auth.label} session dead ({dead}) - links '
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
            self.res_stack.setCurrentWidget(self.results)
            self.list_head.setText('Results')
            if dead:
                self._gate_auth_flow(auth, dead)
            return
        self.set_session(s)
        if self._cfg is not None:
            history.add(self._cfg, link=target, name=s.title)
        # success: the session is up in its place; the results list and the
        # typed query stay exactly as they were (nothing empties mid-window)
        self.state['msg'] = ''

    # --- auth health (per-source session-dead detection) ----------------
    @classmethod
    def _auth_dead(cls, src: str, target: str, ex
                   ) -> Tuple[Optional[type], Optional[str]]:
        """(Auth class, reason) when a load failed ONLY because one source's
        auth is dead (else (None, None)). The marker regexes live on the
        source's own Auth object - the GUI only scans the registry."""
        from . import features
        for acls in features.REGISTRY['auth'].values():
            reason = acls.dead(src, target, ex)
            if reason:
                return acls, reason
        return None, None

    def _gate_auth_flow(self, auth, dead: str):
        """Ask the user to open the source's login page and re-authenticate;
        once signed in, one click reloads the show with fresh credentials.
        While auth stays unavailable the app works with its cache."""
        self.state['gate_auth'] = auth
        C.QTimer.singleShot(0, self._gate_nag)

    def _gate_nag(self):
        auth = self.state.get('gate_auth')
        if auth is None or self.state.get('gate_nagged'):
            return
        self.state['gate_nagged'] = True
        box = W.QMessageBox(self)
        box.setWindowTitle(f'{auth.label} login expired')
        box.setText(f'{auth.label} reports the browser session is logged '
                    'out,\n'
                    'so its links are dead until you authenticate again.')
        box.setInformativeText(
            'Open the login page and sign in - tgplay re-reads the cookies\n'
            'on the next load. Until then it keeps working with the data it\n'
            'has (results, history, the last loaded show, cache).')
        b_open = box.addButton(f'🌐 Open {auth.label} login',
                               W.QMessageBox.AcceptRole)
        box.addButton('Continue with cache', W.QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_open:
            try:
                auth().open_login()
            except Exception as ex:
                self.state['msg'] = f'error: {ex}'
            W.QMessageBox.information(
                self, 'After signing in…',
                f'Log in to {auth.label} in Firefox, then press OK.\n'
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
        q = self._typed()
        self.state['msg'] = ''                 # 'searching …' is over
        self.state['msg_until'] = 0
        if items:
            self.list_head.setText(f'Results · {len(items)} for “{q}”')
        else:
            empty = W.QListWidgetItem('no matches — edit the text and press '
                                      'Enter, or paste a link')
            empty.setFlags(C.Qt.NoItemFlags)     # a message, not a choice
            self.results.addItem(empty)
            self.list_head.setText(f'Results · no hits for “{q}”' if q
                                   else 'Results · nothing yet')
            if q:
                self.state['msg'] = (f'no results for “{q}” — try another '
                                     'spelling, or paste a link')
                self.state['msg_until'] = time.time() + 8
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
        self.shelf.sync()      # the posters slot never moves

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
        menu.addSeparator()
        links = menu.addMenu('🌐  Show pages')
        pages = {}
        for label, u in self._page_links(it.text().split('  ·  ')[0],
                                         ids=it.data(C.Qt.UserRole + 4)):
            pages[links.addAction(label)] = u
        pick = menu.exec(self.results.viewport().mapToGlobal(pos))
        if pick is None:
            return
        try:
            if pick == a_copy:
                W.QApplication.clipboard().setText(str(url))
                self.state['msg'] = f'link copied: {url}'
            elif pick == a_open:
                G.QDesktopServices.openUrl(C.QUrl(str(url)))
            elif pick in pages:
                G.QDesktopServices.openUrl(C.QUrl(pages[pick]))
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
        has_pick = any(self.results.item(i).flags() & C.Qt.ItemIsEnabled
                       for i in range(self.results.count()))
        if not has_pick:                         # nothing to pick: search now
            if t:
                self.state['msg'] = f'searching “{t}” …'
                self.debounce.start()
            return
        n = self.results.currentRow()
        if n < 0:
            n = 0
        self._pick_result(self.results.item(n))

    # --- local history picker ------------------------------------------
    def _hist_rows(self) -> List[dict]:
        items = history.recent(self._cfg) if self._cfg is not None else []
        filtered, seen = [], set()
        for e in items:                     # dedupe by link, not by title:
            k = (e.get('title'), e.get('url') or e.get('source'))
            if k in seen:                   # two sources of one show are real
                continue
            seen.add(k)
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
        self.list_head.setText('Recent links & searches')
        if force:                       # asked for it: refresh Simkl too
            self._refresh_library()

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

    # --- continue-watching shelf ---------------------------------------
    def _load_posters(self, items):
        """Download shelf posters (Simkl/AniList CDN) on a worker thread."""
        todo = []
        for it in items or []:
            u = it.get('image')
            if not u or u in self._poster_pending or self.shelf.has_poster(u):
                continue
            self._poster_pending.add(u)
            todo.append(u)
        if not todo:
            return

        def work():
            import urllib.request
            for u in todo:
                try:
                    req = urllib.request.Request(
                        u, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=15) as r:
                        data = r.read()
                    self._libq.put(('poster', u, data))
                except Exception:
                    self._poster_pending.discard(u)
        threading.Thread(target=work, daemon=True).start()

    def _shelf_click(self, item):
        """One click resumes: the last link used for that show, else chooser."""
        from .cli_all import route
        link = (history.last_link_for(self._cfg, item.get('title'))
                if self._cfg is not None else None)
        r = route(link) if link else None
        if r:
            _log.cprint(f'continue: resuming “{item["title"]}” '
                        f'(ep {item.get("next_ep")})')
            self.load_target(r[0], r[1])
            return
        self.load_entry({'title': item.get('title'),
                         'mal': item.get('mal'), 'simkl': item.get('simkl')})

    def _shelf_menu(self, item, pos):
        from .cli_all import route
        menu = W.QMenu(self)
        link = (history.last_link_for(self._cfg, item.get('title'))
                if self._cfg is not None else None)
        r = route(link) if link else None
        a_resume = menu.addAction('▶  Resume' if r
                                  else '▶  Resume (no link yet)')
        a_resume.setEnabled(bool(r))
        a_pick = menu.addAction('🔎  Choose source…')
        pick = menu.exec(pos)
        if pick is a_resume and r:
            self.load_target(r[0], r[1])
        elif pick is a_pick:
            self.load_entry({'title': item.get('title'),
                             'mal': item.get('mal'),
                             'simkl': item.get('simkl')})

    def _probe_status(self):
        """Check Simkl/AnimeGate/AniList on a worker and light them up."""
        if getattr(self._syncer, 'auth_failed_recent', False):
            # the queue is failing on auth: the light must say the login is
            # dead and clicking it must offer the browser authorize FIRST
            self._libq.put(('status', [{'key': 'simkl', 'fix': 'simkl',
                                        'detail': 'login expired - '
                                                  're-authorize in browser'}]))
            return
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
            if self._simkl_acc.logged_in():
                self._simkl_menu()          # connected: pull / disconnect
            else:
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
            self._anilist_connect()

    def _anilist_connect(self):
        """Browser authorize: open the AniList approve page, paste the token
        back once (the page shows it after Authorize), validate + save."""
        try:
            from .tracking.anilist_client import Tracker
            tr = Tracker(self._cfg)
        except Exception as ex:
            self.state['msg'] = f'anilist: {ex}'
            return
        a = tr._auth() or {}
        cid = (os.environ.get('AGP_ANILIST_CLIENT_ID')
               or a.get('client_id'))
        if not cid:
            import webbrowser
            W.QMessageBox.information(
                self, 'AniList - one-time setup',
                'One time only: open anilist.co/settings/developer\n'
                '(it is opening for you), create an app with redirect\n'
                '  https://anilist.co/api/v2/oauth/pin\n'
                'and paste its CLIENT ID here. Never needed again.')
            webbrowser.open('https://anilist.co/settings/developer')
            cid, ok = W.QInputDialog.getText(
                self, 'AniList client id', 'client id:')
            if not ok or not cid.strip():
                return
            cid = cid.strip()
            a.update({'client_id': cid})
            from .config import save_json
            save_json(tr.cfg.anilist_auth, a)
        url = ('https://anilist.co/api/v2/oauth/authorize?client_id='
               f'{cid}&response_type=token')
        import webbrowser
        webbrowser.open(url)                 # the authorize page, never /pin
        tok, ok = W.QInputDialog.getMultiLineText(
            self, 'AniList authorization',
            'The AniList page is open.\n'
            'Press AUTHORIZE - it shows your access token.\n'
            'Copy that token here and press OK:', '')
        if not (ok and tok.strip()):
            return
        try:
            user = tr.login(client_id=cid, tok=tok.strip(),
                            open_browser=False)
        except Exception as ex:
            self.state['msg'] = f'anilist: {ex}'
            return
        if user:
            self.state['msg'] = f'AniList connected as {user["name"]}'
            _log.cprint(f'anilist: connected from the window as '
                        f'{user["name"]}')
            self._probe_status()
        else:
            self.state['msg'] = 'AniList: token rejected'

    def _simkl_connect(self):
        dlg = SimklConnectDialog(self._tr.client, parent=self)
        if dlg.exec() == W.QDialog.Accepted:
            self.state['msg'] = 'Simkl connected'
            _log.cprint('simkl: connected from the window')
            self._syncer.start()          # drain anything queued while offline
            threading.Thread(target=self._simkl_pull, daemon=True).start()
            self._probe_status()
            self.load_side()

    def _simkl_pull(self, keys=None):
        """Pull Simkl watched state into the local store (worker thread).

        The feature owns the merge, so a tombstoned unmark stays unmarked and
        its remove is queued.
        """
        try:
            added = self._tr.pull(id_map=self._sync_ids, keys=keys)
        except Exception as ex:
            _log.cprint(f'simkl: pull failed ({ex})')
            return
        if added:
            _log.cprint(f'simkl: pulled {added} watched ep(s)')
            self._libq.put(('watched-repaint',))

    def _simkl_menu(self):
        """Light clicked while connected: pull, rate/status the loaded show, or
        disconnect."""
        acc = self._simkl_acc
        menu = W.QMenu(self)
        # the browser-authorize entry is ALWAYS first: a token can die
        # server-side while the local file still exists, and then 'Pull'
        # silently 401s forever. Re-authorizing is always safe.
        a_auth = menu.addAction('🔗  Authorize in browser…')
        a_pull = menu.addAction('⬇  Pull watched state from Simkl')
        ids = self._show_ids()
        rate, status = {}, {}
        if ids:
            sub = menu.addMenu('★  Rate this show')
            for n in range(1, 11):
                rate[sub.addAction(f'{n}/10')] = n
            sub = menu.addMenu('☰  List status')
            for name in STATUSES:
                status[sub.addAction(name.replace('plantowatch',
                                                  'plan to watch'))] = name
        menu.addSeparator()
        a_off = menu.addAction('⏏  Disconnect Simkl')
        pick = menu.exec(G.QCursor.pos())
        if pick in rate:
            self._tr.ratings.rate(ids, rate[pick])
            self._syncer.wake()
            self._simkl_note(f'rated {rate[pick]}/10 (queued)')
        elif pick in status:
            self._tr.lists.set(ids, status[pick])
            self._syncer.wake()
            self._simkl_note(f'list: {status[pick]} (queued)')
        elif pick is a_auth:
            self._simkl_connect()
        elif pick is a_pull:
            self.state['msg'] = 'pulling watched state from Simkl…'
            threading.Thread(target=self._simkl_pull, daemon=True).start()
        elif pick is a_off:
            self._syncer.stop()
            acc.logout()
            self.state['msg'] = 'Simkl disconnected (queued changes kept)'
            self._probe_status()

    def _show_ids(self) -> dict:
        """Simkl/MAL ids of the loaded show, for one-shot Simkl writes."""
        try:
            return self._sync_ids(self._wkey() or '')
        except Exception:
            return {}

    def _simkl_note(self, msg):
        _log.cprint(msg)
        self._libq.put(('simkl-sync', {'msg': msg}))

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
            from .bangumi import Bangumi
            svc = self._tr.cast.service
            svc.bangumi = svc.bangumi or Bangumi()
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
                mal = getattr(s.provider, 'mal_id', None)
                if not mal:
                    mal = Metadata(self._cfg, self._http).resolve_mal(
                        s.title, ask=False)
                ids = {'mal': mal} if mal else {'title': s.title}
                ok = self._tr.lists.set(ids, 'watching')
                if ok:
                    self._syncer.wake()
                self.state['msg'] = ('added to Simkl list' if ok
                                     else 'could not add to Simkl (logged in?)')
                if ok:
                    self._libq.put(('feed-refresh',))
            except Exception as ex:
                self.state['msg'] = f'add failed: {ex}'
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _known_titles(rows) -> List[str]:
        """Titles he actually watched (any season) - 'new season' baseline."""
        out = []
        for r in rows or []:
            try:
                watched = int(r.get('watched') or 0)
            except (TypeError, ValueError):
                watched = 0
            if r.get('title') and (r.get('last_watched') or watched > 0):
                out.append(r['title'])
        return out

    @staticmethod
    def _feed_fetch(cfg, http):
        """Simkl's schedule + trending rows (no auth, cached an hour)."""
        from .tracking import Tracking
        tr = Tracking(cfg, http)
        return tr.calendar.calendar(), tr.calendar.trending()

    @staticmethod
    def _fetch_extra(cfg, http, rows, days):
        """Detail + episode lists for the shows that can appear on the rail.

        Library rows carry no air date (verified against the live API), so the
        show detail's `last_aired` is the real source. Worker thread only,
        cached (detail 7 days, episodes 1 day). Caps: 60 details, 20 episode
        lists - a first run costs one call per followed show, later runs free.
        """
        from datetime import date, timedelta
        from .recent import day_of
        from .simkl_extra import SimklExtra
        if cfg is None:
            return {}, {}, {}
        today = date.today()
        oldest = today - timedelta(days=days)
        ids, rel, eps, det = [], {}, {}, {}
        cands = []
        for r in rows or []:
            sid = r.get('simkl')
            if not sid:
                continue
            started = (int(r.get('watched') or 0) > 0 or r.get('last_watched')
                       or r.get('status') in ('watching', 'plantowatch')
                       or day_of(r.get('air_date')) is not None)
            if not started:
                continue
            # shows still being watched first, then most recently watched:
            # the cap must never be eaten by old completed movies
            cands.append(((r.get('status') == 'watching',
                           str(r.get('last_watched') or '')), sid))
        seen = set()
        for _score, sid in sorted(cands, key=lambda t: t[0], reverse=True):
            if sid in seen:
                continue
            seen.add(sid)
            ids.append(sid)
            if len(ids) >= 60:
                break
        if not ids:
            return rel, eps, det
        extra = SimklExtra(cfg, http)
        for sid in ids:
            d = extra.detail(sid) or {}
            det[sid] = d
            rel[sid] = d.get('relations') or []
            la = day_of(d.get('last_aired'))
            airing = d.get('status') == 'airing'
            if airing or (la and oldest <= la <= today):
                if len(eps) < 30:
                    eps[sid] = extra.episodes(sid)  # exact newest aired ep
        return rel, eps, det

    def _refresh_library(self):
        """ONE worker call to library.overview() re-renders everything it
        feeds: the shelf (current rail), the feed, the history table and the
        Recent view - so a Simkl change lands in all of them at once."""
        self.feed.setSortingEnabled(False)
        self.feed.setRowCount(0)
        self.hist.setSortingEnabled(False)
        self.hist.setRowCount(0)
        self.feed.insertRow(0)
        self.feed.setItem(0, 2, W.QTableWidgetItem('loading…'))
        rails = getattr(self, '_settings', None) or {}
        if getattr(self, '_lib_busy', False) \
                and time.time() - getattr(self, '_lib_at', 0.0) < 120:
            self._lib_again = True        # one read at a time, last wins
            return
        self._lib_busy = True
        self._lib_at = time.time()

        def work():
            acc = None
            try:
                acc = self._tr.client
                connected = bool(acc and acc.logged_in())
            except Exception as ex:
                connected = False
                _log.cprint(f'feed: Simkl check failed ({ex})')
            if not connected:
                _log.cprint('feed: Simkl not connected - click the Simkl '
                            'light (↻ area, above) to sign in')
                self._libq.put(('feed', None, None))
                return
            rows = []
            try:
                from .library import overview
                with _log.span('feed') as s:
                    ov = overview(self._cfg, self._http)
                    cal, rem, rc = ov['cal'], ov['rem'], ov['hist']
                    rows = ov.get('rows') or []
                    s.result(f'{len(cal)} upcoming · {len(rem)} to-watch '
                             f'· {len(rc)} watched')
            except Exception as ex:
                _log.cprint(f'feed: fetch failed ({ex}) - press ↻ to retry')
                cal, rem, rc = [], [], []
            sched, trend = [], []
            try:
                sched, trend = self._feed_fetch(self._cfg, self._http)
            except Exception as exc:
                _log.cprint(f'feed: schedule/discover failed ({exc})')
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
            shelf, recent = [], []
            try:
                from .continuewatch import ContinueWatching
                from .recent import RecentlyAired
                shelf = ContinueWatching(self._cfg, self._http).items(
                    rem, limit=(rails.get('continue') or {}).get('limit', 10))
                # one list wide enough for BOTH the rail and the sidebar;
                # each view filters own days/new-season flags on the GUI side
                sside = rails.get('sidebar') or {}
                window = max((rails.get('recent') or {}).get('days', 14),
                             sside.get('days', 14))
                rel, eps, det = self._fetch_extra(self._cfg, self._http,
                                                  rows, window)
                from .recent import _newest_aired
                def _air_date(r):
                    sid = r.get('simkl')
                    newest = _newest_aired(eps.get(sid) or eps.get(str(sid))
                                           or [])
                    if newest:
                        return newest[0].isoformat()
                    return ((det.get(sid) or {}).get('last_aired')
                            or r.get('air_date'))
                rows = [dict(r, air_date=_air_date(r)) for r in rows]
                recent = RecentlyAired(self._cfg, self._http).items(
                    rows, days=window, limit=50,
                    known_titles=self._known_titles(rows),
                    relations=rel, episodes=eps)
            except Exception as ex:
                _log.cprint(f'feed: poster rails failed ({ex})')
            self._libq.put(('feed', {'cal': cal, 'rem': rem, 'shelf': shelf,
                                     'today': sched, 'trending': trend,
                                     'recent': recent}, rc))
        threading.Thread(target=work, daemon=True).start()

    def load_side(self):
        """Old name for the same single-path refresh (callers kept working)."""
        self._refresh_library()

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
        side = (getattr(self, '_settings', None) or {}).get('sidebar') or {}
        if mode == 'Calendar':
            rows = list(cal or [])
        elif mode == 'Today':
            rows = list(self.state.get('today') or [])
        elif mode == 'Trending':
            rows = list(self.state.get('trending') or [])
        elif mode == 'Remaining':
            rows = list(rem or [])
        elif mode == 'Recent':
            rows = self._recent_items(side.get('days', 14), None,
                                      side.get('include_new_seasons', True))
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
            if 'days_ago' in e:                  # recently-aired (tp.recent) row
                ago = e.get('days_ago') or 0
                when = '🆕  today' if not ago else f'🆕  {ago}d ago'
            elif k in ('upcoming', 'today'):
                when = '📅  ' + _fmt_date(e['air_date'])
            elif k == 'trending':
                when = '🔥  trending'
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
            elif 'days_ago' in e and e.get('is_new_season'):
                ttl = f"{e['title']}  ·  new season"
            self.feed.setItem(r, 2, W.QTableWidgetItem(ttl))
            # Aired column: shown only when the sidebar option is on
            ago = e.get('days_ago')
            c3 = _SortItem('' if ago is None else
                           ('today' if not ago else f'{ago}d'))
            c3.setData(C.Qt.UserRole, int(ago or 0))
            self.feed.setItem(r, 3, c3)
        if not rows:
            self.feed.insertRow(0)
            self.feed.setItem(0, 2, W.QTableWidgetItem(
                'nothing here — try another filter or ↻ refresh'))
        self.feed.setSortingEnabled(True)

    def _drain_lib(self):
        while True:
            try:
                msg = self._libq.get_nowait()
                if isinstance(msg, tuple) and msg and msg[0] == 'copied-ep':
                    _k, url, title, num = msg
                    if url:
                        W.QApplication.clipboard().setText(str(url))
                        self.state['msg'] = f'ep{num} link copied: {url}'
                    else:
                        self.state['msg'] = f'{title}'
                    self.state['msg_until'] = time.time() + 8
                    continue
            except queue.Empty:
                return
            if msg[0] in ('feed-refresh', 'refresh'):
                self._refresh_library()
            elif msg[0] == 'status':
                items = msg[1] or []
                self.status_strip.set_items(items)
                if items:
                    _log.cprint('status: ' + ' · '.join(
                        f"{i.get('name')} {i.get('state')}"
                        for i in items))
            elif msg[0] == 'simkl-sync':
                r = msg[1] or {}
                if r.get('failed'):
                    self.state['msg'] = (
                        f"simkl: {r['failed']} change(s) failed, "
                        f"{r.get('pending', 0)} queued (retrying)")
                    self.state['msg_until'] = time.time() + 10
                elif r.get('sent'):
                    self.state['msg'] = f"simkl: {r['sent']} change(s) synced"
                    self.state['msg_until'] = time.time() + 6
                    self._libq.put(('refresh',))
                elif r.get('msg'):
                    self.state['msg'] = r['msg']
                    self.state['msg_until'] = time.time() + 8
            elif msg[0] == 'watched-repaint':
                self._paint_watched()
            elif msg[0] == 'loaded':
                # async completion of load_target (worker -> GUI thread)
                self._apply_loaded(msg[1], msg[2], msg[3], msg[4])
            elif msg[0] == 'size':
                _, s, n, sz = msg
                if self.state['session'] is not s:
                    continue
                for r in range(self.table.rowCount()):
                    it = self.table.item(r, 0)
                    if it and int(it.data(C.Qt.UserRole)) == int(n):
                        self.table.setItem(r, 2, W.QTableWidgetItem(
                            _fmt_size(sz)))
                        break
            elif msg[0] == 'poster':
                u, data = msg[1], msg[2]
                self._poster_pending.discard(u)
                pm = G.QPixmap()
                if pm.loadFromData(data):
                    self.shelf.set_poster(u, pm)
            elif msg[0] == 'feed':
                self._lib_busy = False
                if getattr(self, '_lib_again', False):
                    self._lib_again = False
                    C.QTimer.singleShot(200, self._refresh_library)
                _, payload, rc = msg
                if payload is None:
                    self.state['cal'] = self.state['rem'] = None
                else:
                    self.state['cal'] = payload.get('cal')
                    self.state['rem'] = payload.get('rem')
                self.state['today'] = (payload or {}).get('today') or []
                self.state['trending'] = (payload or {}).get('trending') or []
                # one payload feeds both rails: the shelf shows the picked one
                self.state['recent'] = (payload or {}).get('recent') or []
                rset = (getattr(self, '_settings', None) or {}).get('recent') or {}
                self._rails = {
                    'continue': (payload or {}).get('shelf') or [],
                    'recent': self._recent_items(rset.get('days', 14),
                                                 rset.get('limit', 20),
                                                 rset.get('include_new_seasons',
                                                          True))}
                self._rail_mode(self.shelf.mode)
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
                ok = self._tr.lists.set(ids, status)
                if ok:
                    self._syncer.wake()
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
            # no log pane any more: keep the lines reachable as a tooltip and
            # still refresh the feed/history when a sync lands
            self.status.setToolTip('\n'.join(lines[-8:]))
            for ln in lines:
                if ln.startswith('skip['):      # visible skip receipt
                    self.state['msg'] = ln
                    self.state['msg_until'] = time.time() + 10
            if any(('synced:' in ln) or ('marked ep' in ln) for ln in lines):
                self.side_timer.start()          # auto-refresh feed/history

    def _refresh_status(self):
        if self.state['closing']:
            return
        s = self.state['session']
        mu = self.state.get('msg_until')
        if mu and time.time() > mu:
            self.state['msg'] = ''
            self.state['msg_until'] = 0
        txt = s.status() if s is not None else ''
        if self.state.get('msg'):
            txt = self.state['msg']
        txt = txt or 'idle'
        self.status.setToolTip(txt if len(txt) > 60 else '')
        self.status.setText(self.status.fontMetrics().elidedText(
            txt, C.Qt.ElideRight, max(80, self.status.width() - 8)))

    # --- closing --------------------------------------------------------
    def close_window(self):
        """Quit: stop the player, the Simkl sync worker and this process."""
        try:
            self._syncer.stop()
        except Exception:
            pass
        if self.state['closing']:
            return
        self.state['closing'] = True
        self._remember_window_state()               # keep the pane widths
        for t in (self.debounce, self.poll, self.log_timer, self.st_timer,
                  self.side_timer):
            try:
                t.stop()
            except Exception:
                pass
        try:
            if self.state['session'] is not None:
                self.state['session'].stop()        # kill mpv, save progress
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
        if self._simkl_acc.logged_in():
            self._syncer.start()       # retry anything queued in a past run

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
