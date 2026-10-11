"""Replacement must isolate the new media from editor state and idle writes."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from haizflow.desktop.project_import_controller import ProjectImportController
from haizflow.schemas.editor import EditorClip, EditorTrack
from haizflow.schemas.video import VideoConfig
from haizflow.services import editor_documents, editor_view_state, project_store, video_store


def test_manual_replacement_clears_layers_assets_drafts_and_preserves_model_choices(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECT_INDEX_PATH", str(tmp_path / "projects.json"))
    monkeypatch.setattr(video_store, "LEGACY_VIDEO_WORKSPACES_DIR", str(tmp_path / "legacy"))
    monkeypatch.setattr(editor_documents, "get_video_duration", lambda _: 10)
    config = VideoConfig(project_type="manual", project_name="Reset", project_directory=str(tmp_path),
                         watermark_text="OLD", speech_recognition_model="small-cpu", translation_model="q4")
    video = video_store.create_video(f"reset-{tmp_path.name}", "old.mp4", config)
    Path(video.files["video_input"]).write_bytes(b"old input")
    video.files["background_music"] = str(tmp_path / "old.mp3")
    video_store.save_video(video)
    old = editor_documents.ensure(video)
    old.tracks.append(EditorTrack(track_id="old-cover", kind="ocr", name="Old", order=0))
    old.clips.append(EditorClip(clip_id="old-cover", track_id="old-cover", kind="ocr", duration_ms=4000))
    editor_documents.save(video, old)
    editor_view_state.save(video.video_id, {"stage": 7})
    source = tmp_path / "new.mp4"
    source.write_bytes(b"new input")
    replaced = video_store.replace_video_input(video.video_id, str(source))
    clean = editor_documents.ensure(replaced)
    assert not {"watermark-1", "music-1", "old-cover"}.intersection(c.clip_id for c in clean.clips)
    assert not any(c.kind in {"voice", "subtitle"} for c in clean.clips)
    assert clean.sequence.duration_ms == 10000
    assert replaced.speech_recognition_model == "small-cpu"
    assert replaced.translation_model == "q4"
    assert replaced.manual_tool_generations == {"source": 1}
    # A rollback copy exists, but is never used as the new editor document.
    assert list((editor_documents.document_path(video.video_id).parent / "source-replacements").glob("*.json"))
    other_draft = {"watermark_text": "OTHER"}
    host = SimpleNamespace(_selected_video_id=video.video_id,
                           _manual_settings_drafts={video.video_id: {"watermark_text": "OLD"}, "other": other_draft},
                           _editor_transform_drafts={"watermark-1": {}}, _manual_cache_indexed={video.video_id},
                           _manual_edit_history=Mock(), _manual_editor_document=Mock(), _manual_subtitles=Mock(),
                           _select_video=Mock(), _manual_voice_video_id=video.video_id,
                           _manual_voice_refresh_pending=True, _manual_voice_refresh_enabled=True)
    assert ProjectImportController(host)._reset_replaced_source_view(replaced)
    assert host._manual_settings_drafts == {"other": other_draft}
    assert host._editor_transform_drafts == {}
    assert host._manual_cache_indexed == set()
    assert not host._manual_voice_refresh_pending
    host._manual_editor_document.clear.assert_called_once()
    host._manual_editor_document.load.assert_called_once_with(replaced)
    host._manual_subtitles.reset_source.assert_called_once_with(video.video_id)
    host._select_video.assert_called_once_with(replaced)
    assert editor_view_state.load(video.video_id)["stage"] == 0


def test_source_generation_advances_on_every_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECT_INDEX_PATH", str(tmp_path / "projects.json"))
    monkeypatch.setattr(video_store, "LEGACY_VIDEO_WORKSPACES_DIR", str(tmp_path / "legacy"))
    video = video_store.create_video(f"generation-{tmp_path.name}", "old.mp4",
                                    VideoConfig(project_type="manual", project_directory=str(tmp_path)))
    source = tmp_path / "same.mp4"
    source.write_bytes(b"same source")
    first = video_store.replace_video_input(video.video_id, str(source))
    second = video_store.replace_video_input(video.video_id, str(source))
    assert first.manual_tool_generations == {"source": 1}
    assert second.manual_tool_generations == {"source": 2}
