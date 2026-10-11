"""Exercise actual QML viewport culling, including sub-pixel long-video zoom."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QPointF, Property, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

QML_DIR = Path(__file__).parents[1] / "src/haizflow/desktop/qml"


class TimelineBackend(QObject):
    @Property("QVariantMap", constant=True)
    def manualEditorDocumentModel(self):
        return {"selectedTrackId": "subtitles"}


def visual_child(item, predicate):
    if predicate(item):
        return item
    for child in item.childItems():
        if (found := visual_child(child, predicate)) is not None:
            return found
    return None


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        QTest.qWait(20)
        if predicate():
            return
    assert predicate()


@pytest.mark.parametrize("width,duration", [(900, 2530), (1800, 2530), (1000, 3600), (1280, 60)])
def test_subtitles_and_voice_cover_fit_zoom_and_survive_zoom_resize(width, duration):
    # Keep QML engine/window lifetimes isolated from the other desktop suites.
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), str(width), str(duration)],
        capture_output=True, text=True, timeout=45,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def exercise_timeline_viewport(width, duration):
    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlEngine()
    backend = TimelineBackend()
    engine.rootContext().setContextProperty("AppController", backend)
    # Dense cues expose missing delegates, while an isolated final cue can be
    # clicked without neighbouring minimum-width handles obscuring it.
    count = 440 if duration > 60 else 8
    interval = duration * 0.8 / count
    segments = [{"start": index * interval,
                 "end": index * interval + min(4, interval * 0.7),
                 "text": f"Cue {index}"} for index in range(count)]
    segments.append({"start": duration * 0.9, "end": duration - 1, "text": "Final cue"})
    voice_clips = [{"clip_id": f"voice-{index}", "track_id": "voice", "kind": "voice",
                    "enabled": True, "start_ms": round(segment["start"] * 1000),
                    "duration_ms": round((segment["end"] - segment["start"]) * 1000)}
                   for index, segment in enumerate(segments)]
    component = QQmlComponent(engine)
    component.setData(f'''import QtQuick
import QtQuick.Controls.Basic
import "{QML_DIR.as_uri()}"
ApplicationWindow {{
    width: {width}; height: 340; visible: true
    SubtitleTimeline {{
        objectName: "timeline"; anchors.fill: parent; duration: {duration}
        segments: {json.dumps(segments)}
        editorTracks: [{{track_id: "voice", kind: "voice", visible: true, name: "Giọng đọc"}}]
        editorClips: {json.dumps(voice_clips)}
    }}
}}'''.encode(), QUrl())
    assert component.isReady(), [error.toString() for error in component.errors()]
    window = component.create()
    assert isinstance(window, QQuickWindow)
    try:
        timeline = window.findChild(QObject, "timeline")
        selected = []
        timing_changes = []
        timeline.segmentSelected.connect(selected.append)
        timeline.timingCommitted.connect(lambda *args: timing_changes.append(args))

        def assert_final_cues():
            final_subtitle = visual_child(window.contentItem(),
                lambda item: item.objectName() == f"subtitleTimelineClip-{count}")
            assert final_subtitle is not None
            assert final_subtitle.isVisible()
            final_voice = visual_child(window.contentItem(),
                lambda item: item.property("clipId") == f"voice-{count}")
            assert final_voice is not None
            assert final_voice.isVisible()
            assert final_subtitle.x() == pytest.approx(
                timeline.property("trackLeft") + segments[-1]["start"] * timeline.property("pixelsPerSecond"))
            return final_subtitle

        def assert_fit():
            wait_for(lambda: [segment["sourceIndex"] for segment in
                timeline.property("visibleSegments").toVariant()] == list(range(count + 1)))
            visible = timeline.property("visibleSegments").toVariant()
            assert [segment["sourceIndex"] for segment in visible] == list(range(count + 1))
            voice_track = visual_child(window.contentItem(),
                lambda item: item.objectName() == "timelineTrack-voice")
            assert len(voice_track.property("clips").toVariant()) == count + 1
            assert_final_cues()

        assert_fit()
        # The reported 42-minute video fits at less than one pixel per second.
        if duration > 60:
            assert timeline.property("pixelsPerSecond") < 1
        for resized_width in (700, 1600, width):
            window.setWidth(resized_width)
            assert_fit()

        for zoom in ((1.5, 24) if duration > 60 else (24,)):
            timeline.setProperty("position", 0)
            timeline.setProperty("zoomFactor", zoom)
            QTest.qWait(100)
            timeline.setProperty("position", duration * 0.95)
            wait_for(lambda: visual_child(window.contentItem(),
                lambda item: item.objectName() == "subtitleTimelineClip-0") is None)
            assert_final_cues()

        timeline.setProperty("zoomFactor", 1)
        timeline.setProperty("position", 0)
        assert_fit()
        last = assert_final_cues()
        point = last.mapToScene(QPointF(last.width() / 2, last.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(50)
        assert selected == [count]
        assert timing_changes == []
        assert timeline.property("segments").toVariant() == segments
        assert timeline.property("editorClips").toVariant() == voice_clips
    finally:
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    exercise_timeline_viewport(int(sys.argv[1]), int(sys.argv[2]))
