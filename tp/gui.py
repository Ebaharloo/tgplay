"""tp.gui - the Tkinter fallback UI (URL picker + launcher, retired window).

The Tk episode controller is retired (tp/gui_qt.controller too): every GUI
now routes through the unified window (tp/gui_all.UnifiedWindow). What stays
here is the no-PySide6 fallback: `available()` test, `choose_url()` picker and
the `launcher()` search field.
"""
import os
from typing import Optional


def available() -> bool:
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return False
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def choose_url(recent: list, search_fn=None) -> Optional[str]:
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
            if '://' in t or t.lower().startswith('axp:'):
                res['url'] = t
        if 'url' in res:
            root.destroy()
        else:
            status.configure(text='no result yet — press Cancel to close')

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


def launcher():
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
            got = search_all(t, http=http, sources=('agp', 'axp', 'zoro')) or []
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
        if 'target' in res:
            root.destroy()
        else:
            status.configure(text='no result yet — type a title or paste a '
                                  'link (Cancel to close)')

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
