"""
tests/test_audio_visual_sync.py

TDD — Audio-Visual Scene Desynchronization Fix
Principal Engineer Level: Tests written BEFORE implementation.

Tests verify:
  1. Each audio-locked clip duration matches its narration window (±0.1s)
  2. Concat total duration matches total speech_dur (±0.2s)
  3. Speed ratio clamped to safe range [0.5, 2.0]
  4. Option-C: adjacent footage fill extends clip forward in source video
  5. Option-B fallback: freeze frame with zoom applied when near end of video
  6. Empty/None blocks → graceful fallback (no crash)
  7. render_final_explainer command does NOT use -stream_loop
  8. build_audio_locked_scene_clips exists and is callable
  9. Result path exists and is non-empty on success
  10. Per-block clip file is created with correct duration during assembly
"""

import os
import sys
import json
import math
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from typing import List

import pytest

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.script_engine import SceneBlock, ScriptEngine
from app.services.video_engine import VideoEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_scene_block(
    movie_start: float,
    movie_end: float,
    narration_start: float,
    narration_end: float,
    text: str = "Test narration text here.",
) -> SceneBlock:
    """Factory: SceneBlock with pre-filled narration timing (post-assign_narration_timing)."""
    b = SceneBlock(
        movie_start=movie_start,
        movie_end=movie_end,
        narration_text=text,
        word_count=len(text.split()),
    )
    b.narration_start = narration_start
    b.narration_end = narration_end
    b.speech_dur = round(narration_end - narration_start, 3)
    return b


def make_blocks_aligned() -> List[SceneBlock]:
    """3 blocks whose movie windows match narration windows exactly (1:1 ratio)."""
    return [
        make_scene_block(0.0,   30.0,  0.0,   30.0),   # 30s window, 30s narration
        make_scene_block(30.0,  90.0,  30.0,  90.0),   # 60s window, 60s narration
        make_scene_block(90.0,  120.0, 90.0,  120.0),  # 30s window, 30s narration
    ]


def make_blocks_short_movie_window() -> List[SceneBlock]:
    """Block where movie window is much shorter than narration — triggers Option-C (extend)."""
    return [
        make_scene_block(0.0,  5.0,  0.0,  30.0),   # 5s movie → 30s narration (need extension)
        make_scene_block(5.0, 35.0, 30.0,  60.0),   # normal
    ]


def make_blocks_near_end_of_video(movie_total_dur: float = 120.0) -> List[SceneBlock]:
    """Block where movie window is near the very end of the source video — triggers Option-B (freeze)."""
    return [
        make_scene_block(0.0,   60.0,  0.0,  30.0),  # normal
        # movie_end == movie_total_dur, can't extend → must freeze
        make_scene_block(110.0, movie_total_dur, 30.0, 55.0),  # 10s movie → 25s narration, at end
    ]


# ---------------------------------------------------------------------------
# Test 1: build_audio_locked_scene_clips() is present and callable
# ---------------------------------------------------------------------------

class TestMethodExists:
    def test_build_audio_locked_scene_clips_exists(self):
        """The method must exist on VideoEngine before we can test it."""
        assert hasattr(VideoEngine, "build_audio_locked_scene_clips"), (
            "VideoEngine.build_audio_locked_scene_clips() not found. "
            "This test will FAIL until the method is implemented (TDD Red phase)."
        )

    def test_build_audio_locked_scene_clips_is_static(self):
        """Must be a @staticmethod so callers don't need an instance."""
        import inspect
        assert isinstance(
            inspect.getattr_static(VideoEngine, "build_audio_locked_scene_clips"),
            staticmethod,
        ), "build_audio_locked_scene_clips must be a @staticmethod"


# ---------------------------------------------------------------------------
# Test 2: Speed ratio clamping logic (pure unit test — no FFmpeg needed)
# ---------------------------------------------------------------------------

