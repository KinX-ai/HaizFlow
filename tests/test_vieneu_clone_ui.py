from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from haizflow.desktop.audio_preview_controller import AudioPreviewController
from haizflow.desktop.presenters import voice_options_for_language
from haizflow.desktop.project_import_controller import ProjectImportController
from haizflow.desktop.qml_controller import HaizFlowController
from haizflow.services.batch_settings import config_for


@pytest.mark.parametrize("provider", ["vieneu", "vieneu-gpu"])
@pytest.mark.parametrize("project_type", ["manual", "single"])
def test_vieneu_clone_apply_preserves_backend_and_commits_single_speaker(tmp_path, provider, project_type):
    sample = tmp_path / "reference.wav"
    sample.write_bytes(b"reference")
    video = SimpleNamespace(video_id="video", target_language="vi", project_type=project_type,
                            files={"voice_reference": str(sample)})
    host = SimpleNamespace(_selected_video_id="video", _tts_provider=provider, _tts_voice="vieneu:Hải Đăng",
        _speaker_mode="multiple", _processing_queue=SimpleNamespace(contains=lambda _: False),
        persistVideoSettingsFor=Mock(return_value=True), ttsProviderChanged=Mock(), ttsVoiceChanged=Mock(),
        ttsVoiceOptionsChanged=Mock(), speakerModeChanged=Mock(), _audio_preview=Mock())
    with patch("haizflow.desktop.project_import_controller.video_store.get_video", return_value=video):
        assert ProjectImportController(host).apply_voice_reference("video", provider)
        assert host._tts_voice == "vieneu:clone" and host._tts_provider == provider
        assert host._speaker_mode == "single"
        host.persistVideoSettingsFor.assert_called_once_with("video")
        host._tts_voice, host._speaker_mode = "vieneu:Trúc Ly", "multiple"
        host.persistVideoSettingsFor.return_value = False
        assert not ProjectImportController(host).apply_voice_reference("video", provider)
        assert host._tts_voice == "vieneu:Trúc Ly" and host._speaker_mode == "multiple"


@pytest.mark.parametrize("provider", ["vieneu", "vieneu-gpu"])
def test_vieneu_clone_survives_ui_normalization_and_batch_reference_validation(provider):
    host = SimpleNamespace(_voice_options_for_language=lambda language, backend:
                           voice_options_for_language(language, "vi", backend))
    assert HaizFlowController._normalized_voice_for_language(host, "vi", "vieneu:clone", provider) == "vieneu:clone"
    values = {"targetLanguage": "vi", "ttsProvider": provider, "ttsVoice": "vieneu:clone"}
    with pytest.raises(ValueError, match="reference sample"):
        config_for(values)
    assert config_for({**values, "voiceReferencePath": "reference.wav"}).tts_voice == "vieneu:clone"


@pytest.mark.parametrize("provider", ["vieneu", "vieneu-gpu"])
def test_vieneu_clone_preview_uses_reference_without_synthesis(tmp_path, provider):
    sample = tmp_path / "reference.wav"
    sample.write_bytes(b"reference")
    video = SimpleNamespace(files={"voice_reference": str(sample)}, project_type="single")
    preview = AudioPreviewController(SimpleNamespace())
    with patch("haizflow.desktop.audio_preview_controller.video_store.get_video", return_value=video):
        assert Path(preview.voice_sample_path(provider, "vieneu:clone", "vi", selected_video_id="video")) == sample
    assert preview.voice_sample_path(provider, "vieneu:clone", "vi") == ""
