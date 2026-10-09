"""tp.gui - native (Tkinter) menu: episode list + options, then Play.

Same role as tp.ui (the terminal menu): it only *chooses* things and returns
(opts, mpv) + the chosen episodes. Playback stays in Playlist/mpv. No extra
dependencies - tkinter ships with Python.
"""
import os
from typing import Dict, List, Optional, Tuple

SKIP_MODES = ['off', 'all', 'names', 'auto']


def available() -> bool:
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return False
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def configure(title: str, link: Optional[str], groups: List[dict],
              labels: Dict[int, str], resume: Optional[int], opts: dict,
              mpv: List[str]) -> Optional[Tuple[List[int], dict, List[str]]]:
    """Open the window. Returns (chosen_episode_numbers, opts, mpv), or None
    if cancelled. Raises RuntimeError if the GUI cannot start."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as ex:  # pragma: no cover
        raise RuntimeError(f'tkinter unavailable ({ex})')

    try:
        root = tk.Tk()
    except Exception as ex:
        raise RuntimeError(f'cannot open window ({ex})')
    root.title('tgplay')
    root.minsize(640, 480)
    try:
        ttk.Style().theme_use('clam')
    except Exception:
        pass

    nums = sorted(labels)
    result: dict = {}

    # header ---------------------------------------------------------------
    top = ttk.Frame(root, padding=(10, 8, 10, 4))
    top.pack(fill='x')
    ttk.Label(top, text=title, font=('TkDefaultFont', 13, 'bold')).pack(anchor='w')
    if link:
        lb = ttk.Label(top, text=link, foreground='#1565c0', cursor='hand2')
        lb.pack(anchor='w')
        lb.bind('<Button-1>', lambda e: _open(link))

    # options --------------------------------------------------------------
    opt = ttk.LabelFrame(root, text='Options', padding=(10, 6))
    opt.pack(fill='x', padx=10, pady=(2, 6))

    quality_var = tk.StringVar()
    glabels = [str(g['label']) for g in groups]
    if glabels:
        row = ttk.Frame(opt); row.pack(fill='x', pady=1)
        ttk.Label(row, text='Quality', width=12).pack(side='left')
        ttk.Combobox(row, textvariable=quality_var, values=glabels,
                     state='readonly', width=40).pack(side='left')
        cur = next((l for l in glabels
                    if opts.get('f') and str(opts['f']).lower() in l.lower()),
                   glabels[0])
        quality_var.set(cur)

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

    # episode list ---------------------------------------------------------
    mid = ttk.LabelFrame(root, text=f'Episodes ({len(nums)})', padding=(6, 4))
    mid.pack(fill='both', expand=True, padx=10, pady=(0, 6))
    cols = ('num', 'name')
    tree = ttk.Treeview(mid, columns=cols, show='headings', selectmode='extended')
    tree.heading('num', text='#')
    tree.heading('name', text='Episode name')
    tree.column('num', width=60, anchor='e', stretch=False)
    tree.column('name', width=520, anchor='w')
    for n in nums:
        tree.insert('', 'end', iid=str(n), values=(n, labels.get(n, f'Episode {n}')))
    if resume in labels:
        try:
            tree.see(str(resume))
            tree.selection_set(str(resume))
            tree.focus(str(resume))
        except Exception:
            pass
    tree.bind('<Double-1>', lambda e: _from_here())
    sb = ttk.Scrollbar(mid, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    sb.pack(side='right', fill='y')
    tree.pack(side='left', fill='both', expand=True)

    def _open(url):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    def _sel_nums() -> List[int]:
        out = []
        for i in tree.selection():
            try:
                out.append(int(i))
            except ValueError:
                pass
        return sorted(out)

    def _focus_num() -> Optional[int]:
        sel = _sel_nums()
        if sel:
            return sel[0]
        try:
            return int(tree.focus())
        except (ValueError, TypeError):
            return None

    def _apply_options():
        if glabels:
            opts['f'] = quality_var.get()
        sm = skip_var.get()
        opts['skip'] = False if sm == 'off' else sm
        opts['skip_toggle'] = bool(toggle_var.get())
        opts['next'] = 0.60 if next_var.get() else False
        opts['nowait'] = bool(nowait_var.get())
        c = cut_var.get().strip()
        opts['cut'] = int(c) if c.isdigit() else None
        flags = extra_var.get().split()
        if full_var.get() and '--fullscreen' not in flags:
            flags.append('--fullscreen')
        return flags

    def _finish(chosen: List[int]):
        result['chosen'] = chosen
        result['opts'] = opts
        result['mpv'] = _apply_options()
        root.destroy()

    def _from_here():
        f = _focus_num()
        if f is not None:
            _finish([n for n in nums if n >= f])

    def _only_selected():
        sel = _sel_nums()
        f = _focus_num()
        _finish(sel if sel else ([f] if f is not None else nums))

    def _all():
        _finish(nums)

    def _cancel():
        root.destroy()

    root.event_generate('<Return>')  # noop; keep bindings simple
    root.bind('<Escape>', lambda e: _cancel())

    # buttons --------------------------------------------------------------
    bar = ttk.Frame(root, padding=(10, 0, 10, 10))
    bar.pack(fill='x')
    ttk.Button(bar, text='▶  Play from here', command=_from_here).pack(side='left')
    ttk.Button(bar, text='▶  Only selected', command=_only_selected).pack(side='left', padx=6)
    ttk.Button(bar, text='▶  All', command=_all).pack(side='left')
    ttk.Button(bar, text='Cancel', command=_cancel).pack(side='right')

    _center(root)
    mode = os.environ.get('AGP_GUI_TEST')   # test hook: auto-act, no clicking
    if mode == 'cancel':
        root.after(300, _cancel)
    elif mode == 'play':
        root.after(300, _from_here)
    elif mode == 'all':
        root.after(300, _all)
    root.mainloop()
    if 'chosen' not in result:
        return None
    return result['chosen'], result['opts'], result['mpv']


def _center(root):
    try:
        root.update_idletasks()
        w, h = 760, 640
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 3
        root.geometry(f'{w}x{h}+{x}+{y}')
    except Exception:
        pass


def choose_url(recent: List[str]) -> Optional[str]:
    """Small window to pick a recent link or paste a new one."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as ex:  # pragma: no cover
        raise RuntimeError(f'tkinter unavailable ({ex})')
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
        sel = lb.curselection()
        val = entry.get().strip()
        if val:
            res['url'] = val
        elif sel:
            it = items[sel[0]]
            res['url'] = None if it.startswith('✎') else it
        root.destroy()

    def use_entry(e=None):
        if entry.get().strip() or not lb.curselection():
            return
        it = items[lb.curselection()[0]]
        if it.startswith('✎'):
            entry.focus_set()

    lb.bind('<<ListboxSelect>>', use_entry)
    lb.bind('<Double-1>', lambda e: ok())
    entry.bind('<Return>', lambda e: ok())
    bar = ttk.Frame(root); bar.pack(fill='x', padx=10, pady=(0, 10))
    ttk.Button(bar, text='OK', command=ok).pack(side='left')
    ttk.Button(bar, text='Cancel', command=root.destroy).pack(side='right')
    root.mainloop()
    return res.get('url')