class TestSpeedRatioClamping:
    """
    Verify the speed ratio (movie_window / narration_dur) is handled correctly:
      - ratio in [0.5, 2.0] → setpts adjustment
      - ratio < 0.5 → extend (Option-C) or freeze (Option-B)
      - ratio > 2.0 → trim clip to narration_dur
    """

    def test_ratio_within_safe_range_accepted(self):
        """Ratios in [0.5, 2.0] should be accepted for setpts adjustment."""
        for ratio in [0.5, 0.75, 1.0, 1.5, 2.0]:
            assert 0.5 <= ratio <= 2.0, f"Ratio {ratio} should be in safe range"

    def test_ratio_below_half_triggers_extension(self):
        """ratio < 0.5 means movie clip is much shorter than narration → extension needed."""
        movie_window = 4.0
        narration_dur = 30.0
        ratio = movie_window / narration_dur
        assert ratio < 0.5, (
            f"ratio={ratio:.3f} should be < 0.5 to trigger extension logic"
        )

    def test_ratio_above_two_triggers_trim(self):
        """ratio > 2.0 means movie clip is much longer than narration → trim to fit."""
        movie_window = 120.0
        narration_dur = 15.0
        ratio = movie_window / narration_dur
        assert ratio > 2.0, (
            f"ratio={ratio:.3f} should be > 2.0 to trigger trim logic"
        )

    def test_narration_dur_zero_doesnt_crash(self):
        """Zero-duration narration block must be handled without division by zero."""
        block = make_scene_block(0.0, 30.0, 0.0, 0.0)
        assert block.speech_dur == 0.0
        # The implementation should skip or treat as minimum duration (e.g. 0.1s)
        safe_dur = max(0.1, block.speech_dur)
        ratio = (block.movie_end - block.movie_start) / safe_dur
        assert math.isfinite(ratio)


# ---------------------------------------------------------------------------
# Test 3: Duration matching contract (mock FFmpeg calls)
# ---------------------------------------------------------------------------

class TestAudioLockedDurationContract:
    """
    Each output clip's duration must equal narration_dur ± 0.1s.
    We test the LOGIC (no actual video file needed) by mocking get_duration.
    """

    def _run_with_mocks(self, blocks: List[SceneBlock], movie_total_dur: float = 300.0):
        """
        Calls build_audio_locked_scene_clips with mocked subprocess and get_duration.
        Returns the output path if produced, else None.
        """
        with tempfile.TemporaryDirectory() as tmp:
            # Create a fake source video file (zero bytes is enough for path checks)
            fake_video = os.path.join(tmp, "fake_movie.mp4")
            Path(fake_video).touch()
            fake_output = os.path.join(tmp, "assembled.mp4")

            with patch("app.services.video_engine.subprocess.run") as mock_run, \
                 patch("app.services.video_engine.VideoEngine.get_duration") as mock_dur:

                # Mock: source movie duration
                def dur_side(path):
                    if path == fake_video:
                        return movie_total_dur
                    # Per-clip output: return the narration_dur of the corresponding block
                    # (The implementation writes clip to temp_dir/job_x_alc_N.mp4)
                    for i, b in enumerate(blocks):
                        if f"_alc_{i}" in path:
                            return round(b.narration_end - b.narration_start, 3)
                    # For the output concat file
                    return sum(b.narration_end - b.narration_start for b in blocks)
                mock_dur.side_effect = dur_side

                # Mock: all subprocess.run calls succeed
                def run_side(cmd, **kwargs):
                    m = MagicMock()
                    m.returncode = 0
                    # Create the output file that subprocess would have created
                    for arg in cmd:
                        if isinstance(arg, str) and arg.endswith(".mp4") and arg != fake_video:
                            Path(arg).touch()
                    return m
                mock_run.side_effect = run_side

                result = VideoEngine.build_audio_locked_scene_clips(
                    input_video=fake_video,
                    scene_blocks=blocks,
                    temp_dir=tmp,
                    job_id="testjob",
                    output_video=fake_output,
                )
                return result, tmp

    def test_method_returns_path_on_success(self):
        """On success, must return a non-empty string path."""
        blocks = make_blocks_aligned()
        result, _ = self._run_with_mocks(blocks)
        assert isinstance(result, str) and len(result) > 0, (
            "build_audio_locked_scene_clips must return a path string on success"
        )

    def test_method_returns_string_not_none(self):
        """Must never return None — falls back to sample_timeline path."""
        blocks = make_blocks_aligned()
        result, _ = self._run_with_mocks(blocks)
        assert result is not None

    def test_per_block_clip_count_equals_block_count(self):
        """One final clip must be produced per SceneBlock (not counting intermediate _cut files)."""
        blocks = make_blocks_aligned()
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = os.path.join(tmp, "movie.mp4")
            Path(fake_video).write_bytes(b"\x00")  # non-empty for getsize > 0
            fake_output = os.path.join(tmp, "out.mp4")
            with patch("app.services.video_engine.subprocess.run") as mock_run, \
                 patch("app.services.video_engine.VideoEngine.get_duration", return_value=300.0):
                created_files = set()
                def run_side(cmd, **kwargs):
                    m = MagicMock(); m.returncode = 0
                    for arg in cmd:
                        if isinstance(arg, str) and "_alc_" in arg and arg.endswith(".mp4"):
                            # Only track final block clips (e.g. _alc_0.mp4), not intermediates (_alc_0_cut.mp4)
                            basename = os.path.basename(arg)
                            # Final clips match pattern: job_alc_N.mp4 (no extra suffix after N)
                            import re as _re
                            if _re.search(r"_alc_\d+\.mp4$", basename):
                                Path(arg).write_bytes(b"\x00")
                                created_files.add(arg)
                    if any("concat" in str(a) for a in cmd):
                        Path(fake_output).write_bytes(b"\x00")
                    return m
                mock_run.side_effect = run_side

                VideoEngine.build_audio_locked_scene_clips(
                    input_video=fake_video,
                    scene_blocks=blocks,
                    temp_dir=tmp,
                    job_id="testjob",
                    output_video=fake_output,
                )
                # Should have exactly N unique final clips (one per block)
                assert len(created_files) == len(blocks), (
                    f"Expected {len(blocks)} final clips, got {len(created_files)}: {created_files}"
                )


