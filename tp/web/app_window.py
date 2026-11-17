"""tp.web.app_window - the same UI as a native Qt Quick window (no Chromium).

`./tgplay --web-app`: the local server from `tp.web.server` runs exactly as for
`--web`, but the window is Qt Quick (QML) instead of a QWebEngineView embed. The
QML client renders `/api/state` and posts to the same endpoints, so the Python
data layer stays the only source of truth.

`--web` still opens a browser/app-mode window (`tp/web/run.py`) - the QML window
is the native shell, the web bundle is optional.
"""
import os
import sys
import threading

from . import server as _srv
from .server import HOST
from .. import log

QML = os.path.join(os.path.dirname(__file__), 'qml', 'Main.qml')


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
        from PySide6 import QtCore as C, QtGui as G, QtQml
    except Exception as ex:
        log.cprint(f'web-app: PySide6/QtQuick missing ({ex}) - use --web')
        return 2

    port = int(os.environ.get('TPLAY_WEB_PORT') or 0)
    server = _srv.serve(port)          # 0 = pick a free port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://{HOST}:{server.server_address[1]}/'
    log.cprint(f'web-app: {url}')

    rc = 0
    try:
        app = G.QGuiApplication.instance() or G.QGuiApplication(sys.argv[:1])
        app.setApplicationName('tgplay')
        _icon(app)
        engine = QtQml.QQmlApplicationEngine()
        engine.rootContext().setContextProperty('apiBase', url)
        engine.load(C.QUrl.fromLocalFile(QML))
        if not engine.rootObjects():
            log.cprint(f'web-app: QML failed to load ({QML})')
            rc = 2
        else:
            rc = app.exec()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
    return rc
