"""Published Manual subtitle language is independent of the next translation."""

import re


def manual_subtitle_language(video, segments=None):
    stored = str(getattr(video, "subtitle_language", "") or "").lower()
    if stored:
        return stored
    requested = str(getattr(video, "target_language", "vi") or "vi")
    if segments is None and requested != "zh":
        return requested  # Keep legacy cache keys and avoid unnecessary I/O.
    if segments is None:
        from haizflow.pipeline.manual_tools import _load_segments

        segments = _load_segments(video, validate=False)
    text = " ".join(str(item.get("text") or "") for item in segments)
    if not text.strip():
        return "vi"  # No published Chinese result yet.
    han = len(re.findall(r"[\u3400-\u9fff]", text))
    letters = sum(character.isalpha() for character in text)
    if han >= 2 and han / max(1, letters) >= .2:
        return "zh"
    if requested != "zh":
        return requested
    return "vi" if any(ord(character) > 127 for character in text if character.isalpha()) else "en"
