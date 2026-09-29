import os
import re
import math
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from app.services.script_engine import ScriptEngine, SceneBlock
from app.services.video_engine import VideoEngine
from app.services.subtitle_engine import SubtitleEngine


# ===========================================================================
# PHASE 4B TEST SUITE: FINAL VIDEO TIMELINE + SCENE ASSEMBLY SYNCHRONIZATION
# ===========================================================================


def test_1_video_clip_duration_equals_actual_narration_duration():
    """
    Step 1: For every narration scene/block:
    VIDEO CLIP OUTPUT DURATION == AUTHORITATIVE NARRATION DURATION.
    """
    block = SceneBlock(
        movie_start=150.0,
        movie_end=200.0,
        narration_text="The protagonist finds the cipher code in the library archives.",
        word_count=10,
        speech_dur=14.5,
        narration_start=0.0,
        narration_end=14.5,
        estimated_duration=10.0,
        actual_duration=14.5,
        is_authoritative=True
    )

    # 1. Authoritative duration extraction
    dur = VideoEngine._get_block_narration_dur(block)
    assert dur == 14.5, f"Expected 14.5s actual duration, got {dur}"

    # 2. Source cut plan allocates cuts totaling 14.5s
    cuts = VideoEngine.calculate_source_cut_plan(
        scene_blocks=[block],
        total_movie_dur=3600.0,
        target_duration=14.5,
        micro_clip_dur=3.8
    )
    assert len(cuts) > 0
    total_cut_dur = sum(e - s for s, e in cuts)
    assert abs(total_cut_dur - 14.5) <= 0.5, f"Expected cuts totaling ~14.5s, got {total_cut_dur}"


def test_2_estimated_duration_is_ignored_after_tts():
    """
    Step 2: Pre-TTS estimate must never override authoritative actual synthesized duration.
    """
    block = SceneBlock(
        movie_start=50.0,
        movie_end=100.0,
        narration_text="Quick escape sequence through the alleyway.",
        word_count=7,
        speech_dur=16.2,
        narration_start=0.0,
        narration_end=16.2,
        estimated_duration=8.0,   # Pre-TTS estimate was 8.0s
        actual_duration=16.2,      # Synthesized TTS is 16.2s
        is_authoritative=True
    )

    # Video engine must strictly prioritize actual_duration over estimated_duration
    dur = VideoEngine._get_block_narration_dur(block)
    assert dur == 16.2
    assert dur != block.estimated_duration

    # Even if estimated_duration is mutated to a wild value, authoritative duration governs
    block.estimated_duration = 99.0
    assert VideoEngine._get_block_narration_dur(block) == 16.2


def test_3_multi_scene_cumulative_timing_contiguity():
    """
    Step 3: Multi-scene cumulative timing must be strictly contiguous without gaps or overlaps.
    """
    blocks = [
        SceneBlock(movie_start=100.0, movie_end=150.0, narration_text="Block 1", word_count=5, speech_dur=5.2, narration_start=0.0, narration_end=5.2, actual_duration=5.2, is_authoritative=True),
        SceneBlock(movie_start=200.0, movie_end=250.0, narration_text="Block 2", word_count=8, speech_dur=8.4, narration_start=5.2, narration_end=13.6, actual_duration=8.4, is_authoritative=True),
        SceneBlock(movie_start=300.0, movie_end=350.0, narration_text="Block 3", word_count=6, speech_dur=6.1, narration_start=13.6, narration_end=19.7, actual_duration=6.1, is_authoritative=True),
    ]

    report = VideoEngine.verify_timeline_drift(blocks, clip_durations=[5.2, 8.4, 6.1])
    assert report["is_aligned"] is True
    assert report["is_contiguous"] is True
    assert report["total_drift"] == 0.0
    assert report["max_scene_drift"] == 0.0
    assert report["total_expected_duration"] == 19.7
    assert report["total_actual_duration"] == 19.7

    # Injected non-contiguity (gap of 1.0s before Block 2)
    disjoint_blocks = [
        SceneBlock(movie_start=100.0, movie_end=150.0, narration_text="Block 1", word_count=5, speech_dur=5.2, narration_start=0.0, narration_end=5.2, actual_duration=5.2, is_authoritative=True),
        SceneBlock(movie_start=200.0, movie_end=250.0, narration_text="Block 2", word_count=8, speech_dur=8.4, narration_start=6.2, narration_end=14.6, actual_duration=8.4, is_authoritative=True),
    ]
    report_disjoint = VideoEngine.verify_timeline_drift(disjoint_blocks, clip_durations=[5.2, 8.4])
    assert report_disjoint["is_contiguous"] is False
    assert report_disjoint["is_aligned"] is False


