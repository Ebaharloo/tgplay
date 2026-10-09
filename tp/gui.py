"""tp.gui - native (Tkinter) controller: episode list + options; stays open.

Play is launched in a background thread (via a callback from cli), so the
window keeps working: pick other episodes, change the setup, Stop, and the
anime's Simkl/MAL link is shown and clickable. No extra dependencies.
"""
import os
import threading
from typing import Callable, Dict, List, Optional

SKIP_MODES = ['off', 'all', 'names', 'auto']


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
               one_shot: bool = False):
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
    try:
        ttk.Style().theme_use('clam')
    except Exception:
        pass

    nums = sorted(labels)
    state: dict = {}

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
        ttk.Label(row, text='Quality', width=12).pack(side='left')
        ttk.Combobox(row, textvariable=quality_var, values=glabels,
                     state='readonly', width=40).pack(side='left')
        quality_var.set(next((l for l in glabels
                              if opts.get('f') and str(opts['f']).lower() in l.lower()),
                             glabels[0]))
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
            root.destroy()
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
        if status_fn:
            try:
                status_var.set(status_fn())
            except Exception:
                pass
        root.after(1000, _poll)

    root.bind('<Escape>', lambda e: root.destroy())
    tree.bind('<Double-1>', lambda e: _from_here())
    bar = ttk.Frame(root, padding=(10, 0, 10, 10))
    bar.pack(fill='x')
    ttk.Button(bar, text='▶  Play from here', command=_from_here).pack(side='left')
    ttk.Button(bar, text='▶  Only selected', command=_only_sel).pack(side='left', padx=6)
    ttk.Button(bar, text='▶  All', command=_all).pack(side='left')
    ttk.Button(bar, text='■  Stop', command=_stop).pack(side='left', padx=(16, 0))
    ttk.Button(bar, text='Close', command=root.destroy).pack(side='right')

    _center(root, 780, 660)
    mode = os.environ.get('AGP_GUI_TEST')   # test hook
    if mode == 'play':
        root.after(300, _from_here)
    elif mode == 'all':
        root.after(300, _all)
    elif mode == 'stop':
        root.after(300, _stop)
    elif mode == 'close':
        root.after(300, root.destroy)
    if status_fn:
        root.after(400, _poll)
    root.mainloop()


def _center(root, w=780, h=660):
    try:
        root.update_idletasks()
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 3
        root.geometry(f'{w}x{h}+{x}+{y}')
    except Exception:
        pass


def choose_url(recent: List[str]) -> Optional[str]:
    """Small window to pick a recent link or paste a new one."""
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title('tgplay - which anime?')
    res: dict = {}
    items = list(dict.fromkeys(recent))[:15] + ['✎  Enter a new link…']
    ttk.Label(root, text='Which anime do you want to watch?',
              font=('TkDefaultFont', 12, 'bold')).pack(anchor='w', padx=10, pady=(10, 4))
    lb = tk.Listbox(root, width=90, height=min(16, len(items)))
    for it in items:
        lb.insert('end', it)
    lb.pack(padx=10, pady=4, fill='both', expand=True)
    lb.selection_set(0)
    entry = ttk.Entry(root, width=90)
    entry.pack(padx=10, pady=(0, 4), fill='x')

    def ok():
        val = entry.get().strip()
        sel = lb.curselection()
        if val:
            res['url'] = val
        elif sel:
            it = items[sel[0]]
            res['url'] = None if it.startswith('✎') else it
        root.destroy()

    lb.bind('<Double-1>', lambda e: ok())
    entry.bind('<Return>', lambda e: ok())
    bar = ttk.Frame(root); bar.pack(fill='x', padx=10, pady=(0, 10))
    ttk.Button(bar, text='OK', command=ok).pack(side='left')
    ttk.Button(bar, text='Cancel', command=root.destroy).pack(side='right')
    root.mainloop()
    return res.get('url')
