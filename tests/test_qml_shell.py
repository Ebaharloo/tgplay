#!/usr/bin/env python3
"""test_qml_shell - the Qt Quick window loads and only calls real API routes."""
import os
import pathlib
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QML = pathlib.Path(ROOT, 'tp/web/qml/Main.qml')
SERVER = pathlib.Path(ROOT, 'tp/web/server.py')
sys.path.insert(0, ROOT)


def test_qml_loads():
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    try:
        from PySide6 import QtCore as C, QtGui as G, QtQml
    except Exception as ex:                     # PySide6 is optional for the CLI
        print(f'SKIP qml load ({ex})')
        return
    assert QML.exists(), QML
    app = G.QGuiApplication.instance() or G.QGuiApplication([])  # noqa: F841
    engine = QtQml.QQmlApplicationEngine()
    warns = []
    engine.warnings.connect(lambda ws: warns.extend(w.toString() for w in ws))
    engine.rootContext().setContextProperty('apiBase', 'http://127.0.0.1:1/')
    engine.load(C.QUrl.fromLocalFile(str(QML)))
    assert engine.rootObjects(), 'Main.qml failed to load'
    bad = [w for w in warns if 'Main.qml' in w]
    assert not bad, bad
    print('PASS qml loads')


def test_qml_uses_real_routes():
    src = QML.read_text()
    used = set(re.findall(r"'/api/([a-z]+)'", src))
    assert used, 'no /api paths found in Main.qml'
    server = SERVER.read_text()
    missing = {p for p in used if f"'/api/{p}'" not in server}
    assert not missing, f'Main.qml calls routes the server does not handle: {missing}'
    print('PASS qml routes', sorted(used))