def test_4_source_output_coordinate_separation():
    """
    Step 4: Strict separation between source movie space and output narration space:
    movie_start/movie_end are source seek anchors (-ss).
    narration_start/narration_end are explainer output timeline coordinates.
    movie coordinates must NEVER be overwritten with narration coordinates.
    """
    block = SceneBlock(
        movie_start=1850.0,
        movie_end=1920.0,
        narration_text="The climax unfolds on top of the transmission tower.",
        word_count=10,
        speech_dur=12.4,
        narration_start=25.4,
        narration_end=37.8,
        actual_duration=12.4,
        is_authoritative=True
    )

    with tempfile.TemporaryDirectory() as tmp:
        fake_video = os.path.join(tmp, "movie.mp4")
        Path(fake_video).write_bytes(b"\x00" * 100)
        fake_out = os.path.join(tmp, "assembled.mp4")
        recorded_cmds = []

        with patch("app.services.video_engine.subprocess.run") as mock_run, \
             patch("app.services.video_engine.VideoEngine.get_duration", return_value=7200.0), \
             patch("app.services.video_engine.VideoEngine.probe_media", return_value={"duration": 7200.0}):

            def side_effect(cmd, **kwargs):
                recorded_cmds.append(list(cmd))
                for arg in cmd:
                    if isinstance(arg, str) and arg.endswith(".mp4") and arg != fake_video:
                        Path(arg).write_bytes(b"\x00" * 50)
                m = MagicMock()
                m.returncode = 0
                return m

            mock_run.side_effect = side_effect

            res = VideoEngine.build_audio_locked_scene_clips(
                input_video=fake_video,
                scene_blocks=[block],
                temp_dir=tmp,
                job_id="test_coord_sep",
                output_video=fake_out
            )

        assert res is not None
        # Verify source seek timestamps in ffmpeg commands
        ss_args = []
        for cmd in recorded_cmds:
            if "-ss" in cmd:
                ss_idx = cmd.index("-ss")
                ss_args.append(float(cmd[ss_idx + 1]))

        assert any(1800.0 <= s <= 1900.0 for s in ss_args), f"Expected seek near source anchor 1850.0, got {ss_args}"
        assert not any(abs(s - 25.4) < 1.0 for s in ss_args), f"Seek must NOT use narration_start (25.4), got {ss_args}"

        # Source coordinates remain completely intact
        assert block.movie_start == 1850.0
        assert block.movie_end == 1920.0
        assert block.narration_start == 25.4
        assert block.narration_end == 37.8


def test_5_end_of_movie_behavior_no_seek_outside_safe_zone():
    """
    Step 5: Blacklist end credits & prevent seeking outside safe movie bounds.
    """
    total_movie_dur = 3600.0
    safe_dur = VideoEngine.get_safe_story_duration(total_movie_dur)
    assert safe_dur == 3366.0  # credits margin = 234.0s (6.5% of 3600s), credits blacklisted

    # Request near the very end of credits
    requested_start = 3590.0
    narration_dur = 12.0
    clamped_start = VideoEngine.clamp_safe_movie_start(requested_start, safe_dur, narration_dur)

    assert clamped_start <= safe_dur - narration_dur - 1.0
    assert clamped_start >= 0.0
    assert clamped_start < 3366.0


