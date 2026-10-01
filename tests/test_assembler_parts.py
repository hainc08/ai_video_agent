import shutil
import subprocess

import pytest

from app.assembler.ffmpeg import AssemblyError, fit_audio, output_size, probe_duration, run_ffmpeg
from app.assembler.subtitles import build_ass
from app.config import AssemblerConfig

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed on this machine",
)
CFG = AssemblerConfig()


def tone(path, seconds):
    """A mono 24 kHz MP3-like source, as the TTS service returns (a sine tone instead of speech)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=440:sample_rate=24000:duration={seconds}", str(path)],
        check=True,
    )
    return path


# --- output size ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "aspect, size", [("9:16", (1080, 1920)), ("16:9", (1920, 1080)), ("1:1", (1080, 1080))]
)
def test_output_size_keeps_the_short_side_at_1080(aspect, size):
    assert output_size(aspect, CFG) == size


def test_output_size_of_an_unknown_aspect_is_an_error():
    with pytest.raises(AssemblyError):
        output_size("4:3", CFG)


# --- ffmpeg helpers ---------------------------------------------------------------------


@needs_ffmpeg
async def test_probe_duration_reads_the_length(tmp_path):
    assert abs(await probe_duration(tone(tmp_path / "a.mp3", 2.5), "ffprobe") - 2.5) <= 0.1


@needs_ffmpeg
async def test_probe_duration_of_a_non_media_file_is_an_assembly_error(tmp_path):
    (tmp_path / "x.mp3").write_text("not audio", encoding="utf-8")

    with pytest.raises(AssemblyError):
        await probe_duration(tmp_path / "x.mp3", "ffprobe")
    with pytest.raises(AssemblyError):
        await probe_duration(tmp_path / "missing.mp3", "ffprobe")


async def test_a_failing_ffmpeg_run_reports_what_ffmpeg_said(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg is not installed on this machine")

    with pytest.raises(AssemblyError, match="FFmpeg") as excinfo:
        await run_ffmpeg("ffmpeg", ["-i", "does-not-exist.mp4", "out.mp4"], cwd=tmp_path)

    assert "does-not-exist.mp4" in str(excinfo.value)


async def test_a_missing_ffmpeg_binary_is_an_assembly_error(tmp_path):
    with pytest.raises(AssemblyError, match="assembler.ffmpeg_path"):
        await run_ffmpeg("no-such-ffmpeg-xyz", ["-version"], cwd=tmp_path)


# --- fitting a voice track to its scene ---------------------------------------------------


@needs_ffmpeg
@pytest.mark.parametrize(
    "source_sec, target_sec, speed, cut",
    [
        (2.0, 6, 1.0, False),   # shorter: padded with silence
        (6.0, 6, 1.0, False),   # exact
        (7.2, 6, 1.2, False),   # a little long: sped up
        (12.0, 6, 1.5, True),   # far too long: sped up as far as allowed, then cut
    ],
)
async def test_voice_is_made_exactly_as_long_as_its_scene(tmp_path, source_sec, target_sec, speed, cut):
    source = tone(tmp_path / "voice.mp3", source_sec)
    target = tmp_path / "audio" / "scene_01.wav"

    result = await fit_audio(source, target, target_sec=target_sec, cfg=CFG)

    assert abs(await probe_duration(target, "ffprobe") - target_sec) <= 0.05
    assert result.speed == pytest.approx(speed, abs=0.02)
    assert result.cut is cut


@needs_ffmpeg
async def test_fitted_voice_is_48k_stereo_wav(tmp_path):
    target = tmp_path / "scene_01.wav"

    await fit_audio(tone(tmp_path / "voice.mp3", 1.0), target, target_sec=4, cfg=CFG)

    info = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels", "-of", "csv=p=0", str(target)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert info == "pcm_s16le,48000,2"


@needs_ffmpeg
async def test_fitting_an_unreadable_voice_file_is_an_assembly_error_and_leaves_no_output(tmp_path):
    (tmp_path / "voice.mp3").write_text("not audio", encoding="utf-8")

    with pytest.raises(AssemblyError):
        await fit_audio(tmp_path / "voice.mp3", tmp_path / "scene_01.wav", target_sec=4, cfg=CFG)

    assert not (tmp_path / "scene_01.wav").exists()


# --- subtitles ------------------------------------------------------------------------


def dialogue_lines(ass):
    return [line for line in ass.splitlines() if line.startswith("Dialogue:")]


def test_ass_has_one_timed_line_per_scene_at_the_frame_size():
    ass = build_ass(
        [(0, 4, "Mất nửa tiếng soạn email?"), (4, 10, "Tóm tắt chuỗi thư và viết nháp."), (10, 16, "Soát lỗi trước khi gửi.")],
        size=(1080, 1920), font="Be Vietnam Pro",
    )

    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Style: Default,Be Vietnam Pro," in ass
    assert dialogue_lines(ass) == [
        "Dialogue: 0,0:00:00.00,0:00:04.00,Default,,0,0,0,,Mất nửa tiếng soạn email?",
        "Dialogue: 0,0:00:04.00,0:00:10.00,Default,,0,0,0,,Tóm tắt chuỗi thư và viết nháp.",
        "Dialogue: 0,0:00:10.00,0:00:16.00,Default,,0,0,0,,Soát lỗi trước khi gửi.",
    ]


def test_ass_times_past_a_minute_are_formatted():
    ass = build_ass([(58, 64, "Cảnh cuối")], size=(1080, 1920), font="Arial")

    assert dialogue_lines(ass) == ["Dialogue: 0,0:00:58.00,0:01:04.00,Default,,0,0,0,,Cảnh cuối"]


def test_ass_text_cannot_inject_override_codes_or_break_the_line():
    ass = build_ass(
        [(0, 4, "Giảm {\\b1}50%{\\b0}\nngay \\N hôm nay,  nhé")], size=(1080, 1920), font="Arial"
    )

    (line,) = dialogue_lines(ass)
    text = line.split("0,0,0,,", 1)[1]
    assert "{" not in text and "}" not in text and "\\" not in text and "\n" not in text
    assert "50%" in text and "hôm nay, nhé" in text


def test_scenes_without_a_subtitle_get_no_line():
    ass = build_ass([(0, 4, "   "), (4, 8, "Có chữ")], size=(1080, 1920), font="Arial")

    assert len(dialogue_lines(ass)) == 1


def test_ass_style_scales_with_the_frame():
    tall = build_ass([(0, 4, "x")], size=(1080, 1920), font="Arial")
    wide = build_ass([(0, 4, "x")], size=(1920, 1080), font="Arial")

    def style(ass):
        return next(line for line in ass.splitlines() if line.startswith("Style: Default")).split(",")

    assert int(style(tall)[2]) == int(style(wide)[2])  # font size follows the short side
    assert int(style(tall)[21]) > int(style(wide)[21])  # bottom margin follows the height
    assert "PlayResX: 1920" in wide and "PlayResY: 1080" in wide


def test_a_font_name_cannot_break_the_style_line():
    ass = build_ass([(0, 4, "x")], size=(1080, 1920), font="Bad, Font\nName")

    style = next(line for line in ass.splitlines() if line.startswith("Style: Default"))
    assert style.count(",") == 22
