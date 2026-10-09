"""tp.gui - native (Tkinter) controller: episode list + options; stays open.

Play is launched in a background thread (via a callback from cli), so the
window keeps working: pick other episodes, change the setup, Stop, and the
anime's Simkl/MAL link is shown and clickable. No extra dependencies.
"""
import os
import queue
import threading
from typing import Callable, Dict, List, Optional

SKIP_MODES = ['off', 'all', 'names', 'auto']


# --- OS theme (KDE/GNOME) ----------------------------------------------
def _kde_colors():
    """KDE Plasma stores its color scheme in ~/.config/kdeglobals."""
    import configparser
    p = os.path.expanduser('~/.config/kdeglobals')
    if not os.path.exists(p):
        return None
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        cp.read(p)
    except Exception:
        return None

    def col(sec, key):
        try:
            r, g, b = [int(x) for x in cp.get(sec, key).split(',')[:3]]
            return '#%02x%02x%02x' % (r, g, b)
        except Exception:
            return None

    win = col('Colors:Window', 'BackgroundNormal')
    if not win:
        return None
    return {'win_bg': win,
            'win_fg': col('Colors:Window', 'ForegroundNormal') or '#000000',
            'view_bg': col('Colors:View', 'BackgroundNormal') or win,
            'view_fg': col('Colors:View', 'ForegroundNormal') or '#000000',
            'btn_bg': col('Colors:Button', 'BackgroundNormal') or win,
            'btn_fg': col('Colors:Button', 'ForegroundNormal') or '#000000',
            'sel_bg': col('Colors:Selection', 'BackgroundNormal') or '#3daee9',
            'sel_fg': col('Colors:Selection', 'ForegroundNormal') or '#ffffff'}


def _gtk_colors():
    """Fallback for GNOME: read gtk settings.ini for the dark preference."""
    import configparser
    for name in ('~/.config/gtk-3.0/settings.ini',
                 '~/.config/gtk-4.0/settings.ini'):
        p = os.path.expanduser(name)
        if not os.path.exists(p):
            continue
        cp = configparser.ConfigParser(strict=False)
        try:
            cp.read(p)
            dark = cp.get('Settings', 'gtk-application-prefer-dark-theme',
                          fallback='0')
            if dark.strip().lower() in ('1', 'true'):
                return {'win_bg': '#232629', 'win_fg': '#eff0f1',
                        'view_bg': '#1b1e20', 'view_fg': '#eff0f1',
                        'btn_bg': '#2a2e32', 'btn_fg': '#eff0f1',
                        'sel_bg': '#3daee9', 'sel_fg': '#ffffff'}
        except Exception:
            continue
    return None


def _apply_theme(root, style) -> Optional[dict]:
    col = _kde_colors() or _gtk_colors()
    if not col:
        return None
    try:
        root.configure(bg=col['win_bg'])
    except Exception:
        pass

    def cfg(w, **kw):
        try:
            style.configure(w, **kw)
        except Exception:
            pass
    cfg('.', background=col['win_bg'], foreground=col['win_fg'],
        fieldbackground=col['view_bg'])
    for w in ('TFrame', 'TLabel', 'TLabelframe', 'TLabelframe.Label',
              'TCheckbutton', 'TRadiobutton'):
        cfg(w, background=col['win_bg'], foreground=col['win_fg'])
    cfg('TButton', background=col['btn_bg'], foreground=col['btn_fg'])
    try:
        style.map('TButton', background=[('active', col['sel_bg'])],
                  foreground=[('active', col['sel_fg'])])
    except Exception:
        pass
    for w in ('TCombobox', 'TEntry'):
        cfg(w, fieldbackground=col['view_bg'], foreground=col['view_fg'],
            background=col['btn_bg'])
    cfg('Treeview', background=col['view_bg'], fieldbackground=col['view_bg'],
        foreground=col['view_fg'])
    cfg('Treeview.Heading', background=col['btn_bg'], foreground=col['btn_fg'])
    try:
        style.map('Treeview',
                  background=[('selected', col['sel_bg'])],
                  foreground=[('selected', col['sel_fg'])])
    except Exception:
        pass
    return col