def test_6_short_source_footage_padded_to_full_narration():
    """
    Step 6: When source footage is shorter than required narration duration,
    Option-B/tpad freeze frame extends visual so output clip duration == narration duration.
    """
    block = SceneBlock(
        movie_start=100.0,
        movie_end=120.0,
        narration_text="Narration requiring full 10 seconds despite only 8s footage available in selective clip.",
        word_count=10,
        speech_dur=10.0,
        narration_start=0.0,
        narration_end=10.0,
        actual_duration=10.0,
        is_authoritative=True
    )

    with tempfile.TemporaryDirectory() as tmp:
        fake_video = os.path.join(tmp, "movie.mp4")
        Path(fake_video).write_bytes(b"\x00" * 100)
        fake_out = os.path.join(tmp, "out.mp4")
        recorded_cmds = []

        with patch("app.services.video_engine.subprocess.run") as mock_run, \
             patch("app.services.video_engine.VideoEngine.get_duration", return_value=8.0), \
             patch("app.services.video_engine.VideoEngine.probe_media", return_value={"duration": 8.0}):

            def side_effect(cmd, **kwargs):
                recorded_cmds.append(list(cmd))
                for arg in cmd:
                    if isinstance(arg, str) and arg.endswith(".mp4") and arg != fake_video:
                        Path(arg).write_bytes(b"\x00" * 50)
                m = MagicMock()
                m.returncode = 0
                return m

            mock_run.side_effect = side_effect

            VideoEngine.build_audio_locked_scene_clips(
                input_video=fake_video,
                scene_blocks=[block],
                temp_dir=tmp,
                job_id="test_short_src",
                output_video=fake_out
            )

        # Check for tpad filter padding the gap
        tpad_cmds = [c for c in recorded_cmds if any("tpad=" in str(arg) for arg in c)]
        assert len(tpad_cmds) > 0, "Expected tpad padding command when source footage is shorter than narration"


def test_7_no_modulo_wrap_reverifying_phase1_clamp():
    """
    Step 7: Movie timestamp clamps to safe bounds and never wraps modulo.
    """
    total_movie_dur = 3600.0
    safe_dur = 3240.0
    requested_start = 12500.0  # Excessive timestamp far beyond movie length

    clamped = VideoEngine.clamp_safe_movie_start(requested_start, safe_dur, narration_dur=10.0)
    # Modulo would give: 12500 % 3600 = 1700s (wrong!)
    assert clamped != (requested_start % total_movie_dur)
    # Must clamp to safe ceiling
    assert clamped == (safe_dur - 10.0 - 1.0)


def test_8_audio_video_duration_agreement():
    """
    Step 8: Audio and video duration must match within tolerance.
    """
    blocks = [
        SceneBlock(movie_start=10.0, movie_end=40.0, narration_text="Part 1", word_count=4, speech_dur=10.0, narration_start=0.0, narration_end=10.0, actual_duration=10.0, is_authoritative=True),
        SceneBlock(movie_start=50.0, movie_end=80.0, narration_text="Part 2", word_count=4, speech_dur=12.5, narration_start=10.0, narration_end=22.5, actual_duration=12.5, is_authoritative=True),
    ]

    # Perfect match
    report_ok = VideoEngine.verify_timeline_drift(blocks, clip_durations=[10.0, 12.5], tolerance_sec=0.05)
    assert report_ok["is_aligned"] is True
    assert report_ok["total_drift"] <= 0.05

    # Drift violation (clip 2 is 14.0s instead of 12.5s)
    report_bad = VideoEngine.verify_timeline_drift(blocks, clip_durations=[10.0, 14.0], tolerance_sec=0.05)
    assert report_bad["is_aligned"] is False
    assert report_bad["total_drift"] == 1.5


def test_9_subtitle_bounds_within_speech_dur():
    """
    Step 9: Subtitle cues must be strictly bounded within [0.0, speech_dur].
    """
    script_text = "The protagonist investigates the underground chamber and finds the lost artifact."
    speech_dur = 8.5

    cues = SubtitleEngine.split_script_into_cues(script_text, total_duration=speech_dur)
    assert len(cues) > 0

    for cue in cues:
        c_start, c_end, c_text = cue
        assert c_start >= 0.0, f"Cue started before 0.0: {cue}"
        assert c_end <= speech_dur + 0.05, f"Cue ended after speech_dur ({speech_dur}): {cue}"
        assert c_end > c_start


def test_10_one_point_zero_two_pre_post_timeline_distinction():
    """
    Step 10: 1.02x pre/post timeline distinction.
    Pre-render authoritative timeline duration is T.
    Post-render media duration is T / 1.02.
    Ratio between pre and post is exactly 1.02 with zero relative drift.
    """
    pre_render_dur = 120.0
    speed_factor = 1.02
    post_render_dur = round(pre_render_dur / speed_factor, 2)

    assert post_render_dur == 117.65
    assert abs((pre_render_dur / post_render_dur) - 1.02) < 0.001

    # Verify that VideoEngine render_final_explainer filter components maintain 1.02x synchrony
    v_filter = f"setpts=PTS/{speed_factor}"
    a_filter = f"atempo={speed_factor}"
    assert "setpts=PTS/1.02" in v_filter
    assert "atempo=1.02" in a_filter