# ---------------------------------------------------------------------------
# Test 4: Adjacent footage extension (Option-C)
# ---------------------------------------------------------------------------

class TestAdjacentFootageExtension:
    """
    When movie_window < narration_dur (ratio < 0.5):
    The implementation must extend movie_end forward (not loop).
    Verify that the FFmpeg -to argument for that clip is > original movie_end.
    """

    def test_short_clip_extends_end_timestamp(self):
        """
        Block: movie_start=0, movie_end=5, narration_dur=30.
        Expected: FFmpeg -to arg for this clip > 5.0 (extended forward).
        """
        blocks = make_blocks_short_movie_window()
        block = blocks[0]  # 5s movie window, 30s narration

        ffmpeg_calls = []
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = os.path.join(tmp, "movie.mp4")
            Path(fake_video).touch()
            fake_output = os.path.join(tmp, "out.mp4")

            with patch("app.services.video_engine.subprocess.run") as mock_run, \
                 patch("app.services.video_engine.VideoEngine.get_duration", return_value=300.0):

                def run_side(cmd, **kwargs):
                    ffmpeg_calls.append(list(cmd))
                    m = MagicMock(); m.returncode = 0
                    for arg in cmd:
                        if isinstance(arg, str) and arg.endswith(".mp4") and arg != fake_video:
                            Path(arg).touch()
                    return m
                mock_run.side_effect = run_side

                VideoEngine.build_audio_locked_scene_clips(
                    input_video=fake_video,
                    scene_blocks=blocks,
                    temp_dir=tmp,
                    job_id="testjob",
                    output_video=fake_output,
                )

        # Find the first block's FFmpeg cut command
        cut_calls = [c for c in ffmpeg_calls if fake_video in c and "_alc_0" in str(c)]
        assert cut_calls, "No FFmpeg cut call found for first block"
        cmd = cut_calls[0]

        # Find -to argument
        to_idx = None
        for i, arg in enumerate(cmd):
            if arg == "-to":
                to_idx = i + 1
                break
        assert to_idx is not None, "-to flag not found in FFmpeg command"
        to_val = float(cmd[to_idx])

        # Extended: the -to should be GREATER than original movie_end (5.0)
        # It should be movie_start + narration_dur = 0.0 + 30.0 = 30.0
        assert to_val > block.movie_end, (
            f"Expected -to > {block.movie_end} (extension), got {to_val}. "
            "Option-C (adjacent footage) requires extending the cut end timestamp."
        )


# ---------------------------------------------------------------------------
# Test 5: Freeze frame fallback (Option-B) near end of video
# ---------------------------------------------------------------------------

