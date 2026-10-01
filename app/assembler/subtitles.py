"""Builds the .ass subtitle file burned into the final video (one line per scene)."""
from __future__ import annotations

_FONT_SIZE_RATIO = 0.065  # of the frame's short side
_MARGIN_V_RATIO = 0.12  # of the frame height, from the bottom
_MARGIN_H_RATIO = 0.07  # of the frame width, each side

# ASS has no escape for these: braces open override blocks and a backslash starts a code
# such as \N, so text from the plan gets look-alike characters instead.
_SAFE = str.maketrans({"{": "(", "}": ")", "\\": "/"})


def _timestamp(seconds: float) -> str:
    centis = round(seconds * 100)
    hours, rest = divmod(centis, 360_000)
    minutes, rest = divmod(rest, 6_000)
    secs, centis = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _clean(text: str) -> str:
    return " ".join(text.translate(_SAFE).split())  # also folds line breaks and runs of spaces


def build_ass(scenes: list[tuple[float, float, str]], *, size: tuple[int, int], font: str) -> str:
    """ASS text for `scenes` = [(start_sec, end_sec, subtitle)], laid out for a frame of `size`."""
    width, height = size
    font_size = round(min(width, height) * _FONT_SIZE_RATIO)
    outline = max(2, round(font_size * 0.06))
    margin_h = round(width * _MARGIN_H_RATIO)
    margin_v = round(height * _MARGIN_V_RATIO)
    font_name = _clean(font).replace(",", " ")  # a comma would shift every field of the style line

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # white text, black outline, soft shadow, bottom centre (alignment 2)
        f"Style: Default,{font_name},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline},1,2,{margin_h},{margin_h},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for start, end, text in scenes:
        text = _clean(text)
        if text:
            lines.append(f"Dialogue: 0,{_timestamp(start)},{_timestamp(end)},Default,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"
