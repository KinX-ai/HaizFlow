"""Export editor captions without rendering or modifying project artifacts."""

import os
import tempfile
from datetime import timedelta
from pathlib import Path

import srt

from haizflow.schemas.editor import EditorDocument
from haizflow.services import project_store, video_store
from haizflow.utils.atomic_file import replace_with_retry


def compose_document_srt(document: EditorDocument | None, text_overrides: dict | None = None) -> str:
    if document is None:
        return ""
    visible_tracks = {track.track_id for track in document.tracks
                      if track.kind == "subtitle" and track.visible}
    overrides = text_overrides or {}
    subtitles = []
    for clip in sorted(document.clips, key=lambda item: (item.start_ms, item.clip_id)):
        if clip.kind != "subtitle" or clip.track_id not in visible_tracks or not clip.enabled:
            continue
        text = str(overrides.get(clip.segment_id, clip.name)).replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text or clip.duration_ms <= 0:
            continue
        subtitles.append(srt.Subtitle(
            index=len(subtitles) + 1,
            start=timedelta(milliseconds=clip.start_ms),
            end=timedelta(milliseconds=clip.start_ms + clip.duration_ms),
            content=text,
        ))
    return srt.compose(subtitles, eol="\r\n")


def validate_srt_destination(destination: str | Path) -> Path:
    target = Path(destination)
    if not target.suffix:
        target = target.with_suffix(".srt")
    if not target.is_absolute() or target.suffix.casefold() != ".srt":
        raise ValueError("Choose an absolute SRT destination.")
    project_store.validate_new_project_name(target.name)
    if not target.parent.is_dir():
        raise FileNotFoundError("Export folder or drive is unavailable.")
    roots = [Path(project_store.project_root_for_key(record["key"])) for record in project_store.list_projects()]
    roots.append(Path(video_store.LEGACY_VIDEO_WORKSPACES_DIR))
    for root in roots:
        if target.resolve().is_relative_to(root.resolve()):
            raise ValueError("Choose a location outside managed project storage.")
    if target.exists() and not target.is_file():
        raise ValueError("Export destination is not a regular file.")
    return target


def save_srt(content: str, destination: str | Path) -> Path:
    if not content.strip():
        raise ValueError("No subtitles to export.")
    target = validate_srt_destination(destination)
    descriptor, temporary = tempfile.mkstemp(prefix=".haizflow-srt-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        replace_with_retry(temporary, target)
    finally:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass
    return target