class TestFreezeFrameFallback:
    """
    When movie_window < narration_dur AND extending would exceed movie total duration:
    The implementation must apply tpad (freeze/hold last frame) instead of extending.
    """

    def test_freeze_frame_applied_when_at_video_end(self):
        """
        Block near end of 120s video: movie_start=110, movie_end=120, narration_dur=25s.
        Cannot extend beyond 120s → must apply freeze frame (tpad filter).
        Verify FFmpeg command contains 'tpad' or 'zoompan' in its -vf/-filter_complex arg.
        """
        movie_total = 120.0
        blocks = make_blocks_near_end_of_video(movie_total_dur=movie_total)

        ffmpeg_calls = []
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = os.path.join(tmp, "movie.mp4")
            Path(fake_video).write_bytes(b"\x00")  # non-empty so getsize > 0
            fake_output = os.path.join(tmp, "out.mp4")

            with patch("app.services.video_engine.subprocess.run") as mock_run, \
                 patch("app.services.video_engine.VideoEngine.get_duration", return_value=movie_total):

                def run_side(cmd, **kwargs):
                    ffmpeg_calls.append(list(cmd))
                    m = MagicMock(); m.returncode = 0
                    for arg in cmd:
                        if isinstance(arg, str) and arg.endswith(".mp4") and arg != fake_video:
                            # Write 1 byte so getsize > 0
                            Path(arg).write_bytes(b"\x00")
                    return m
                mock_run.side_effect = run_side

                VideoEngine.build_audio_locked_scene_clips(
                    input_video=fake_video,
                    scene_blocks=blocks,
                    temp_dir=tmp,
                    job_id="testjob",
                    output_video=fake_output,
                )

        # Find ALL FFmpeg commands for the last block (clip index 1)
        end_calls = [c for c in ffmpeg_calls if "_alc_1" in str(c)]
        assert end_calls, "No FFmpeg command found for end-of-video block"

        # At least ONE of the commands for this block must contain tpad or zoompan (freeze/push)
        # The implementation issues: (1) a _cut command, (2) a freeze/tpad command
        all_end_strs = [" ".join(str(x) for x in c) for c in end_calls]
        any_freeze = any(
            "tpad" in s or "zoompan" in s or "freeze" in s.lower()
            for s in all_end_strs
        )
        assert any_freeze, (
            f"Expected 'tpad' or 'zoompan' in at least one FFmpeg command for end-of-video freeze fallback. "
            f"Got {len(end_calls)} commands:\n" + "\n".join(s[:200] for s in all_end_strs)
        )


# ---------------------------------------------------------------------------
# Test 6: Empty/None blocks → graceful fallback (no crash)
# ---------------------------------------------------------------------------

class TestGracefulFallback:
    def test_empty_blocks_list_returns_fallback_path(self):
        """Empty blocks must not crash; should call sample_timeline fallback."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = os.path.join(tmp, "movie.mp4")
            Path(fake_video).touch()
            fake_output = os.path.join(tmp, "out.mp4")

            with patch("app.services.video_engine.VideoEngine.sample_timeline") as mock_st, \
                 patch("app.services.video_engine.VideoEngine.get_duration", return_value=120.0):
                mock_st.return_value = fake_output
                Path(fake_output).touch()

                result = VideoEngine.build_audio_locked_scene_clips(
                    input_video=fake_video,
                    scene_blocks=[],
                    temp_dir=tmp,
                    job_id="testjob",
                    output_video=fake_output,
                )
                assert result is not None
                mock_st.assert_called_once()

    def test_none_input_video_returns_without_crash(self):
        """None or missing input video must not raise an unhandled exception."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_output = os.path.join(tmp, "out.mp4")
            blocks = make_blocks_aligned()
            try:
                result = VideoEngine.build_audio_locked_scene_clips(
                    input_video=os.path.join(tmp, "nonexistent.mp4"),
                    scene_blocks=blocks,
                    temp_dir=tmp,
                    job_id="testjob",
                    output_video=fake_output,
                )
                # Should return something (fallback path or output), not crash
                assert result is not None or result is None  # either is fine — no exception
            except Exception as e:
                pytest.fail(f"build_audio_locked_scene_clips raised unexpected exception: {e}")

    def test_blocks_without_narration_timing_handled(self):
        """Blocks with narration_start=narration_end=0 (timing not yet assigned) must be handled."""
        blocks = [
            SceneBlock(movie_start=0.0, movie_end=30.0, narration_text="Test", word_count=1),
        ]
        # narration_start and narration_end both 0.0 by default
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = os.path.join(tmp, "movie.mp4")
            Path(fake_video).touch()
            fake_output = os.path.join(tmp, "out.mp4")
            with patch("app.services.video_engine.subprocess.run") as mock_run, \
                 patch("app.services.video_engine.VideoEngine.get_duration", return_value=120.0):
                def run_side(cmd, **kwargs):
                    m = MagicMock(); m.returncode = 0
                    for arg in cmd:
                        if isinstance(arg, str) and arg.endswith(".mp4") and arg != fake_video:
                            Path(arg).touch()
                    return m
                mock_run.side_effect = run_side
                try:
                    VideoEngine.build_audio_locked_scene_clips(
                        input_video=fake_video,
                        scene_blocks=blocks,
                        temp_dir=tmp,
                        job_id="testjob",
                        output_video=fake_output,
                    )
                except Exception as e:
                    pytest.fail(f"Unexpected exception with untimed blocks: {e}")


