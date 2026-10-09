"""tp.app - the shared process wrapper for the entry points.

Every CLI (agp / axp / tg / tgp) runs through `run()`: it appends our log to a
file and turns any crash into an on-screen dialog (plus the log path), so an
app started from the desktop icon never dies silently with no terminal.
"""
import os
import sys
import traceback

from . import log


def log_path(name: str) -> str:
    base = os.environ.get('AGP_LOG_DIR') or os.path.join(
        os.path.expanduser('~'), '.config', 'tgp')
    return os.path.join(base, f'{name}.log')


def run(main, name: str = 'agp') -> int:
    path = log_path(name)
    log.open_logfile(path)
    try:
        log.cprint(f'log file: {path}')
        result = main()
        return result if isinstance(result, int) else 0
    except KeyboardInterrupt:
        log.real_print(log.style('⛔ interrupted - bye'))
        return 130
    except Exception:
        tb = traceback.format_exc()
        try:
            log.cprint(f'!! {name} crashed: {tb.strip().splitlines()[-1]}')
        except Exception:
            pass
        _show_error(name, tb, path)
        return 1
    finally:
        try:
            if log.LOGFILE is not None:
                log.LOGFILE.close()
        except Exception:
            pass
        log.LOGFILE = None


def _show_error(name: str, tb: str, path: str):
    last = tb.strip().splitlines()[-1] if tb.strip() else 'unknown error'
    msg = (f'{name} stopped with an error:\n\n{last}\n\n'
           f'Full log:\n{path}')
    if os.environ.get('AGP_NO_DIALOG'):
        return
    # Prefer the toolkit that is already up (avoid clashing with a live Qt app).
    try:
        from PySide6 import QtWidgets as W
        if W.QApplication.instance() is not None:
            W.QMessageBox.critical(None, f'{name} - error', msg)
            return
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(f'{name} - error', msg)
        r.destroy()
        return
    except Exception:
        pass
    try:
        sys.stderr.write(msg + '\n')
    except Exception:
        pass
