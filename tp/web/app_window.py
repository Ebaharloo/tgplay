"""tp.web.app_window - the Astryx UI inside a real desktop window.

No browser, no address bar: a Qt window (native title bar, taskbar entry, app
icon) with a QWebEngineView showing the local server. This is the "normal app"
path - `./tgplay --web-app` or `./tgplay --web` when QtWebEngine is installed.

The heavy Qt imports live inside `main()` so a missing PySide6-Addons only
affects this entry point, never the plain web/CLI paths.
"""
import os
import sys
import threading
import time

from . import server as _srv
from .server import HOST
from .. import log


def _icon(app):
    """The same window icon the Qt window uses, if it loads."""
    try:
        from ..gui_qt import _app_icon as icon
        import PySide6.QtGui as G
        pm = icon(G)
        if pm is not None:
            app.setWindowIcon(pm)
    except Exception:
        pass


def main(argv=None) -> int:
    try:
        from PySide6 import QtWidgets as W, QtCore as C
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    except Exception as ex:
        log.cprint(f'web-app: QtWebEngine missing ({ex}) - '
                   'run `pip install PySide6-Addons` or use --web')
        return 2

    closed = threading.Event()

    def app_main():
        app = W.QApplication.instance() or W.QApplication(sys.argv[:1])
        app.setApplicationName('tgplay')
        _icon(app)
        win = W.QMainWindow()
        win.setWindowTitle('tgplay')
        win.resize(1360, 960)
        view = QWebEngineView(win)
        win.setCentralWidget(view)
        view.setUrl(C.QUrl(url))
        win.show()

        def done(*_a):
            closed.set()
        app.aboutToQuit.connect(done)
        win.destroyed.connect(done)
        code = app.exec()
        closed.set()
        return code

    port = int(os.environ.get('TPLAY_WEB_PORT') or 0)
    server = _srv.serve(port)          # 0 = pick a free port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://{HOST}:{server.server_address[1]}/'
    log.cprint(f'web-app: {url}')

    rc = 0
    try:
        rc = app_main()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
    return rc
