import os
import pytest
from unittest.mock import patch, MagicMock
from app.services.video_engine import VideoEngine
from app.services.script_engine import SceneBlock

def test_build_audio_locked_scene_clips_uses_probe_media(tmp_path, monkeypatch):
    """build_audio_locked_scene_clips should leverage probe_media for input inspection."""
    fake_video = str(tmp_path / "movie.mp4")
    with open(fake_video, "wb") as f: f.write(b"movie")

    probe_called = []
    def mock_probe(path):
        probe_called.append(path)
        return {"duration": 120.0, "width": 1920, "height": 1080, "fps": 30.0}

    monkeypatch.setattr(VideoEngine, "probe_media", mock_probe)

    class MockResult:
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        out_p = cmd[-1]
        with open(out_p, "wb") as f: f.write(b"x" * 500)
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    block = SceneBlock(movie_start=10.0, movie_end=20.0, narration_text="test", word_count=1)
    block.narration_start = 0.0
    block.narration_end = 5.0

    out_p = str(tmp_path / "assembled.mp4")
    res = VideoEngine.build_audio_locked_scene_clips(
        input_video=fake_video,
        scene_blocks=[block],
        temp_dir=str(tmp_path),
        job_id="testjob123",
        output_video=out_p
    )

    assert len(probe_called) == 1
    assert probe_called[0] == fake_video
    assert res == out_p

def test_build_audio_locked_scene_clips_cleans_all_intermediate_files(tmp_path, monkeypatch):
    """Ensures intermediate files like {job_id}_alc_*.mp4 are fully cleaned up in finally block."""
    fake_video = str(tmp_path / "movie.mp4")
    with open(fake_video, "wb") as f: f.write(b"movie")

    # Pre-create leftover intermediate files to simulate crash or mid-loop leftover
    job_id = "cleanleakjob"
    leftover_clip1 = tmp_path / f"{job_id}_alc_0.mp4"
    leftover_clip2 = tmp_path / f"{job_id}_alc_0_cut.mp4"
    leftover_concat = tmp_path / f"{job_id}_alc_concat.txt"
    leftover_clip1.write_bytes(b"temp")
    leftover_clip2.write_bytes(b"temp")
    leftover_concat.write_text("file dummy")

    monkeypatch.setattr(VideoEngine, "probe_media", lambda p: {"duration": 50.0})
    monkeypatch.setattr(VideoEngine, "sample_timeline", lambda *args, **kwargs: str(tmp_path / "fallback.mp4"))

    # Force an exception during loop
    def mock_run_fail(*args, **kwargs):
        raise RuntimeError("FFmpeg crashed mid-render")

    monkeypatch.setattr("subprocess.run", mock_run_fail)

    block = SceneBlock(movie_start=0.0, movie_end=10.0, narration_text="test", word_count=1)
    block.narration_start = 0.0
    block.narration_end = 5.0

    out_p = str(tmp_path / "assembled.mp4")
    VideoEngine.build_audio_locked_scene_clips(
        input_video=fake_video,
        scene_blocks=[block],
        temp_dir=str(tmp_path),
        job_id=job_id,
        output_video=out_p
    )

    # In finally, all leftover intermediate files for this job must be removed
    assert not leftover_clip1.exists(), "leftover_clip1 must be cleaned"
    assert not leftover_clip2.exists(), "leftover_clip2 must be cleaned"
    assert not leftover_concat.exists(), "leftover_concat must be cleaned"

def test_render_final_explainer_anti_copyright_drift_parameter(tmp_path, monkeypatch):
    """Verifies anti_copyright_drift flag enables/disables 1.02x drift and color grade."""
    captured_cmds = []

    class MockResult:
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        out_p = cmd[-1]
        with open(out_p, "wb") as f: f.write(b"x" * 2000)
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    v_in = str(tmp_path / "in.mp4")
    a_in = str(tmp_path / "in.mp3")
    with open(v_in, "wb") as f: f.write(b"v")
    with open(a_in, "wb") as f: f.write(b"a")

    # 1. Default (anti_copyright_drift=True)
    out_default = str(tmp_path / "out_default.mp4")
    VideoEngine.render_final_explainer(
        video_source=v_in,
        audio_source=a_in,
        output_path=out_default,
        duration=100.0,
        burn_subtitles=False
    )
    cmd_default = " ".join(captured_cmds[-1])
    assert "setpts=PTS/1.02" in cmd_default
    assert "atempo=1.02" in cmd_default
    assert "-t 98.04" in cmd_default  # 100 / 1.02 = 98.04

    # 2. Disabled (anti_copyright_drift=False)
    out_no_drift = str(tmp_path / "out_no_drift.mp4")
    VideoEngine.render_final_explainer(
        video_source=v_in,
        audio_source=a_in,
        output_path=out_no_drift,
        duration=100.0,
        burn_subtitles=False,
        anti_copyright_drift=False
    )
    cmd_no_drift = " ".join(captured_cmds[-1])
    assert "setpts=PTS/1.02" not in cmd_no_drift
    assert "atempo=1.02" not in cmd_no_drift
    assert "-t 100.0" in cmd_no_drift