def _make_icon(root, accent='#3daee9'):
    import tkinter as tk
    size = 32
    img = tk.PhotoImage(width=size, height=size)
    img.put('#10131a', to=(0, 0, size, size))
    for i in range(3, size - 3):
        img.put(accent, to=(i, 3))
        img.put(accent, to=(i, size - 4))
        img.put(accent, to=(3, i))
        img.put(accent, to=(size - 4, i))
    for y in range(8, size - 8):
        w = size // 2 - abs(y - size // 2) - 2
        for x in range(12, 12 + max(1, w)):
            img.put('#ffffff', to=(x, y))
    try:
        root.iconphoto(True, img)
    except Exception:
        pass
    return img


def _file_icon(root) -> bool:
    """Use the packaged PNG icon if Tk can read it; return True on success."""
    try:
        import tkinter as tk
        from . import icon as _icon
        p = _icon.png(128)
        if p and os.path.exists(p):
            img = tk.PhotoImage(file=p)
            root.iconphoto(True, img)
            root._tgplay_icon = img   # keep a reference alive
            return True
    except Exception:
        pass
    return False


def available() -> bool:
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return False
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def controller(title: str, link: Optional[str], groups: List[dict],
               labels: Dict[int, str], resume: Optional[int], opts: dict,
               mpv: List[str], play_fn: Callable, stop_fn=None, status_fn=None,
               one_shot: bool = False, audio: bool = False):
    """Open the window and keep it until the user closes it (or, with
    `one_shot`, until the first Play). `play_fn(chosen, opts, mpv)` is called
    in a background thread."""
    import tkinter as tk
    from tkinter import ttk
    try:
        root = tk.Tk()
    except Exception as ex:
        raise RuntimeError(f'cannot open window ({ex})')
    root.title('tgplay')
    style = ttk.Style()
    try:
        style.theme_use('clam')
    except Exception:
        pass
    col = _apply_theme(root, style)
    if not _file_icon(root):
        _make_icon(root, (col or {}).get('sel_bg', '#3daee9'))

    nums = sorted(labels)
    state: dict = {}
    after_ids: list = []

    top = ttk.Frame(root, padding=(10, 8, 10, 4))
    top.pack(fill='x')
    ttk.Label(top, text=title, font=('TkDefaultFont', 13, 'bold')).pack(anchor='w')
    if link:
        lb = ttk.Label(top, text='🔗 ' + link, foreground='#1565c0', cursor='hand2')
        lb.pack(anchor='w')
        lb.bind('<Button-1>', lambda e: _open(link))

    opt = ttk.LabelFrame(root, text='Options', padding=(10, 6))
    opt.pack(fill='x', padx=10, pady=(2, 6))
    glabels = [str(g['label']) for g in groups]
    quality_var = tk.StringVar()
    if glabels:
        row = ttk.Frame(opt); row.pack(fill='x', pady=1)
        ttk.Label(row, text='Server' if audio else 'Quality', width=12).pack(side='left')
        ttk.Combobox(row, textvariable=quality_var, values=glabels,
                     state='readonly', width=40).pack(side='left')
        quality_var.set(next((l for l in glabels
                              if opts.get('f') and str(opts['f']).lower() in l.lower()),
                             glabels[0]))
    audio_var = None
    if audio:
        audio_var = tk.StringVar(value=opts.get('audio')
                                 if opts.get('audio') in ('dub', 'sub', 'auto')
                                 else 'dub')
        row = ttk.Frame(opt); row.pack(fill='x', pady=1)
        ttk.Label(row, text='Audio', width=12).pack(side='left')
        ttk.Combobox(row, textvariable=audio_var, values=['dub', 'sub', 'auto'],
                     state='readonly', width=8).pack(side='left')
    skip_var = tk.StringVar(value=opts.get('skip') if isinstance(
        opts.get('skip'), str) else ('all' if opts.get('skip') else 'off'))
    toggle_var = tk.BooleanVar(value=bool(opts.get('skip_toggle')))
    next_var = tk.BooleanVar(value=bool(opts.get('next')))
    nowait_var = tk.BooleanVar(value=bool(opts.get('nowait')))
    full_var = tk.BooleanVar(value='--fullscreen' in mpv)
    row = ttk.Frame(opt); row.pack(fill='x', pady=1)
    ttk.Label(row, text='Skip', width=12).pack(side='left')
    ttk.Combobox(row, textvariable=skip_var, values=SKIP_MODES,
                 state='readonly', width=8).pack(side='left')
    ttk.Checkbutton(row, text='toggle key T', variable=toggle_var).pack(side='left', padx=8)
    ttk.Checkbutton(row, text='fullscreen', variable=full_var).pack(side='left')
    row = ttk.Frame(opt); row.pack(fill='x', pady=1)
    ttk.Checkbutton(row, text='Pre-download next episode', variable=next_var).pack(side='left')
    ttk.Checkbutton(row, text='start it at cut point', variable=nowait_var).pack(side='left', padx=8)
    cut_var = tk.StringVar(value=str(opts.get('cut') or ''))
    extra_var = tk.StringVar(value=' '.join(x for x in mpv if x != '--fullscreen'))
    row = ttk.Frame(opt); row.pack(fill='x', pady=1)
    ttk.Label(row, text='Cut last N s', width=12).pack(side='left')
    ttk.Entry(row, textvariable=cut_var, width=8).pack(side='left')
    ttk.Label(row, text='  Extra mpv flags').pack(side='left')
    ttk.Entry(row, textvariable=extra_var, width=32).pack(side='left', padx=4)

    mid = ttk.LabelFrame(root, text=f'Episodes ({len(nums)})', padding=(6, 4))
    mid.pack(fill='both', expand=True, padx=10, pady=(0, 6))
    tree = ttk.Treeview(mid, columns=('num', 'name'), show='headings',
                        selectmode='extended')
    tree.heading('num', text='#'); tree.heading('name', text='Episode name')
    tree.column('num', width=60, anchor='e', stretch=False)
    tree.column('name', width=520, anchor='w')
    for n in nums:
        tree.insert('', 'end', iid=str(n), values=(n, labels.get(n, f'Episode {n}')))
    if resume in labels:
        try:
            tree.see(str(resume)); tree.selection_set(str(resume)); tree.focus(str(resume))
        except Exception:
            pass
    sb = ttk.Scrollbar(mid, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    sb.pack(side='right', fill='y'); tree.pack(side='left', fill='both', expand=True)

    status_var = tk.StringVar(value='idle')
    ttk.Label(root, textvariable=status_var, foreground='#333').pack(
        anchor='w', padx=12)

    def _apply():
        o = dict(opts)
        if glabels:
            o['f'] = quality_var.get()
        if audio_var is not None:
            o['audio'] = audio_var.get()
        sm = skip_var.get()
        o['skip'] = False if sm == 'off' else sm
        o['skip_toggle'] = bool(toggle_var.get())
        o['next'] = 0.60 if next_var.get() else False
        o['nowait'] = bool(nowait_var.get())
        c = cut_var.get().strip()
        o['cut'] = int(c) if c.isdigit() else None
        flags = extra_var.get().split()
        if full_var.get() and '--fullscreen' not in flags:
            flags.append('--fullscreen')
        return o, flags

    def _sel():
        out = []
        for i in tree.selection():
            try:
                out.append(int(i))
            except ValueError:
                pass
        return sorted(out)

    def _focus():
        s = _sel()
        if s:
            return s[0]
        try:
            return int(tree.focus())
        except (ValueError, TypeError):
            return None

    def _play(chosen: List[int]):
        o, flags = _apply()
        status_var.set('starting…')
        if play_fn is None:
            return
        if one_shot:
            play_fn(chosen, o, flags)
            _close()
            return

        def run():
            try:
                play_fn(chosen, o, flags)
            except Exception as ex:
                status_var.set(f'error: {ex}')
        threading.Thread(target=run, daemon=True).start()

    def _from_here():
        f = _focus()
        if f is not None:
            _play([n for n in nums if n >= f])

    def _only_sel():
        s = _sel()
        f = _focus()
        _play(s if s else ([f] if f is not None else nums))

    def _all():
        _play(nums)

    def _stop():
        if stop_fn:
            try:
                stop_fn()
            except Exception:
                pass
        status_var.set('stopped')

    def _open(url):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    def _poll():
        if state.get('closing'):
            return
        if status_fn:
            try:
                status_var.set(status_fn())
            except Exception:
                pass
        after_ids.append(root.after(1000, _poll))

    # in-app log panel (mirrors tp.log lines)
    from tkinter.scrolledtext import ScrolledText
    from . import log as _log
    logframe = ttk.LabelFrame(root, text='Log', padding=(4, 2))
    logframe.pack(fill='x', padx=10, pady=(0, 6))
    logbox = ScrolledText(logframe, height=7, wrap='word', state='disabled')
    try:
        logbox.configure(font=('TkFixedFont',))
    except Exception:
        pass
    logbox.pack(fill='both', expand=True)
    logbox.configure(state='normal')
    for s in list(_log.HISTORY):
        logbox.insert('end', s + '\n')
    if _log.HISTORY:
        logbox.see('end')
    logbox.configure(state='disabled')
    q: 'queue.Queue' = queue.Queue()
    _prev_sink = _log.SINK
    _log.SINK = lambda s: q.put(str(s))

    def _drain():
        if state.get('closing'):
            return
        changed = False
        while True:
            try:
                s = q.get_nowait()
            except queue.Empty:
                break
            logbox.configure(state='normal')
            logbox.insert('end', s + '\n')
            changed = True
        if changed:
            logbox.see('end')
            logbox.configure(state='disabled')
        after_ids.append(root.after(250, _drain))

    def _close():
        state['closing'] = True
        for i in after_ids:
            try:
                root.after_cancel(i)
            except Exception:
                pass
        after_ids.clear()
        try:
            _log.SINK = _prev_sink
        except Exception:
            pass
        root.destroy()

    after_ids.append(root.after(250, _drain))
    root.protocol('WM_DELETE_WINDOW', _close)
    root.bind('<Escape>', lambda e: _close())
    tree.bind('<Double-1>', lambda e: _from_here())
    bar = ttk.Frame(root, padding=(10, 0, 10, 10))
    bar.pack(fill='x')
    ttk.Button(bar, text='▶  Play from here', command=_from_here).pack(side='left')
    ttk.Button(bar, text='▶  Only selected', command=_only_sel).pack(side='left', padx=6)
    ttk.Button(bar, text='▶  All', command=_all).pack(side='left')
    ttk.Button(bar, text='■  Stop', command=_stop).pack(side='left', padx=(16, 0))
    ttk.Button(bar, text='Close', command=_close).pack(side='right')

    _center(root, 780, 660)
    mode = os.environ.get('AGP_GUI_TEST')   # test hook
    if mode == 'play':
        root.after(300, _from_here)
    elif mode == 'all':
        root.after(300, _all)
    elif mode == 'stop':
        root.after(300, _stop)
    elif mode == 'close':
        root.after(300, _close)
    if status_fn:
        after_ids.append(root.after(400, _poll))
    root.mainloop()


def _center(root, w=780, h=660):
    try:
        root.update_idletasks()
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 3
        root.geometry(f'{w}x{h}+{x}+{y}')
    except Exception:
        pass


def choose_url(recent: List[str], search_fn=None) -> Optional[str]:
    """Pick a recent link, search (when `search_fn` is given), or paste one."""
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title('tgplay - which anime?')
    res: dict = {}
    recents = list(dict.fromkeys(recent))[:15]
    ttk.Label(root, text='Which anime do you want to watch?',
              font=('TkDefaultFont', 12, 'bold')).pack(anchor='w', padx=10, pady=(10, 4))
    box = ttk.Entry(root, width=90)
    box.pack(padx=10, pady=(0, 4), fill='x')
    status = ttk.Label(root, text='')
    status.pack(anchor='w', padx=10)
    lb = tk.Listbox(root, width=90, height=min(16, max(6, len(recents))))
    lb.pack(padx=10, pady=4, fill='both', expand=True)
    urls: list = []

    def fill(entries):
        lb.delete(0, 'end')
        urls.clear()
        for e in entries:
            if isinstance(e, dict):
                lb.insert('end', f"{e.get('title', '')}  ·  {e.get('source', '')}")
                urls.append(e.get('url'))
            else:
                lb.insert('end', str(e))
                urls.append(str(e))
        if urls:
            lb.selection_clear(0, 'end')
            lb.selection_set(0)
            lb.activate(0)

    fill(recents)
    status.configure(text=f'{len(recents)} recent' if recents else
                     ('type to search' if search_fn else ''))

    def do_search(*_):
        t = box.get().strip()
        if not t:
            fill(recents)
            return
        if '://' in t or t.lower().startswith('axp:'):
            fill([t])
            status.configure(text='press OK to use this link')
            return
        if not search_fn:
            return
        status.configure(text='searching…')
        root.update_idletasks()
        try:
            got = search_fn(t) or []
        except Exception:
            got = []
        fill(got)
        status.configure(text=f'{len(got)} result(s)' if got else 'no results')

    def ok(*_):
        sel = lb.curselection()
        if sel and urls[sel[0]]:
            res['url'] = urls[sel[0]]
        else:
            t = box.get().strip()
            if t:
                res['url'] = t
        root.destroy()

    box.bind('<Return>', do_search)
    lb.bind('<Double-1>', ok)
    bar = ttk.Frame(root)
    bar.pack(fill='x', padx=10, pady=(0, 10))
    ttk.Button(bar, text='Search', command=do_search).pack(side='left')
    ttk.Button(bar, text='OK', command=ok).pack(side='left', padx=6)
    ttk.Button(bar, text='Cancel', command=root.destroy).pack(side='right')
    box.focus_set()
    try:
        root.lift()
        root.attributes('-topmost', True)
        root.after(250, lambda: root.attributes('-topmost', False))
        root.focus_force()
    except Exception:
        pass
    root.mainloop()
    return res.get('url')


def launcher(sources=None):
    """Tk fallback: one field - search AnimeGate + AnimeX, or paste any link
    (animegate / animex / t.me), or `@channel`."""
    import tkinter as tk
    from tkinter import ttk
    from .search import search_all
    from .http import HttpClient
    from .cli_all import route
    http = HttpClient()
    root = tk.Tk()
    root.title('tgplay - watch')
    res: dict = {}
    ttk.Label(root, text='What do you want to watch?',
              font=('TkDefaultFont', 12, 'bold')).pack(anchor='w', padx=10, pady=(10, 4))
    box = ttk.Entry(root, width=90)
    box.pack(padx=10, pady=(0, 4), fill='x')
    status = ttk.Label(root, text='search animegate + animex, or paste a link / @channel')
    status.pack(anchor='w', padx=10)
    lb = tk.Listbox(root, width=90, height=16)
    lb.pack(padx=10, pady=4, fill='both', expand=True)
    targets: list = []
    srcs: list = []

    def fill(entries):
        lb.delete(0, 'end')
        targets.clear()
        srcs.clear()
        for e in entries:
            if isinstance(e, dict):
                lb.insert('end', f"{e.get('title', '')}  ·  {e.get('source', '')}")
                targets.append(e.get('url'))
                srcs.append(e.get('source'))
            else:
                lb.insert('end', str(e))
                targets.append(str(e))
                srcs.append(None)
        if targets:
            lb.selection_clear(0, 'end')
            lb.selection_set(0)
            lb.activate(0)

    def do_it(*_):
        t = box.get().strip()
        if not t:
            fill([])
            return
        r = route(t)
        if r:
            fill([{'title': t, 'url': r[1], 'source': r[0]}])
            status.configure(text=f'link · {r[0]}')
            return
        status.configure(text='searching…')
        root.update_idletasks()
        try:
            got = search_all(t, http=http, sources=('agp', 'axp')) or []
        except Exception:
            got = []
        fill(got)
        status.configure(text=f'{len(got)} result(s)' if got else 'no results')

    def ok(*_):
        sel = lb.curselection()
        if sel and targets[sel[0]]:
            res['src'] = srcs[sel[0]] or 'agp'
            res['target'] = targets[sel[0]]
        else:
            r = route(box.get().strip())
            if r:
                res['src'], res['target'] = r
        root.destroy()

    box.bind('<Return>', do_it)
    lb.bind('<Double-1>', ok)
    bar = ttk.Frame(root)
    bar.pack(fill='x', padx=10, pady=(0, 10))
    ttk.Button(bar, text='Search', command=do_it).pack(side='left')
    ttk.Button(bar, text='Open', command=ok).pack(side='left', padx=6)
    ttk.Button(bar, text='Cancel', command=root.destroy).pack(side='right')
    box.focus_set()
    try:
        root.lift()
        root.attributes('-topmost', True)
        root.after(250, lambda: root.attributes('-topmost', False))
        root.focus_force()
    except Exception:
        pass
    root.mainloop()
    return (res['src'], res['target']) if 'src' in res else None