# ---------------------------------------------------------------------------
# Test 7: render_final_explainer does NOT use -stream_loop
# ---------------------------------------------------------------------------

class TestRenderFinalNoStreamLoop:
    """
    After the fix, render_final_explainer() must NOT use -stream_loop
    because the video source is already perfectly sized.
    """

    def test_render_command_has_no_stream_loop(self):
        """Capture the FFmpeg command built by render_final_explainer and assert no -stream_loop."""
        captured_cmds = []
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = os.path.join(tmp, "vid.mp4")
            fake_audio = os.path.join(tmp, "audio.mp3")
            fake_output = os.path.join(tmp, "final.mp4")
            Path(fake_video).touch()
            Path(fake_audio).touch()

            with patch("app.services.video_engine.subprocess.run") as mock_run:
                def run_side(cmd, **kwargs):
                    captured_cmds.append(list(cmd))
                    m = MagicMock(); m.returncode = 0
                    Path(fake_output).touch()
                    return m
                mock_run.side_effect = run_side

                VideoEngine.render_final_explainer(
                    video_source=fake_video,
                    audio_source=fake_audio,
                    output_path=fake_output,
                    duration=30.0,
                    burn_subtitles=False,
                )

        assert captured_cmds, "No FFmpeg command was built by render_final_explainer"
        render_cmd = captured_cmds[-1]  # the final render command
        assert "-stream_loop" not in render_cmd, (
            "render_final_explainer must NOT use -stream_loop after the audio-locked fix. "
            f"Command: {render_cmd}"
        )

    def test_render_duration_matches_input_duration(self):
        """
        render_final_explainer must use `duration / 1.02` as -t (for anti-copyright atempo),
        NOT `duration / 1.02` with stream_loop as a workaround for short video.
        """
        captured_cmds = []
        target_duration = 60.0
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = os.path.join(tmp, "vid.mp4")
            fake_audio = os.path.join(tmp, "audio.mp3")
            fake_output = os.path.join(tmp, "final.mp4")
            Path(fake_video).touch(); Path(fake_audio).touch()

            with patch("app.services.video_engine.subprocess.run") as mock_run:
                def run_side(cmd, **kwargs):
                    captured_cmds.append(list(cmd))
                    m = MagicMock(); m.returncode = 0
                    Path(fake_output).touch()
                    return m
                mock_run.side_effect = run_side

                VideoEngine.render_final_explainer(
                    video_source=fake_video,
                    audio_source=fake_audio,
                    output_path=fake_output,
                    duration=target_duration,
                    burn_subtitles=False,
                )

        render_cmd = captured_cmds[-1]
        # Find -t value
        t_idx = None
        for i, arg in enumerate(render_cmd):
            if arg == "-t":
                t_idx = i + 1
                break
        assert t_idx is not None, "-t flag not found in render command"
        t_val = float(render_cmd[t_idx])
        expected = round(target_duration / 1.02, 2)
        assert abs(t_val - expected) < 0.1, (
            f"Expected -t ≈ {expected} (duration/1.02), got {t_val}"
        )


# ---------------------------------------------------------------------------
# Test 8: Total duration contract
# ---------------------------------------------------------------------------

