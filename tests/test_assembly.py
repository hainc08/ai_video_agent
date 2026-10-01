import json
import shutil
import subprocess

import pytest

from app.assembler import ffmpeg as assembler
from app.assembler.ffmpeg import AssemblyError, assemble, fit_audio
from app.assembler.subtitles import build_ass
from app.config import AssemblerConfig
from app.providers.base import ClipRequest
from app.providers.fake_video import FakeVideoProvider

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed on this machine",
)
# Small frames and the fastest preset keep these real encodes quick.
CFG = AssemblerConfig(output_width=270, output_height=480, x264_preset="ultrafast")


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    video = [s for s in data["streams"] if s["codec_type"] == "video"]
    audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
    return video, audio, float(data["format"]["duration"])


async def make_job(folder, scenes=((1, "9:16", 4), (2, "9:16", 4)), aspect="9:16"):
    """A job folder with clips and fitted voices, as the finisher prepares it."""
    provider = FakeVideoProvider("ffmpeg")
    clips, voices, durations = [], [], []
    for scene_no, clip_aspect, seconds in scenes:
        clip = folder / "clips" / f"scene_{scene_no:02d}.mp4"
        operation = await provider.submit(ClipRequest(scene_no, "x", clip_aspect, seconds))
        await provider.download(operation, clip)
        raw = folder / "audio" / f"scene_{scene_no:02d}.raw.mp3"
        raw.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg("-f", "lavfi", "-i", f"sine=frequency={300 + 100 * scene_no}:sample_rate=24000:duration=2", str(raw))
        voice = folder / "audio" / f"scene_{scene_no:02d}.wav"
        await fit_audio(raw, voice, target_sec=seconds, cfg=CFG)
        clips.append(clip)
        voices.append(voice)
        durations.append(seconds)
    size = assembler.output_size(aspect, CFG)
    subtitles = folder / "subtitles.ass"
    starts = [sum(durations[:i]) for i in range(len(durations))]
    subtitles.write_text(
        build_ass([(start, start + d, f"Phụ đề cảnh {i + 1}: tiếng Việt có dấu") for i, (start, d) in enumerate(zip(starts, durations))],
                  size=size, font="Arial"),
        encoding="utf-8",
    )
    return {"clips": clips, "voices": voices, "subtitles": subtitles, "size": size, "output": folder / "final.mp4"}


async def test_final_video_has_the_output_size_the_summed_length_and_both_streams(tmp_path):
    parts = await make_job(tmp_path)

    await assemble(tmp_path, **parts, music=None, logo=None, fonts_dir=None, cfg=CFG)

    video, audio, duration = probe(tmp_path / "final.mp4")
    assert [(s["codec_name"], s["width"], s["height"], s["pix_fmt"], s["r_frame_rate"]) for s in video] == [
        ("h264", 270, 480, "yuv420p", "30/1")
    ]
    assert [s["codec_name"] for s in audio] == ["aac"]
    assert abs(duration - 8) <= 0.3
    assert not list(tmp_path.glob("*.part*"))


async def test_music_shorter_than_the_video_and_a_logo_are_mixed_in(tmp_path):
    parts = await make_job(tmp_path)
    music = tmp_path / "assets" / "music.mp3"
    music.parent.mkdir()
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100:duration=2", str(music))
    logo = tmp_path / "assets" / "logo.png"
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=200x100:d=1", "-frames:v", "1", str(logo))

    await assemble(tmp_path, **parts, music=music, logo=logo, fonts_dir=None, cfg=CFG)

    video, audio, duration = probe(tmp_path / "final.mp4")
    assert (len(video), len(audio)) == (1, 1)
    assert abs(duration - 8) <= 0.3  # the 2-second music is looped, not the end of the video


async def test_clips_of_other_shapes_are_fitted_to_a_landscape_output(tmp_path):
    parts = await make_job(tmp_path, scenes=((1, "16:9", 4), (2, "1:1", 4), (3, "9:16", 4)), aspect="16:9")

    await assemble(tmp_path, **parts, music=None, logo=None, fonts_dir=None, cfg=CFG)

    video, _, duration = probe(tmp_path / "final.mp4")
    assert (video[0]["width"], video[0]["height"]) == (480, 270)
    assert abs(duration - 12) <= 0.3


async def test_a_job_folder_with_spaces_and_a_fonts_folder_work(tmp_path):
    folder = tmp_path / "thư mục có dấu cách" / "job 1"
    parts = await make_job(folder)
    fonts = tmp_path / "phông chữ"
    fonts.mkdir()

    await assemble(folder, **parts, music=None, logo=None, fonts_dir=fonts, cfg=CFG)

    assert abs(probe(folder / "final.mp4")[2] - 8) <= 0.3


async def test_subtitles_are_burned_into_the_picture(tmp_path):
    with_text = await make_job(tmp_path / "a")
    without = await make_job(tmp_path / "b")
    without["subtitles"].write_text(build_ass([], size=without["size"], font="Arial"), encoding="utf-8")

    await assemble(tmp_path / "a", **with_text, music=None, logo=None, fonts_dir=None, cfg=CFG)
    await assemble(tmp_path / "b", **without, music=None, logo=None, fonts_dir=None, cfg=CFG)

    def frame(folder):
        target = folder / "frame.png"
        ffmpeg("-ss", "1", "-i", str(folder / "final.mp4"), "-frames:v", "1", str(target))
        return target.read_bytes()

    assert frame(tmp_path / "a") != frame(tmp_path / "b")


async def test_a_missing_clip_is_reported_by_name(tmp_path):
    parts = await make_job(tmp_path)
    parts["clips"][1].unlink()

    with pytest.raises(AssemblyError, match="scene_02.mp4"):
        await assemble(tmp_path, **parts, music=None, logo=None, fonts_dir=None, cfg=CFG)

    assert not (tmp_path / "final.mp4").exists()


async def test_a_result_over_the_size_limit_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(assembler, "MAX_OUTPUT_BYTES", 1000)
    parts = await make_job(tmp_path)

    with pytest.raises(AssemblyError, match="100 MB"):
        await assemble(tmp_path, **parts, music=None, logo=None, fonts_dir=None, cfg=CFG)

    assert not (tmp_path / "final.mp4").exists()


async def test_reassembling_replaces_the_previous_file(tmp_path):
    parts = await make_job(tmp_path)
    (tmp_path / "final.mp4").write_bytes(b"old")

    await assemble(tmp_path, **parts, music=None, logo=None, fonts_dir=None, cfg=CFG)

    assert (tmp_path / "final.mp4").stat().st_size > 1000