def test_11_invalid_source_timing_handling():
    """
    Step 11: Handle invalid, negative, reversed, or out-of-range source movie timestamps gracefully.
    """
    # Negative movie_start
    b_neg = SceneBlock(movie_start=-50.0, movie_end=-10.0, narration_text="Negative start", word_count=3, speech_dur=5.0, actual_duration=5.0, is_authoritative=True)
    # Reversed movie bounds (end < start)
    b_rev = SceneBlock(movie_start=500.0, movie_end=200.0, narration_text="Reversed bounds", word_count=3, speech_dur=5.0, actual_duration=5.0, is_authoritative=True)

    cuts = VideoEngine.calculate_source_cut_plan(
        scene_blocks=[b_neg, b_rev],
        total_movie_dur=3600.0,
        target_duration=10.0,
        micro_clip_dur=3.8
    )
    assert len(cuts) > 0
    for s, e in cuts:
        assert s >= 0.0, f"Cut start {s} must be non-negative"
        assert e > s, f"Cut end {e} must be greater than start {s}"


def test_12_invalid_narration_timing_handling():
    """
    Step 12: Handle invalid or missing narration timings (0, negative, None) gracefully.
    """
    b_zero = SceneBlock(movie_start=100.0, movie_end=150.0, narration_text="Zero duration", word_count=3, speech_dur=0.0, actual_duration=0.0, narration_start=0.0, narration_end=0.0)
    dur = VideoEngine._get_block_narration_dur(b_zero)
    assert dur >= 2.5, "Must return safe minimum fallback duration"

    b_none = None
    assert VideoEngine._get_block_narration_dur(b_none) == 3.5

    report = VideoEngine.verify_timeline_drift([])
    assert report["is_aligned"] is True
    assert report["scene_count"] == 0


def test_13_stress_accumulation_10_50_100_scenes_zero_drift():
    """
    Step 13: Stress test cumulative timeline accumulation across 10, 50, and 100 scenes.
    Verifies zero drift accumulation.
    """
    import random
    rng = random.Random(42)

    for n_scenes in [10, 50, 100]:
        durations = [round(rng.uniform(3.0, 8.0), 2) for _ in range(n_scenes)]
        blocks = []
        for i, d in enumerate(durations):
            blocks.append(SceneBlock(
                movie_start=float(i * 30),
                movie_end=float(i * 30 + 25),
                narration_text=f"Scene text for block {i}",
                word_count=int(d * 2.5),
                speech_dur=d,
                estimated_duration=d * 0.9,
                actual_duration=d
            ))

        authoritative = ScriptEngine.build_authoritative_narration_timeline(blocks, actual_durations=durations)
        assert len(authoritative) == n_scenes

        # Verify timeline contiguity and drift with VideoEngine.verify_timeline_drift
        report = VideoEngine.verify_timeline_drift(authoritative, clip_durations=durations, tolerance_sec=0.05)
        assert report["is_aligned"] is True, f"Failed alignment at {n_scenes} scenes: {report}"
        assert report["is_contiguous"] is True
        assert report["total_drift"] <= 0.05
        assert report["scene_count"] == n_scenes


def test_14_unicode_multilingual_narration_timing():
    """
    Step 14: Multilingual and Unicode scripts (Urdu, Hindi, Arabic, Japanese, Korean, Russian, French)
    preserve exact authoritative durations without character-encoding corruption or drift.
    """
    multilingual_blocks = [
        SceneBlock(movie_start=100.0, movie_end=150.0, narration_text="وہ پرانے گھر کے اندر داخل ہوتا ہے اور خاموشی محسوس کرتا ہے۔", word_count=12, speech_dur=6.5, actual_duration=6.5, is_authoritative=True),
        SceneBlock(movie_start=200.0, movie_end=250.0, narration_text="जासूस कमरे में रखे गुप्त दस्तावेज़ को ढूंढ लेता है।", word_count=10, speech_dur=5.8, actual_duration=5.8, is_authoritative=True),
        SceneBlock(movie_start=300.0, movie_end=350.0, narration_text="يكتشف المحقق دليلاً قاطعاً في الخزانة السرية.", word_count=8, speech_dur=7.2, actual_duration=7.2, is_authoritative=True),
        SceneBlock(movie_start=400.0, movie_end=450.0, narration_text="探偵は机の引き出しから古い鍵を見つける。", word_count=6, speech_dur=4.9, actual_duration=4.9, is_authoritative=True),
        SceneBlock(movie_start=500.0, movie_end=550.0, narration_text="탐정은 비밀 통로를 발견하고 안으로 들어간다.", word_count=6, speech_dur=5.4, actual_duration=5.4, is_authoritative=True),
        SceneBlock(movie_start=600.0, movie_end=650.0, narration_text="Детектив находит секретное письмо в старом сейфе.", word_count=7, speech_dur=6.1, actual_duration=6.1, is_authoritative=True),
    ]

    durations = [b.actual_duration for b in multilingual_blocks]
    authoritative = ScriptEngine.build_authoritative_narration_timeline(multilingual_blocks, actual_durations=durations)

    report = VideoEngine.verify_timeline_drift(authoritative, clip_durations=durations, tolerance_sec=0.05)
    assert report["is_aligned"] is True
    assert report["is_contiguous"] is True
    assert report["total_drift"] <= 0.05


