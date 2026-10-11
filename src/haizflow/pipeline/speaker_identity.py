"""Offline speaker identities; no source-language audio is passed to TTS."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import wave
from pathlib import Path

from haizflow.config import MEDIA_PROCESS_TIMEOUT_SECONDS, MODELS_DIR, TMP_DIR
from haizflow.pipeline.process_registry import check_cancellation, communicate_process
from haizflow.utils.ffmpeg import _binary
from haizflow.utils.atomic_file import atomic_json

from haizflow.core.bundled_models import MODEL_FILE, MODEL_SIZE, MODEL_SHA256, MODEL_REVISION, MODEL_URL as MODEL_URL
IDENTITY_VERSION = "wespeaker-stable-target-voices-v5-expressive-consensus"


def _pitch_samples(audio, *, preserve_gaps=False):
    """Reliable F0 frames at 16 kHz, using YIN's normalized difference.

    Unlike windowed autocorrelation peaks, the first periodic minimum is
    less prone to selecting a strong second harmonic as the fundamental.
    Mathematical reference: de Cheveigne & Kawahara, JASA 111 (2002).
    Work is bounded by the eight-second turn supplied by the caller.
    """
    import numpy as np

    audio = np.asarray(audio, dtype=np.float64)
    if len(audio) < 1024 or not np.isfinite(audio).all():
        return []
    frames = np.lib.stride_tricks.sliding_window_view(audio, 1024)[::800].copy()
    frames -= frames.mean(axis=1, keepdims=True)
    voiced = np.sqrt(np.mean(frames ** 2, axis=1)) >= 20
    if not voiced.any():
        return []
    if not preserve_gaps:
        frames = frames[voiced]
    max_lag = 229
    correlation = np.fft.irfft(np.abs(np.fft.rfft(frames, n=2048)) ** 2, n=2048)[:, :max_lag + 1]
    energy = np.concatenate((np.zeros((len(frames), 1)), np.cumsum(frames ** 2, axis=1)), axis=1)
    lags = np.arange(1, max_lag + 1)
    difference = np.maximum(0, energy[:, 1024 - lags] + energy[:, -1, None]
                            - energy[:, lags] - 2 * correlation[:, 1:])
    difference /= 1024 - lags
    normalized = difference * lags / np.maximum(np.cumsum(difference, axis=1), 1e-12)
    estimates = []
    for frame_index, curve in enumerate(normalized):
        if preserve_gaps and not voiced[frame_index]:
            estimates.append(float("nan"))
            continue
        count = len(estimates)
        # Only accept clearly periodic frames; noise/silence is not evidence
        # of either a male or female voice.
        for index in range(39, max_lag - 1):
            if curve[index] < 0.18 and curve[index] <= curve[index - 1] and curve[index] < curve[index + 1]:
                denominator = curve[index - 1] - 2 * curve[index] + curve[index + 1]
                offset = (0.5 * (curve[index - 1] - curve[index + 1]) / denominator
                          if denominator > 1e-12 else 0.0)
                estimates.append(16000 / (index + 1 + float(np.clip(offset, -.5, .5))))
                break
        if preserve_gaps and len(estimates) == count:
            estimates.append(float("nan"))
    return estimates


def _voice_pitch_profile(samples):
    """Choose a preset family, not a person's gender, from voiced evidence.

    A raised/shouted phrase should not change the whole speaker to a female
    preset. Retain their lower, habitual register across reliable frames.
    Overlapping registers and sparse evidence are explicitly uncertain.
    """
    import numpy as np

    values = np.asarray(samples, dtype=np.float64)
    values = values[np.isfinite(values) & (values >= 70) & (values <= 400)]
    if len(values) < 8:
        return "male", True, None
    lower, median, upper = np.percentile(values, [25, 50, 75])
    kind = "male" if lower < 175 else "female"
    uncertain = len(values) < 20 or (160 <= lower <= 200) or upper - lower > 85
    return kind, bool(uncertain), round(float(median), 1)


def _speaker_voice_profile(turn_samples):
    """Retain sustained low-register evidence even when shouting dominates.

    Pooling every frame weights long/high phrases too heavily. A habitual
    register must be sustained within one turn, not assembled from isolated
    subharmonic errors or from the ends of several unrelated turns. This
    chooses an acoustic preset family, not a person's gender identity.
    """
    import numpy as np

    turns = [np.asarray(samples, dtype=np.float64) for samples in turn_samples]
    kind, uncertain, pitch = _voice_pitch_profile([value for turn in turns for value in turn])
    for turn in turns:
        if len(turn) < 8:
            continue
        # Require 400 ms of periodic evidence within at most one second.
        # Normal speech has unvoiced consonants: allow gaps under 200 ms,
        # but never bridge a higher-register sample or a long silent gap.
        for start in range(len(turn) - 7):
            window = turn[start:start + 20]
            higher_or_invalid = np.flatnonzero(np.isfinite(window) & ((window < 70) | (window >= 160)))
            if len(higher_or_invalid):
                window = window[:higher_or_invalid[0]]
            positions = np.flatnonzero(np.isfinite(window))
            if len(positions) < 8:
                continue
            values = window[positions]
            gaps = ~np.isfinite(window[positions[0]:positions[-1] + 1])
            long_gap = len(gaps) >= 4 and np.lib.stride_tricks.sliding_window_view(gaps, 4).all(axis=1).any()
            if not long_gap and np.all((values >= 70) & (values < 160)) and np.ptp(values) <= 45:
                return "male", uncertain or kind != "male", pitch
    return kind, uncertain, pitch


def verify_model(root: Path) -> Path:
    from haizflow.core.model_integrity import _verify

    if root.resolve() == bundled_model_root().resolve():
        from haizflow.core.bundled_models import verify_speaker
        return verify_speaker(root)
    _verify(
        root, kind="speaker identification", revision=MODEL_REVISION, expected={MODEL_FILE: (MODEL_SIZE, MODEL_SHA256)}
    )
    return root / MODEL_FILE


def bundled_model_root() -> Path:
    from haizflow.core.paths import bundle_root, project_root
    import sys

    base = bundle_root() / "models" if getattr(sys, "frozen", False) else project_root() / "build" / "bundled-models"
    return base / "speaker-identification"


def model_root() -> Path:
    """Prefer the immutable Core asset; retain existing development storage."""
    bundled = bundled_model_root()
    return bundled if (bundled / MODEL_FILE).is_file() else Path(MODELS_DIR) / "speaker-identification"


def _features(audio):
    """Kaldi-compatible 80-bin, 25/10 ms, Hamming filterbank + CMN."""
    import numpy as np

    audio = np.asarray(audio, dtype=np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(audio, 400)[::160].copy()
    frames -= frames.mean(axis=1, keepdims=True)
    frames[:, 1:] -= 0.97 * frames[:, :-1].copy()
    frames[:, 0] *= 0.03
    frames *= np.hamming(400).astype(np.float32)
    power = np.abs(np.fft.rfft(frames, n=512)) ** 2
    mel = 1127 * np.log1p(np.arange(257) * (16000 / 512) / 700)
    edges = np.linspace(1127 * np.log1p(20 / 700), 1127 * np.log1p(8000 / 700), 82)
    weights = np.maximum(
        0,
        np.minimum(
            (mel[None, :] - edges[:-2, None]) / (edges[1:-1] - edges[:-2])[:, None],
            (edges[2:, None] - mel[None, :]) / (edges[2:] - edges[1:-1])[:, None],
        ),
    )
    features = np.log(np.maximum(power @ weights.T, np.finfo(np.float32).eps)).astype(np.float32)
    return features - features.mean(axis=0, keepdims=True)


def _cluster(embeddings, threshold=0.50):
    """Complete-link clustering avoids chaining unrelated speakers together."""
    import numpy as np

    if not len(embeddings):
        return []
    vectors = np.array(embeddings, dtype=np.float32, copy=True)
    if vectors.ndim != 2 or not np.isfinite(vectors).all():
        raise ValueError("Invalid speaker embeddings.")
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-8)
    similarities = vectors @ vectors.T
    np.fill_diagonal(similarities, -np.inf)
    groups = [[i] for i in range(len(vectors))]
    while len(groups) > 1:
        i, j = np.unravel_index(np.argmax(similarities), similarities.shape)
        if similarities[i, j] < threshold:
            break
        i, j = sorted((int(i), int(j)))
        groups[i].extend(groups.pop(j))
        merged = np.minimum(similarities[i], similarities[j])
        similarities[i, :] = merged
        similarities[:, i] = merged
        similarities = np.delete(np.delete(similarities, j, axis=0), j, axis=1)
        np.fill_diagonal(similarities, -np.inf)
    labels = [0] * len(vectors)
    for identity, group in enumerate(sorted(groups, key=min)):
        for index in group:
            labels[index] = identity
    return labels


def _assign_identities(vectors, anchors, anchor_labels):
    """Retain reliable cluster members; use exemplars for expressive short turns.

    A single average loses the range of an identity (quiet speech vs shouting).
    Combine it with the best matching anchor examples, without allowing one
    outlier to replace the centroid or moving anchors into another cluster.
    """
    import numpy as np

    centers, scores = [], []
    for label in sorted(set(anchor_labels)):
        members = vectors[[anchors[i] for i, identity in enumerate(anchor_labels) if identity == label]]
        center = members.mean(axis=0)
        center /= max(float(np.linalg.norm(center)), 1e-8)
        centers.append(center)
        similarities = np.sort(vectors @ members.T, axis=1)
        examples = similarities[:, -min(3, len(members)):].mean(axis=1)
        scores.append(0.65 * (vectors @ center) + 0.35 * examples)
    scores = np.asarray(scores).T
    labels = list(np.argmax(scores, axis=1).astype(int))
    for anchor, label in zip(anchors, anchor_labels):
        labels[anchor] = label
    return labels, scores


def _reconcile_expressive_groups(vectors, labels):
    """Reconcile style-split identities using independent turn exemplars.

    Complete-link anchor clustering can split quiet and shouted speech.
    Merge only strongly matching aggregate identities with corroborating
    turns on BOTH sides, and a margin over competing identities. Never use
    pitch or adjacency as evidence that two turns belong to the same person.
    Representatives are bounded so long videos cannot produce an N² matrix.
    """
    import numpy as np

    identities = sorted(set(labels))
    if len(identities) < 2:
        return labels
    members = [np.flatnonzero(np.asarray(labels) == identity) for identity in identities]
    centers = np.asarray([vectors[group].mean(axis=0) for group in members])
    centers /= np.maximum(np.linalg.norm(centers, axis=1, keepdims=True), 1e-8)
    similarity = centers @ centers.T
    np.fill_diagonal(similarity, -np.inf)
    allowed = np.eye(len(identities), dtype=bool)
    candidates = []
    for left in range(len(identities)):
        for right in range(left + 1, len(identities)):
            score = float(similarity[left, right])
            if score < .70 or min(len(members[left]), len(members[right])) < 2:
                continue
            others = [i for i in range(len(identities)) if i not in (left, right)]
            competing = max((max(similarity[left, i], similarity[right, i]) for i in others), default=-1)
            if score - competing < .12:
                continue
            examples = [vectors[group[np.linspace(0, len(group) - 1, min(24, len(group)), dtype=int)]]
                        for group in (members[left], members[right])]
            matches = examples[0] @ examples[1].T >= .52
            if np.count_nonzero(matches.any(axis=0)) < 2 or np.count_nonzero(matches.any(axis=1)) < 2:
                continue
            allowed[left, right] = allowed[right, left] = True
            candidates.append((score, left, right))
    groups = [{i} for i in range(len(identities))]
    for _score, left, right in sorted(candidates, reverse=True):
        left_group = next(group for group in groups if left in group)
        right_group = next(group for group in groups if right in group)
        if left_group is right_group:
            continue
        # Do not chain A≈B≈C into A=C when A/C have no direct evidence.
        if all(allowed[a, b] for a in left_group for b in right_group):
            left_group.update(right_group)
            groups.remove(right_group)
    remap = {identities[old]: new for new, group in enumerate(sorted(groups, key=min)) for old in group}
    return [remap[label] for label in labels]


def _label_turns(vectors, valid_indices, segments):
    import numpy as np

    # Prefer full turns so phonetic variation in tiny fragments does not
    # create extra people; do not collapse a dialogue with only short turns.
    anchors = [i for i, index in enumerate(valid_indices)
               if float(segments[index]["end"]) - float(segments[index]["start"]) >= 1.8]
    if not anchors:
        anchors = list(range(len(valid_indices)))
    if len(anchors) > 192:
        anchors = [anchors[i] for i in np.linspace(0, len(anchors) - 1, 192, dtype=int)]
    labels, scores = _assign_identities(vectors, anchors, _cluster(vectors[anchors]))
    reconciled = _reconcile_expressive_groups(vectors, labels)
    if reconciled != labels:
        _assignments, scores = _assign_identities(vectors, anchors, [reconciled[anchor] for anchor in anchors])
        # Recompute confidence for the merged profiles, but retain established
        # turn memberships. A changed centroid must not move unrelated short
        # turns between speakers as a side effect of reconciling two styles.
        return reconciled, scores
    return labels, scores


def identify(audio_path: str, segments: list[dict], video_id: str, progress=None, *,
             model_directory: str = "", runtime_callback=None) -> list[dict]:
    """Use the built-in CPU backend in an isolated worker; release before TTS."""
    import numpy as np
    from haizflow.pipeline.speaker_runtime import SpeakerSession

    model = verify_model(Path(model_directory) if model_directory else model_root())
    session = SpeakerSession(model, runtime_callback)
    embeddings, valid_indices, pitches = [], [], {}
    with tempfile.TemporaryDirectory(prefix="speaker-audio-", dir=TMP_DIR) as directory:
        decoded = Path(directory) / "speech.wav"
        process = subprocess.Popen(
            [
                _binary("ffmpeg"),
                "-y",
                "-v",
                "error",
                "-i",
                audio_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(decoded),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _, errors = communicate_process(
            video_id, process, label="speaker audio", timeout_seconds=MEDIA_PROCESS_TIMEOUT_SECONDS
        )
        if process.returncode:
            raise RuntimeError(errors[-500:])
        with wave.open(str(decoded), "rb") as stream:
            for index, segment in enumerate(segments):
                check_cancellation(video_id)
                start = max(0, int(float(segment.get("start") or 0) * 16000))
                end = min(stream.getnframes(), int(float(segment.get("end") or 0) * 16000), start + 8 * 16000)
                if end - start < 8000:
                    continue
                stream.setpos(min(start, stream.getnframes()))
                audio = np.frombuffer(stream.readframes(end - start), dtype="<i2").astype(np.float32)
                if np.sqrt(np.mean(audio**2)) < 20:
                    continue
                embedding = session.run(_features(audio)[None, :, :])[0].reshape(-1)
                if not np.isfinite(embedding).all():
                    raise RuntimeError("Speaker model returned invalid embeddings.")
                embeddings.append(embedding)
                valid_indices.append(index)
                # Pitch is used only to choose a natural target-language preset,
                # never as the identity classifier.
                pitches[index] = _pitch_samples(audio, preserve_gaps=True)
                if progress:
                    progress(index + 1, len(segments))
    if not embeddings:
        raise RuntimeError("Không đủ lời nói rõ để nhận diện người nói. Hãy chọn một giọng đọc.")
    vectors = np.asarray(embeddings, dtype=np.float32)
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-8)
    labels, scores = _label_turns(vectors, valid_indices, segments)
    label_by_index = dict(zip(valid_indices, labels))
    male = [
        "omnivoice:male",
        "omnivoice:deep",
        "omnivoice:male_mature",
        "omnivoice:male_high",
        "omnivoice:male_tenor",
        "omnivoice:male_narrator",
        "omnivoice:male_elder_high",
        "omnivoice:male_soft",
        "omnivoice:male_broadcast",
        "omnivoice:tech_presenter",
        "omnivoice:trailer_deep",
        "omnivoice:documentary",
    ]
    female = [
        "omnivoice:female",
        "omnivoice:female_low",
        "omnivoice:bright",
        "omnivoice:female_mature",
        "omnivoice:female_soprano",
        "omnivoice:female_narrator",
        "omnivoice:female_elder_high",
        "omnivoice:female_gentle",
        "omnivoice:female_confident",
        "omnivoice:show_host",
        "omnivoice:radio_warm",
    ]
    voices, pitch_profiles, counts = {}, {}, {"male": 0, "female": 0}
    for label in sorted(set(labels)):
        turns = [pitches[index] for index, identity in label_by_index.items() if identity == label]
        kind, uncertain, pitch = _speaker_voice_profile(turns)
        pitch_profiles[label] = (uncertain, pitch)
        choices = female if kind == "female" else male
        voices[label] = choices[counts[kind] % len(choices)]
        counts[kind] += 1
    positions = {index: position for position, index in enumerate(valid_indices)}
    result = []
    for index, segment in enumerate(segments):
        label = label_by_index.get(index)
        if label is None:
            # Only unvoiced/very short fragments inherit the nearest reliable
            # turn. No new random identity is introduced for "Go!" etc.
            nearest = min(valid_indices, key=lambda i: abs(float(segments[i]["start"]) - float(segment["start"])))
            label = label_by_index[nearest]
        position = positions.get(index)
        confidence = round(max(0.0, float(scores[position, label])), 3) if position is not None else 0.0
        margin = (float(scores[position, label] - np.max(np.delete(scores[position], label)))
                  if position is not None and scores.shape[1] > 1 else confidence)
        result.append(
            {
                **segment,
                "speaker_id": f"speaker-{label + 1}",
                "speaker_voice": voices[label],
                "speaker_voice_uncertain": pitch_profiles[label][0],
                "speaker_pitch_hz": pitch_profiles[label][1],
                "speaker_confidence": confidence,
                "speaker_uncertain": confidence < 0.55 or margin < 0.10
                or float(segment["end"]) - float(segment["start"]) < 1.8,
            }
        )
    return result


def _valid_map(value, segments) -> bool:
    from haizflow.pipeline.omnivoice_tts import OMNIVOICE_VOICE_INSTRUCTIONS

    valid = (
        isinstance(value, list)
        and len(value) == len(segments)
        and all(
            isinstance(item, dict)
            and isinstance(item.get("speaker_id"), str)
            and bool(item["speaker_id"])
            and item.get("speaker_voice") in OMNIVOICE_VOICE_INSTRUCTIONS
            and item.get("start") == source.get("start")
            and item.get("end") == source.get("end")
            and item.get("text") == source.get("text")
            for item, source in zip(value, segments)
        )
    )
    if not valid:
        return False
    voices = {}
    for item in value:
        speaker = item["speaker_id"]
        voice = item["speaker_voice"]
        if speaker in voices and voices[speaker] != voice:
            return False
        voices[speaker] = voice
    return True


def prepare_speakers(audio_path: str, segments: list[dict], video_id: str, progress=None) -> list[dict]:
    """Persist a source-bound map, independent of translated text and edits."""
    from haizflow.services.external_tasks import run_external_task
    from haizflow.services.external_engine import shared_external_engine_pool
    # CPU has a lower cold-load cost and turn latency on real speech.
    selected_device = "cpu"
    stat = Path(audio_path).stat()
    key = hashlib.sha256(
        json.dumps(
            [IDENTITY_VERSION, str(Path(audio_path).resolve()), stat.st_size, stat.st_mtime_ns, segments],
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    path = Path(audio_path).parent / f"speaker-map-{key}.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if _valid_map(cached, segments):
            return cached
    except (OSError, ValueError, TypeError):
        pass
    # A validated source-bound map is sufficient for subtitle-only edits.
    # Do not re-verify/load the model when only regenerated speech needs it.
    directory = model_root()
    verify_model(directory)
    try:
        result = run_external_task(
            "speaker",
            "speaker_identification",
            {"audio_path": audio_path, "segments": segments, "video_id": video_id,
             "model_directory": str(directory), "device": selected_device},
            video_id,
            context={"device": selected_device},
            progress_callback=progress,
            isolate_source=True,
        )
        if result is None:
            raise RuntimeError("Cần cài bộ xử lý ONNX để nhận diện người nói.")
        identified = result.get("segments")
        if not _valid_map(identified, segments):
            raise RuntimeError("Speaker engine returned an invalid identity map.")
    finally:
        shared_external_engine_pool().release({"speaker"})
    atomic_json(path, identified)
    return identified
