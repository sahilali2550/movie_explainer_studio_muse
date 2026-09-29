"""
tests/test_dialogue_anchored_micro_cuts.py

TDD test suite for Dialogue-Anchored Micro-Cuts (3-5s Pacing):
1. ScriptEngine extracts [DIALOGUE_REF: "..."] from storyboard script.
2. anchor_scenes_to_dialogue binds scene timestamps directly to exact dialogue quote matches.
3. build_audio_locked_scene_clips creates 3.0s-5.0s sequential micro-cuts for narrations > 5s.
4. Micro-cuts are centered around the anchored dialogue timestamp and concatenate to exact block duration.
5. Short blocks (<=5s) remain as single clips without unnecessary slicing.
"""

import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.script_engine import SceneBlock, ScriptEngine
from app.services.video_engine import VideoEngine


class TestDialogueRefExtractionAndAnchoring:
    """
    Verifies that [DIALOGUE_REF: "..."] is extracted from storyboard scripts
    and bound to real movie dialogue timestamps via anchor_scenes_to_dialogue.
    """

    def test_extract_dialogue_ref_from_storyboard(self):
        script = """
[SCENE: 00:00 - 00:30]
[DIALOGUE_REF: "I will find you and I will kill you"]
[VOICEOVER]
Bryan Mills delivers his chilling ultimatum over the phone to the kidnappers.

[SCENE: 00:30 - 01:00]
[DIALOGUE_REF: "Good luck"]
[VOICEOVER]
The kidnapper responds with cold indifference before hanging up.
"""
        blocks = ScriptEngine.parse_storyboard_blocks(script)
        assert len(blocks) == 2

        # Check dialogue_ref field is populated
        assert hasattr(blocks[0], "dialogue_ref")
        assert blocks[0].dialogue_ref == "I will find you and I will kill you"
        assert blocks[1].dialogue_ref == "Good luck"

        # Check dialogue_ref is stripped from spoken voiceover
        assert "DIALOGUE_REF" not in blocks[0].narration_text
        assert "I will find you and I will kill you" not in blocks[0].narration_text
        assert "Bryan Mills delivers his chilling ultimatum" in blocks[0].narration_text

    def test_anchor_scenes_to_dialogue_with_dialogue_ref(self):
        """
        Verify that exact quotes in dialogue_ref bind scene timestamps directly
        to the exact dialogue cues in dialogue_timeline.
        """
        blocks = [
            SceneBlock(
                movie_start=0.0,
                movie_end=30.0,
                narration_text="The hero warns the villains of their fate.",
                word_count=8,
                dialogue_ref="I will find you and I will kill you"
            ),
            SceneBlock(
                movie_start=30.0,
                movie_end=60.0,
                narration_text="The villain coldly laughs off the threat.",
                word_count=7,
                dialogue_ref="Good luck"
            )
        ]

        dialogue_timeline = [
            {"start": 45.2, "end": 49.8, "text": "Can you hear me?"},
            {"start": 182.5, "end": 188.0, "text": "I will find you and I will kill you."},
            {"start": 190.2, "end": 193.0, "text": "Good luck."},
            {"start": 250.0, "end": 255.0, "text": "We need backup now!"},
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        # First block should be anchored to 182.5 (exact dialogue quote match)
        assert abs(anchored[0].movie_start - 182.5) < 0.1, (
            f"Expected movie_start ~182.5, got {anchored[0].movie_start}"
        )

        # Second block should be anchored to 190.2 (exact dialogue quote match)
        assert abs(anchored[1].movie_start - 190.2) < 0.1, (
            f"Expected movie_start ~190.2, got {anchored[1].movie_start}"
        )


class TestDialogueAnchoredMicroCuts:
    """
    Verifies the 3-5 second micro-cut rule in VideoEngine.build_audio_locked_scene_clips.
    """

    def test_long_narration_produces_3_to_5s_micro_cuts(self):
        """
        When narration_dur = 15.0s (>5s), build_audio_locked_scene_clips should
        slice 3 to 4 sequential micro-cuts (each 3.0s to 5.0s) centered around
        the anchored dialogue timestamp and concatenate them into the block clip.
        """
        block = SceneBlock(
            movie_start=182.5,  # Anchored dialogue timestamp
            movie_end=220.0,    # Scene window
            narration_text="Bryan Mills speaks with ice in his veins, declaring that his particular set of skills makes him a nightmare for men like them.",
            word_count=23,
            dialogue_ref="I will find you and I will kill you"
        )
        block.narration_start = 0.0
        block.narration_end = 15.0
        block.speech_dur = 15.0

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

                result = VideoEngine.build_audio_locked_scene_clips(
                    input_video=fake_video,
                    scene_blocks=[block],
                    temp_dir=tmp,
                    job_id="job_cuts",
                    output_video=fake_output
                )

        assert result is not None

        # Find micro-cut slice commands for block 0 (commands creating _mc_\d+\.mp4)
        mc_commands = [
            c for c in ffmpeg_commands
            if any(isinstance(arg, str) and re.search(r"_mc_\d+\.mp4$", arg) for arg in c)
        ]
        assert len(mc_commands) >= 3, (
            f"Expected at least 3 micro-cuts for 15s narration, got {len(mc_commands)}. "
            f"Commands: {mc_commands}"
        )

        # Check each micro-cut duration is in [3.0, 5.0]s
        total_mc_dur = 0.0
        for mc_cmd in mc_commands:
            t_idx = [i for i, arg in enumerate(mc_cmd) if arg == "-t"]
            assert t_idx, f"-t flag missing in micro-cut command: {mc_cmd}"
            dur = float(mc_cmd[t_idx[-1] + 1])
            assert 3.0 <= dur <= 5.05, f"Micro-cut duration {dur}s must be within [3.0, 5.0]s"
            total_mc_dur += dur

        # Sum of micro-cuts must equal narration_dur (15.0s)
        assert abs(total_mc_dur - 15.0) < 0.1, (
            f"Total micro-cut duration {total_mc_dur} != 15.0s"
        )

        # Verify concat command exists for the micro-cuts
        concat_cmds = [
            c for c in ffmpeg_commands
            if any(isinstance(arg, str) and "_mc_concat.txt" in arg for arg in c)
        ]
        assert len(concat_cmds) == 1, "Expected exactly 1 concat command for micro-cuts"

        # Verify micro-cut start timestamps are near the anchored dialogue timestamp (182.5)
        first_cut_ss = None
        for i, arg in enumerate(mc_commands[0]):
            if arg == "-ss":
                first_cut_ss = float(mc_commands[0][i + 1])
                break
        assert first_cut_ss is not None
        # Centered around or starting near 182.5 (e.g. within [175.0, 190.0])
        assert abs(first_cut_ss - 182.5) <= 10.0, (
            f"Micro-cut start {first_cut_ss} is not centered near dialogue timestamp 182.5"
        )

    def test_short_narration_remains_single_cut(self):
        """
        When narration_dur <= 5.0s (e.g. 4.0s), a single cut should be used
        without dividing into unnecessary sub-clips.
        """
        block = SceneBlock(
            movie_start=50.0,
            movie_end=70.0,
            narration_text="He checks his watch.",
            word_count=4
        )
        block.narration_start = 0.0
        block.narration_end = 4.0
        block.speech_dur = 4.0

        ffmpeg_commands = []
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = os.path.join(tmp, "movie.mp4")
            Path(fake_video).write_bytes(b"\x00" * 100)
            fake_output = os.path.join(tmp, "assembled.mp4")

            with patch("app.services.video_engine.subprocess.run") as mock_run, \
                 patch("app.services.video_engine.VideoEngine.get_duration", return_value=3000.0), \
                 patch("app.services.video_engine.VideoEngine.probe_media", return_value={"duration": 3000.0}):

                def run_side(cmd, **kwargs):
                    ffmpeg_commands.append(list(cmd))
                    m = MagicMock(); m.returncode = 0
                    for arg in cmd:
                        if isinstance(arg, str) and arg.endswith(".mp4") and arg != fake_video:
                            Path(arg).write_bytes(b"\x00" * 50)
                    return m
                mock_run.side_effect = run_side

                VideoEngine.build_audio_locked_scene_clips(
                    input_video=fake_video,
                    scene_blocks=[block],
                    temp_dir=tmp,
                    job_id="test_short",
                    output_video=fake_output
                )

        # For <= 5.0s, no intermediate _mc_ clips should be created
        mc_commands = [c for c in ffmpeg_commands if "_mc_" in str(c)]
        assert len(mc_commands) == 0, (
            f"Short 4.0s narration should NOT create micro-cut sub-clips. Got: {mc_commands}"
        )