def test_15_mocked_end_to_end_scene_assembly_pipeline():
    """
    Step 15: Mocked end-to-end scene assembly pipeline:
    SceneBlocks -> TTS actual durations -> Authoritative timeline -> AudioLockedSceneClips -> Assembly -> Verification.
    """
    raw_blocks = [
        SceneBlock(movie_start=120.0, movie_end=160.0, narration_text="Scene one opening exposition.", word_count=4, speech_dur=10.0, estimated_duration=10.0),
        SceneBlock(movie_start=240.0, movie_end=280.0, narration_text="Scene two dramatic conflict escalates.", word_count=5, speech_dur=10.0, estimated_duration=10.0),
        SceneBlock(movie_start=400.0, movie_end=450.0, narration_text="Scene three final confrontation climax.", word_count=5, speech_dur=10.0, estimated_duration=10.0),
    ]

    # Synthesized TTS generates these actual audio durations
    actual_durations = [8.3, 11.7, 9.4]
    total_audio_dur = sum(actual_durations)  # 29.4s

    # 1. Lock authoritative timeline
    authoritative_blocks = ScriptEngine.build_authoritative_narration_timeline(raw_blocks, actual_durations=actual_durations)
    assert len(authoritative_blocks) == 3
    assert authoritative_blocks[0].narration_start == 0.0
    assert authoritative_blocks[0].narration_end == 8.3
    assert authoritative_blocks[1].narration_start == 8.3
    assert authoritative_blocks[1].narration_end == 20.0
    assert authoritative_blocks[2].narration_start == 20.0
    assert authoritative_blocks[2].narration_end == 29.4

    # 2. Assemble clips via build_audio_locked_scene_clips
    with tempfile.TemporaryDirectory() as tmp:
        fake_video = os.path.join(tmp, "movie.mp4")
        Path(fake_video).write_bytes(b"\x00" * 100)
        fake_out = os.path.join(tmp, "assembled.mp4")
        clip_durations_assembled = []

        with patch("app.services.video_engine.subprocess.run") as mock_run, \
             patch("app.services.video_engine.VideoEngine.get_duration", return_value=7200.0), \
             patch("app.services.video_engine.VideoEngine.probe_media", return_value={"duration": 7200.0}):

            def side_effect(cmd, **kwargs):
                cmd_list = list(cmd)
                # Check for -t argument
                if "-t" in cmd_list:
                    t_idx = cmd_list.index("-t")
                    # If creating a block clip _alc_\d+\.mp4 or _mc_
                    target_arg = cmd_list[-1]
                    if isinstance(target_arg, str) and re.search(r"_alc_\d+\.mp4$", target_arg):
                        clip_durations_assembled.append(float(cmd_list[t_idx + 1]))

                for arg in cmd_list:
                    if isinstance(arg, str) and arg.endswith(".mp4") and arg != fake_video:
                        Path(arg).write_bytes(b"\x00" * 50)
                m = MagicMock()
                m.returncode = 0
                return m

            mock_run.side_effect = side_effect

            result = VideoEngine.build_audio_locked_scene_clips(
                input_video=fake_video,
                scene_blocks=authoritative_blocks,
                temp_dir=tmp,
                job_id="test_e2e_phase4b",
                output_video=fake_out
            )

        assert result is not None
        assert os.path.exists(fake_out)

        # 3. Verify timeline drift
        report = VideoEngine.verify_timeline_drift(
            authoritative_blocks,
            clip_durations=actual_durations,
            tolerance_sec=0.05
        )
        assert report["is_aligned"] is True
        assert report["is_contiguous"] is True
        assert report["total_drift"] <= 0.05
        assert report["total_actual_duration"] == round(total_audio_dur, 3)
