"""Export cannot interrupt a running/queued editor stage, including UI races."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, QPointF, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QSignalSpy, QTest

from haizflow.desktop.qml_controller import HaizFlowController

QML_DIR = Path(__file__).parents[1] / "src/haizflow/desktop/qml"


@pytest.mark.parametrize("has_video,processing,queued,exporting,expected", [
    (True, False, False, False, True),
    (True, True, True, False, False),
    (True, True, False, False, False),
    (True, False, True, False, False),
    (True, False, False, True, False),
    (False, False, False, False, False),
])
def test_backend_does_not_open_export_dialog_during_processing(has_video, processing, queued, exporting, expected):
    signal = Mock()
    host = SimpleNamespace(hasSelectedVideo=has_video, videoExportBusy=exporting,
                           isSelectedVideoProcessing=processing, isSelectedVideoQueued=queued,
                           videoExportRequested=signal)
    HaizFlowController.requestVideoExport(host)
    assert signal.emit.call_count == int(expected)


def test_export_button_tracks_busy_state_and_reenables_without_changing_toolbar():
    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    component.setData(f'''import QtQuick
import QtQuick.Controls.Basic
import "{QML_DIR.as_uri()}"
ApplicationWindow {{
    id: hostWindow
    width: 1100; height: 60; visible: true
    property bool processing: false
    property bool queued: false
    property bool exporting: false
    ManualEditorToolbar {{
        objectName: "toolbar"; width: parent.width; hasVideo: true
        exportEnabled: !hostWindow.processing && !hostWindow.queued && !hostWindow.exporting
    }}
}}'''.encode(), QUrl())
    assert component.isReady(), [error.toString() for error in component.errors()]
    window = component.create()
    try:
        QTest.qWait(40)
        toolbar = window.findChild(QObject, "toolbar")
        button = window.findChild(QObject, "manualExportButton")
        spy = QSignalSpy(toolbar.exportRequested)
        geometry = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        assert button.isEnabled()
        for busy in ("processing", "queued", "exporting"):
            window.setProperty(busy, True)
            app.processEvents()
            assert not button.isEnabled()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, geometry)
            assert spy.count() == 0
            window.setProperty(busy, False)
            app.processEvents()
            assert button.isEnabled()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, geometry)
        assert spy.count() == 1
    finally:
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
