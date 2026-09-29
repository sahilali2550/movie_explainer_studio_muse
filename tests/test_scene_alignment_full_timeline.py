"""
tests/test_scene_alignment_full_timeline.py

TDD tests for:
1. Correct PTS factor calculation (pts_factor = target_block_dur / original_clip_dur) in build_audio_locked_scene_clips.
2. Prevention of video timeline truncation (9m 26s script produces 9m 26s timeline, not 6m 37s).
3. Hold-frame (tpad) buffer in render_final_explainer preventing video EOF truncation.
4. Robust storyboard timestamp parsing across multiple formatting variations.
5. Strict duration invariant: sum(block.speech_dur) == total_speech_dur in assign_narration_timing.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.script_engine import SceneBlock, ScriptEngine
from app.services.video_engine import VideoEngine


class TestPTSMathAndAudioLockedScaling:
    """
    Verifies that build_audio_locked_scene_clips uses the correct PTS scaling formula:
    pts_factor = target_block_dur / original_clip_dur
    and enforces -t target_block_dur.
    """

    def test_pts_factor_is_not_inverted_when_scaling(self):
        """
        When movie_window = 10.0 and narration_dur = 20.0:
        To slow down 10s of footage to fit 20s of speech,
        pts_factor MUST be 20.0 / 10.0 = 2.0 (or extended naturally via Option-C to 20s),
        NEVER 10.0 / 20.0 = 0.5 (which would speed up 2x and shrink the clip to 5s!).
        """
        block = SceneBlock(
            movie_start=100.0,
            movie_end=110.0,  # 10s window
            narration_text="In this dark alley, the investigator examines the crime scene carefully.",
            word_count=12
        )
        block.narration_start = 0.0
        block.narration_end = 20.0  # 20s speech
        block.speech_dur = 20.0

        ffmpeg_commands = []
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = os.path.join(tmp, "movie.mp4")
            Path(fake_video).write_bytes(b"\x00" * 100)
            fake_output = os.path.join(tmp, "assembled.mp4")

            with patch("app.services.video_engine.subprocess.run") as mock_run, \
                 patch("app.services.video_engine.VideoEngine.get_duration", return_value=300.0), \
                 patch("app.services.video_engine.VideoEngine.probe_media", return_value={"duration": 300.0}):

                def run_side(cmd, **kwargs):
                    ffmpeg_commands.append(list(cmd))
                    m = MagicMock()
                    m.returncode = 0
                    for arg in cmd:
                        if isinstance(arg, str) and arg.endswith(".mp4") and arg != fake_video:
                            Path(arg).write_bytes(b"\x00" * 50)
                    return m
                mock_run.side_effect = run_side

                VideoEngine.build_audio_locked_scene_clips(
                    input_video=fake_video,
                    scene_blocks=[block],
                    temp_dir=tmp,
                    job_id="test_pts",
                    output_video=fake_output
                )

        assert ffmpeg_commands, "No FFmpeg commands executed"

        # Verify that setpts=0.5*PTS was NOT generated
        for c in ffmpeg_commands:
            cmd_str = " ".join(str(x) for x in c)
            assert "setpts=0.5" not in cmd_str, (
                f"Inverted PTS detected in command: {cmd_str}. "
                "setpts=0.5 speeds up video, cutting duration in half!"
            )

        # Verify output duration equals 20.0s (as micro-cuts sum or single clip -t)
        mc_cmds = [c for c in ffmpeg_commands if "_mc_" in str(c) and "-t" in c]
        if mc_cmds:
            total_dur = sum(float(c[[idx for idx, arg in enumerate(c) if arg == "-t"][-1] + 1]) for c in mc_cmds)
            assert abs(total_dur - 20.0) < 0.1, f"Expected total micro-cut duration 20.0s, got {total_dur}"
        else:
            clip_cmd = [c for c in ffmpeg_commands if "_alc_0" in str(c)][0]
            assert "-t" in clip_cmd, "Output duration -t flag must be present"
            t_indices = [i for i, arg in enumerate(clip_cmd) if arg == "-t"]
            out_t = float(clip_cmd[t_indices[-1] + 1])
            assert abs(out_t - 20.0) < 0.1, f"Expected output clip duration 20.0s, got {out_t}"

    def test_full_9m26s_script_produces_full_duration_clips(self):
        """
        Simulates the user's scenario: a 1432-word script (~566.0s / 9m 26s total speech)
        across 8 scene blocks. Every clip must output exactly its target block duration.
        """
        total_target_dur = 566.0
        # 8 blocks with various lengths totaling 566.0s
        block_durations = [45.0, 75.0, 80.0, 65.0, 90.0, 70.0, 85.0, 56.0]
        assert sum(block_durations) == total_target_dur

        blocks = []
        curr_t = 0.0
        curr_m = 60.0
        for i, dur in enumerate(block_durations):
            b = SceneBlock(
                movie_start=curr_m,
                movie_end=curr_m + 30.0,  # movie window shorter than narration
                narration_text=f"Scene {i} description with spoken narration.",
                word_count=int(dur * 2.5)
            )
            b.narration_start = curr_t
            curr_t += dur
            b.narration_end = curr_t
            b.speech_dur = dur
            curr_m += 120.0
            blocks.append(b)

        ffmpeg_commands = []
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = os.path.join(tmp, "movie.mp4")
            Path(fake_video).write_bytes(b"\x00" * 100)
            fake_output = os.path.join(tmp, "assembled.mp4")

            with patch("app.services.video_engine.subprocess.run") as mock_run, \
                 patch("app.services.video_engine.VideoEngine.get_duration", return_value=7200.0), \
                 patch("app.services.video_engine.VideoEngine.probe_media", return_value={"duration": 7200.0}):

                def run_side(cmd, **kwargs):
                    ffmpeg_commands.append(list(cmd))
                    m = MagicMock()
                    m.returncode = 0
                    for arg in cmd:
                        if isinstance(arg, str) and arg.endswith(".mp4") and arg != fake_video:
                            Path(arg).write_bytes(b"\x00" * 50)
                    return m
                mock_run.side_effect = run_side

                VideoEngine.build_audio_locked_scene_clips(
                    input_video=fake_video,
                    scene_blocks=blocks,
                    temp_dir=tmp,
                    job_id="test_9m26s",
                    output_video=fake_output
                )

        # Check all 8 clip generation commands (either as micro-cuts or single clip)
        total_assembled_dur = 0.0
        for i in range(len(blocks)):
            mc_cmds = [c for c in ffmpeg_commands if f"_alc_{i}_mc_" in str(c) and "-t" in c]
            if mc_cmds:
                block_mc_dur = sum(
                    float(c[[idx for idx, arg in enumerate(c) if arg == "-t"][-1] + 1])
                    for c in mc_cmds
                )
                assert abs(block_mc_dur - block_durations[i]) < 0.1, (
                    f"Block {i} micro-cuts sum {block_mc_dur}s != expected {block_durations[i]}s"
                )
                total_assembled_dur += block_mc_dur
                concat_cmds = [c for c in ffmpeg_commands if f"_alc_{i}_mc_concat.txt" in str(c)]
                assert len(concat_cmds) == 1, f"Missing concat command for block {i}"
            else:
                clip_cmds = [c for c in ffmpeg_commands if f"_alc_{i}.mp4" in str(c)]
                assert clip_cmds, f"No command generated for block {i}"
                c = clip_cmds[-1]
                t_indices = [idx for idx, arg in enumerate(c) if arg == "-t"]
                out_t = float(c[t_indices[-1] + 1])
                assert abs(out_t - block_durations[i]) < 0.1, (
                    f"Block {i} expected duration {block_durations[i]}s, got {out_t}s"
                )
                total_assembled_dur += out_t

        assert abs(total_assembled_dur - total_target_dur) < 0.5, (
            f"Total assembled duration ({total_assembled_dur}s) != target ({total_target_dur}s). "
            "Timeline truncation occurred!"
        )


class TestRenderFinalHoldFrameBuffer:
    """
    Verifies that render_final_explainer applies tpad hold-frame buffer
    so video streams never terminate before master audio duration.
    """

    def test_render_final_explainer_includes_tpad_buffer(self):
        """
        Verify that render_final_explainer filter complex includes tpad=stop_mode=clone
        to hold the last video frame if video is shorter than audio.
        """
        captured_cmds = []
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = os.path.join(tmp, "video.mp4")
            fake_audio = os.path.join(tmp, "audio.mp3")
            fake_output = os.path.join(tmp, "out.mp4")
            Path(fake_video).touch()
            Path(fake_audio).touch()

            with patch("app.services.video_engine.subprocess.run") as mock_run:
                def run_side(cmd, **kwargs):
                    captured_cmds.append(list(cmd))
                    m = MagicMock()
                    m.returncode = 0
                    Path(fake_output).touch()
                    return m
                mock_run.side_effect = run_side

                VideoEngine.render_final_explainer(
                    video_source=fake_video,
                    audio_source=fake_audio,
                    output_path=fake_output,
                    duration=566.0,  # 9m 26s
                    burn_subtitles=False
                )

        assert captured_cmds, "No FFmpeg render command generated"
        render_cmd = captured_cmds[-1]
        fc_idx = render_cmd.index("-filter_complex") + 1
        filter_complex = render_cmd[fc_idx]

        assert "tpad=stop_mode=clone" in filter_complex, (
            "render_final_explainer filter_complex must contain tpad=stop_mode=clone "
            "to prevent premature video EOF truncation."
        )


class TestStoryboardParsingRobustness:
    """
    Verifies timestamp extraction and narration text cleaning across formats.
    """

    def test_parse_multiple_scene_timestamp_formats(self):
        script = """