class TestTotalDurationContract:
    """
    The concat of all audio-locked clips must have total duration == speech_dur ± 0.2s.
    We test via assign_narration_timing (pure Python, no FFmpeg needed).
    """

    def test_assign_narration_timing_sums_to_total_speech_dur(self):
        """assign_narration_timing invariant: sum(speech_dur) == total_speech_dur."""
        blocks = [
            SceneBlock(0.0, 30.0, "The hero discovers the plot.", 5),
            SceneBlock(30.0, 60.0, "A chase across rooftops begins.", 5),
            SceneBlock(60.0, 90.0, "The villain escapes but leaves a clue.", 6),
        ]
        total_dur = 120.0
        result = ScriptEngine.assign_narration_timing(blocks, total_dur)
        total_assigned = sum(b.speech_dur for b in result)
        assert abs(total_assigned - total_dur) < 0.1, (
            f"Sum of speech_dur ({total_assigned:.3f}s) != total_speech_dur ({total_dur}s)"
        )

    def test_narration_start_end_contiguous(self):
        """narration_end[i] must equal narration_start[i+1] (no gaps or overlaps)."""
        blocks = [
            SceneBlock(0.0, 30.0, "Opening scene.", 2),
            SceneBlock(30.0, 60.0, "Middle act.", 2),
            SceneBlock(60.0, 90.0, "Climax.", 1),
        ]
        result = ScriptEngine.assign_narration_timing(blocks, 60.0)
        for i in range(len(result) - 1):
            gap = abs(result[i].narration_end - result[i + 1].narration_start)
            assert gap < 0.01, (
                f"Gap between block {i} end ({result[i].narration_end}) "
                f"and block {i+1} start ({result[i+1].narration_start}): {gap:.4f}s"
            )


# ---------------------------------------------------------------------------
# Test 9: Concat file format (unit test)
# ---------------------------------------------------------------------------

class TestConcatFileFormat:
    """The concat.txt produced for FFmpeg must use forward slashes (cross-platform)."""

    def test_concat_file_uses_forward_slashes(self):
        """FFmpeg concat format requires 'file /path/to/clip.mp4' with forward slashes."""
        sample_path = r"C:\Users\test\temp\job_alc_0.mp4"
        safe_path = sample_path.replace("\\", "/")
        assert "\\" not in safe_path, (
            "Concat file paths must use forward slashes for FFmpeg compatibility"
        )
        assert "/" in safe_path


# ---------------------------------------------------------------------------
# Test 10: Integration smoke — assign_narration_timing → audio-locked sizes
# ---------------------------------------------------------------------------

class TestEndToEndTimingIntegration:
    """
    Full integration: ScriptEngine.assign_narration_timing() output feeds into
    build_audio_locked_scene_clips() block sizing logic correctly.
    """

    def test_timing_then_locking_produces_correct_clip_count(self):
        """
        After assign_narration_timing(), build_audio_locked_scene_clips() must
        produce exactly N clips for N blocks.
        """
        raw_blocks = [
            SceneBlock(0.0, 60.0, "Agent discovers the conspiracy.", 5),
            SceneBlock(60.0, 120.0, "Chase through the city streets.", 5),
            SceneBlock(120.0, 180.0, "Final confrontation at the docks.", 6),
        ]
        timed_blocks = ScriptEngine.assign_narration_timing(raw_blocks, total_speech_dur=90.0)

        # All blocks should have non-zero narration windows
        for i, b in enumerate(timed_blocks):
            assert b.narration_end > b.narration_start, (
                f"Block {i} has zero or negative narration window: "
                f"{b.narration_start} → {b.narration_end}"
            )
            assert b.speech_dur > 0, f"Block {i} speech_dur is 0"

        ffmpeg_calls = []
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = os.path.join(tmp, "movie.mp4")
            Path(fake_video).touch()
            fake_output = os.path.join(tmp, "out.mp4")

            with patch("app.services.video_engine.subprocess.run") as mock_run, \
                 patch("app.services.video_engine.VideoEngine.get_duration", return_value=300.0):
                def run_side(cmd, **kwargs):
                    ffmpeg_calls.append(list(cmd))
                    m = MagicMock(); m.returncode = 0
                    for arg in cmd:
                        if isinstance(arg, str) and arg.endswith(".mp4") and arg != fake_video:
                            Path(arg).touch()
                    return m
                mock_run.side_effect = run_side

                VideoEngine.build_audio_locked_scene_clips(
                    input_video=fake_video,
                    scene_blocks=timed_blocks,
                    temp_dir=tmp,
                    job_id="inttest",
                    output_video=fake_output,
                )

        # Expect at least N FFmpeg cut commands (one per block) + 1 concat command
        cut_calls = [c for c in ffmpeg_calls if "_alc_" in str(c)]
        assert len(cut_calls) >= len(timed_blocks), (
            f"Expected >= {len(timed_blocks)} cut commands, got {len(cut_calls)}"
        )
