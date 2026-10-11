"""Preview-only playback rate: bounded PCM, native audio and transport clocks."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from haizflow.desktop.manual_preview_audio_controller import (
    ManualPreviewAudioController, PCM_BUFFER_FRAMES, RATE, mix_frames, mix_playback_frames,
)


def ramp_track():
    samples = np.arange(20000, dtype=np.int16).reshape(-1, 1).repeat(2, axis=1)
    return {"id": "voice", "kind": "voice", "start": 0, "samples": samples}


@pytest.mark.parametrize("rate", [.5, 1, 1.5, 2])
def test_pcm_rate_preserves_timeline_clock_across_chunks_and_fractional_writes(rate):
    track = ramp_track()
    cursor = 0
    for count in (37, 61, 32):
        data = mix_playback_frames([track], cursor, count, {"voice": 1}, rate)
        output = np.frombuffer(data, dtype="<i2").reshape(-1, 2)
        expected = (cursor + np.arange(count) * rate).astype(np.int16)
        np.testing.assert_array_equal(output[:, 0], expected)
        np.testing.assert_array_equal(output[:, 1], expected)
        cursor += count * rate


def test_normal_rate_is_bit_exact_with_existing_mixer_and_mute_is_preserved():
    track = ramp_track()
    assert mix_playback_frames([track], 17, 100, {"voice": .7}, 1) == mix_frames(
        [track], 17, 100, {"voice": .7})
    assert mix_playback_frames([track], 17, 100, {"voice": .7}, 2, {"voice"}) == bytes(400)
    assert mix_playback_frames([track], 0, 0, {"voice": 1}, 2) == b""


@pytest.mark.parametrize("rate", [.5, 1.5, 2])
def test_rate_change_discards_old_queue_without_autoplay_or_cache_rebuild(rate):
    audio = ManualPreviewAudioController()
    audio._sink = Mock()
    audio._native_player = Mock()
    audio._key = "keep-cache"
    track = ramp_track()
    audio._tracks = [track]
    try:
        audio.setPlaybackRate(rate, 11.25)
        assert not audio._playing and not audio._timer.isActive()
        assert audio._cursor == round(11.25 * RATE)
        assert audio.positionSeconds == 11.25
        assert audio._key == "keep-cache" and audio._tracks == [track]
        audio._sink.reset.assert_called_once()
        audio._native_player.setPlaybackRate.assert_called_once_with(rate)
        audio._native_player.play.assert_not_called()
        audio.setPlaybackRate(rate, 12)
        audio._sink.reset.assert_called_once()
        for invalid in (0, -1, 4, float("nan"), float("inf")):
            audio.setPlaybackRate(invalid, 12)
        audio.setPlaybackRate(1, float("nan"))
        assert audio._playback_rate == rate
    finally:
        audio.close()


@pytest.mark.parametrize("rate", [.5, 1, 1.5, 2])
def test_pump_accounts_for_audible_not_buffered_timeline_at_every_rate(rate):
    audio = ManualPreviewAudioController()
    queued = 0
    def write(data):
        nonlocal queued
        # Exercise partial writes with an odd number of stereo frames.
        written_frames = min(4801, len(data) // 4)
        queued += written_frames
        return written_frames * 4
    sink = Mock()
    sink.bufferSize.return_value = PCM_BUFFER_FRAMES * 4
    sink.bytesFree.side_effect = lambda: (PCM_BUFFER_FRAMES - queued) * 4
    sink.start.return_value = SimpleNamespace(write=write)
    audio._sink = sink
    audio._playing = True
    audio._playback_rate = rate
    audio._cursor = RATE * 5
    try:
        audio._pump()
        assert audio._cursor == RATE * 5 + 4801 * rate
        assert audio.positionSeconds == pytest.approx(5)
        queued -= 3001
        audio._pump()
        assert audio.positionSeconds == pytest.approx(5 + 3001 * rate / RATE)
        audio.seek(2)
        assert audio.positionSeconds == 2
        assert audio._cursor == 2 * RATE
        assert audio._playback_rate == rate
    finally:
        audio.close()