[SCENE: 00:00 - 00:45]
[VOICEOVER]
The film begins in an abandoned hospital where Dr. John notices strange noises.

SCENE 2: 00:45 - 01:30
Voiceover: He walks down the dark hallway and discovers an open door.

3. [01:30 - 02:15]
Narration: Inside the room, a mysterious shadow moves across the wall.

**Scene 4: [02:15 - 03:00]**
[VOICEOVER]
He screams as the shadow reveals its true terrifying identity.
"""
        blocks = ScriptEngine.parse_storyboard_blocks(script)
        assert len(blocks) == 4
        assert blocks[0].movie_start == 0.0 and blocks[0].movie_end == 45.0
        assert blocks[1].movie_start == 45.0 and blocks[1].movie_end == 90.0
        assert blocks[2].movie_start == 90.0 and blocks[2].movie_end == 135.0
        assert blocks[3].movie_start == 135.0 and blocks[3].movie_end == 180.0

        # Verify Voiceover:/Narration: prefixes are cleaned
        assert not blocks[1].narration_text.lower().startswith("voiceover:")
        assert not blocks[2].narration_text.lower().startswith("narration:")

    def test_assign_narration_timing_strict_sum_and_positive_durations(self):
        """
        Verify that assign_narration_timing strictly satisfies sum(speech_dur) == total_speech_dur
        and every block has speech_dur > 0 even when cues run close to total duration.
        """
        blocks = [
            SceneBlock(0.0, 30.0, "Block one narration text.", 4),
            SceneBlock(30.0, 60.0, "Block two narration text.", 4),
            SceneBlock(60.0, 90.0, "Block three narration text.", 4),
        ]
        # Simulate edge case cues where early cues take up most time
        cues = [
            {"start": 0.0, "end": 10.0, "text": "Block one narration text"},
            {"start": 10.0, "end": 28.0, "text": "Block two narration text"},
            {"start": 28.0, "end": 30.0, "text": "Block three narration text"},
        ]
        total_speech = 30.0
        result = ScriptEngine.assign_narration_timing(blocks, total_speech, cues=cues)
        assert len(result) == 3
        for b in result:
            assert b.speech_dur > 0.5, f"Block duration {b.speech_dur} must be > 0.5s"

        total_assigned = sum(b.speech_dur for b in result)
        assert abs(total_assigned - total_speech) < 0.01, (
            f"Assigned sum {total_assigned} != total {total_speech}"
        )
