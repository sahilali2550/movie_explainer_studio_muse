import os
import json
import math
import pytest
from unittest.mock import patch, MagicMock
from app.services.script_engine import ScriptEngine, SceneBlock, EvidencePacket, StoryPlanItem
from app.services.voice_engine import VoiceEngine


# ===========================================================================
# PHASE 4A TEST SUITE: ACTUAL TTS DURATION + NARRATION TIMELINE AUTHORITY
# ===========================================================================

def test_1_actual_duration_overrides_estimate():
    """Step 14 & 15: Actual audio duration becomes final authority over pre-TTS estimate."""
    block = SceneBlock(
        movie_start=100.0,
        movie_end=130.0,
        narration_text="The detective discovers a hidden letter in the desk drawer.",
        word_count=10,
        speech_dur=10.0,
        estimated_duration=10.0
    )
    # TTS generates 12.4s of audio
    result = ScriptEngine.build_authoritative_narration_timeline([block], actual_durations=[12.4])

    assert len(result) == 1
    b = result[0]
    assert b.estimated_duration == 10.0, "Pre-TTS estimate must be preserved"
    assert b.actual_duration == 12.4, "Actual duration must match synthesized audio"
    assert b.speech_dur == 12.4, "speech_dur must reflect authoritative actual duration"
    assert b.narration_start == 0.0
    assert b.narration_end == 12.4
    assert b.is_authoritative is True
    # Source anchors must remain completely untouched
    assert b.movie_start == 100.0
    assert b.movie_end == 130.0


def test_2_shorter_actual_duration():
    """Step 15: Actual duration is shorter than planned (planned 12.0s -> actual 8.7s)."""
    block = SceneBlock(
        movie_start=200.0,
        movie_end=240.0,
        narration_text="He runs toward the exit before the gates close completely.",
        word_count=10,
        speech_dur=12.0,
        estimated_duration=12.0
    )
    result = ScriptEngine.build_authoritative_narration_timeline([block], actual_durations=[8.7])
    b = result[0]
    assert b.estimated_duration == 12.0
    assert b.actual_duration == 8.7
    assert b.speech_dur == 8.7
    assert b.narration_start == 0.0
    assert b.narration_end == 8.7
    assert b.is_authoritative is True


def test_3_longer_actual_duration():
    """Step 15: Actual duration is longer than planned (planned 10.0s -> actual 12.4s)."""
    block = SceneBlock(
        movie_start=300.0,
        movie_end=330.0,
        narration_text="An unexpected explosion rocks the entire underground facility.",
        word_count=8,
        speech_dur=10.0,
        estimated_duration=10.0
    )
    result = ScriptEngine.build_authoritative_narration_timeline([block], actual_durations=[12.4])
    b = result[0]
    assert b.estimated_duration == 10.0
    assert b.actual_duration == 12.4
    assert b.speech_dur == 12.4
    assert b.narration_start == 0.0
    assert b.narration_end == 12.4
    assert b.is_authoritative is True


def test_4_sequential_scene_accumulation():
    """
    Step 7 & 15: Sequential blocks must accumulate monotonically without gaps or overlaps.
    Planned: [10, 10, 10] -> Actual: [12.4, 8.7, 11.2]
    Expected: Block 1 [0.0, 12.4], Block 2 [12.4, 21.1], Block 3 [21.1, 32.3].
    """
    blocks = [
        SceneBlock(movie_start=50.0, movie_end=80.0, narration_text="Block one text.", word_count=3, speech_dur=10.0, estimated_duration=10.0),
        SceneBlock(movie_start=120.0, movie_end=150.0, narration_text="Block two text.", word_count=3, speech_dur=10.0, estimated_duration=10.0),
        SceneBlock(movie_start=200.0, movie_end=230.0, narration_text="Block three text.", word_count=3, speech_dur=10.0, estimated_duration=10.0),
    ]
    actual_durations = [12.4, 8.7, 11.2]

    result = ScriptEngine.build_authoritative_narration_timeline(blocks, actual_durations=actual_durations)

    assert len(result) == 3
    assert result[0].narration_start == 0.0
    assert result[0].narration_end == 12.4
    assert result[0].actual_duration == 12.4

    assert result[1].narration_start == 12.4
    assert result[1].narration_end == 21.1
    assert result[1].actual_duration == 8.7

    assert result[2].narration_start == 21.1
    assert result[2].narration_end == 32.3
    assert result[2].actual_duration == 11.2

    # Verify zero-gap invariant across all boundaries
    for i in range(len(result) - 1):
        assert result[i].narration_end == result[i + 1].narration_start


def test_5_total_duration_sum_invariant():
    """Step 17: Sum of actual durations must strictly equal final_narration_end - final_narration_start."""
    durations = [5.125, 8.430, 12.600, 4.312, 19.880, 7.550]
    blocks = [
        SceneBlock(movie_start=i * 100.0, movie_end=i * 100.0 + 30.0, narration_text=f"Scene text {i}", word_count=5)
        for i in range(len(durations))
    ]

    result = ScriptEngine.build_authoritative_narration_timeline(blocks, actual_durations=durations)

    sum_actual = sum(b.actual_duration for b in result)
    timeline_span = result[-1].narration_end - result[0].narration_start

    assert abs(sum_actual - timeline_span) < 1e-4, f"Sum ({sum_actual}) != Span ({timeline_span})"
    assert result[0].narration_start == 0.0
    assert abs(result[-1].narration_end - sum(durations)) < 1e-3


def test_6_timestamp_precision_millisecond():
    """Step 16: Timestamps must maintain 3-decimal (millisecond) precision without loss or drift."""
    durations = [3.142, 7.891, 14.250]
    blocks = [
        SceneBlock(movie_start=0.0, movie_end=10.0, narration_text="Block A", word_count=2),
        SceneBlock(movie_start=10.0, movie_end=20.0, narration_text="Block B", word_count=2),
        SceneBlock(movie_start=20.0, movie_end=30.0, narration_text="Block C", word_count=2),
    ]
    result = ScriptEngine.build_authoritative_narration_timeline(blocks, actual_durations=durations)

    assert result[0].narration_start == 0.000
    assert result[0].narration_end == 3.142
    assert result[1].narration_start == 3.142
    assert result[1].narration_end == 11.033
    assert result[2].narration_start == 11.033
    assert result[2].narration_end == 25.283


def test_7_cumulative_rounding_no_drift():
    """Step 16 & 17: 100 sequential blocks with fractional millisecond durations must not accumulate drift."""
    n_blocks = 100
    dur = 3.333  # periodic fraction representation
    durations = [dur] * n_blocks
    blocks = [
        SceneBlock(movie_start=i * 10.0, movie_end=i * 10.0 + 5.0, narration_text=f"Block {i}", word_count=2)
        for i in range(n_blocks)
    ]

    result = ScriptEngine.build_authoritative_narration_timeline(blocks, actual_durations=durations)

    expected_total = round(dur * n_blocks, 3)
    actual_total = round(result[-1].narration_end, 3)

    assert abs(actual_total - expected_total) < 1e-3
    assert abs(result[-1].narration_end - sum(b.actual_duration for b in result)) < 1e-3

    # Check contiguous boundary invariant across all 100 blocks
    for i in range(n_blocks - 1):
        assert result[i].narration_end == result[i + 1].narration_start


def test_8_missing_audio_handling(tmp_path):
    """Step 11: Missing audio files must raise RuntimeError and never fake believable durations."""
    non_existent_file = str(tmp_path / "does_not_exist_voiceover.mp3")

    with pytest.raises(RuntimeError, match="Unable to determine audio duration"):
        VoiceEngine.get_audio_duration(non_existent_file)

    block = SceneBlock(movie_start=0.0, movie_end=10.0, narration_text="Missing audio test", word_count=3)
    with pytest.raises(RuntimeError):
        ScriptEngine.build_authoritative_narration_timeline([block], actual_durations=[non_existent_file])


def test_9_zero_duration_audio_handling(tmp_path, monkeypatch):
    """Step 11: Zero-duration audio must be rejected with ValueError or RuntimeError."""
    block = SceneBlock(movie_start=0.0, movie_end=10.0, narration_text="Zero duration block", word_count=3)

    with pytest.raises(ValueError, match="Invalid duration"):
        ScriptEngine.build_authoritative_narration_timeline([block], actual_durations=[0.0])

    with pytest.raises(ValueError, match="Invalid actual audio duration"):
        ScriptEngine.build_authoritative_narration_timeline([block], actual_durations=0.0)

    # VoiceEngine ffprobe returning 0
    fake_audio = tmp_path / "zero.mp3"
    fake_audio.write_bytes(b"silence")

    class MockProcessZero:
        returncode = 0
        stdout = "0.000000\n"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: MockProcessZero())
    with pytest.raises(RuntimeError, match="Unable to determine audio duration"):
        VoiceEngine.get_audio_duration(str(fake_audio))


def test_10_invalid_duration_handling(tmp_path, monkeypatch):
    """Step 11: Negative, NaN, Inf, and None durations must be rejected firmly."""
    block = SceneBlock(movie_start=0.0, movie_end=10.0, narration_text="Invalid block", word_count=2)

    # None
    with pytest.raises(ValueError, match="cannot be None"):
        ScriptEngine.build_authoritative_narration_timeline([block], actual_durations=None)

    # Negative
    with pytest.raises(ValueError, match="Invalid duration"):
        ScriptEngine.build_authoritative_narration_timeline([block], actual_durations=[-4.5])

    # NaN
    with pytest.raises(ValueError, match="Invalid duration"):
        ScriptEngine.build_authoritative_narration_timeline([block], actual_durations=[float("nan")])

    # Infinity
    with pytest.raises(ValueError, match="Invalid duration"):
        ScriptEngine.build_authoritative_narration_timeline([block], actual_durations=[float("inf")])

    # Length mismatch
    with pytest.raises(ValueError, match="Block count"):
        ScriptEngine.build_authoritative_narration_timeline([block], actual_durations=[5.0, 10.0])


def test_11_source_timestamp_preservation():
    """
    Step 18: Deterministic fixture verifying source timestamps remain unchanged
    while narration output timings accumulate separately.
    """
    source_starts = [120.0, 540.5, 1220.25, 1888.8]
    source_ends = [150.0, 570.5, 1250.25, 1920.8]
    actual_durations = [7.3, 12.8, 9.2, 14.6]

    blocks = [
        SceneBlock(
            movie_start=source_starts[i],
            movie_end=source_ends[i],
            narration_text=f"Narration beat {i+1}",
            word_count=4,
            speech_dur=10.0,
            estimated_duration=10.0
        )
        for i in range(4)
    ]

    result = ScriptEngine.build_authoritative_narration_timeline(blocks, actual_durations=actual_durations)

    assert len(result) == 4

    # 1. Source timestamps remain unchanged
    for i in range(4):
        assert result[i].movie_start == source_starts[i], f"movie_start {i} modified!"
        assert result[i].movie_end == source_ends[i], f"movie_end {i} modified!"

    # 2. Narration output timings are separate and sequential
    expected_starts = [0.0, 7.3, 20.1, 29.3]
    expected_ends = [7.3, 20.1, 29.3, 43.9]
    for i in range(4):
        assert abs(result[i].narration_start - expected_starts[i]) < 1e-3
        assert abs(result[i].narration_end - expected_ends[i]) < 1e-3
        assert abs(result[i].actual_duration - actual_durations[i]) < 1e-3

    # 3. Source order remains strictly chronological
    for i in range(3):
        assert result[i].movie_start < result[i + 1].movie_start


def test_12_source_time_vs_output_time_coordinate_separation():
    """Step 8: Proves movie_start (e.g. 1852.4s) and narration_start (e.g. 92.35s) are independent."""
    block = SceneBlock(
        movie_start=1852.4,
        movie_end=1890.0,
        narration_text="The climax confrontation at the edge of the cliff.",
        word_count=9,
        speech_dur=15.0,
        estimated_duration=15.0
    )
    blocks = [
        SceneBlock(movie_start=100.0, movie_end=130.0, narration_text="Scene 1", word_count=2, speech_dur=92.35),
        block
    ]
    # Set actual durations
    result = ScriptEngine.build_authoritative_narration_timeline(blocks, actual_durations=[92.35, 14.2])

    assert result[1].movie_start == 1852.4, "Source movie coordinate must remain in source film domain"
    assert result[1].narration_start == 92.35, "Narration start must reflect explainer audio timeline"
    assert result[1].narration_end == 106.55
    assert result[1].actual_duration == 14.2


def test_13_multiple_output_durations_matrix():
    """Step 14: Verifies authority across standard output targets: 3m, 5m, 8m, 12m, 15m, 20m, 30m."""
    duration_targets_min = [3, 5, 8, 12, 15, 20, 30]

    for mins in duration_targets_min:
        target_sec = mins * 60.0
        n_scenes = mins * 4  # approx 4 scenes per minute
        blocks = [
            SceneBlock(
                movie_start=i * 60.0,
                movie_end=i * 60.0 + 30.0,
                narration_text=f"Scene {i} narration detailing plot progression.",
                word_count=8
            )
            for i in range(n_scenes)
        ]

        # 1. Pre-TTS planning estimate
        ScriptEngine.estimate_block_durations(blocks, target_output_duration_sec=target_sec)
        assert all(b.estimated_duration > 0.0 for b in blocks)
        assert all(b.is_authoritative is False for b in blocks)

        # 2. Simulated actual TTS synthesis (slight variation from estimate, e.g. +3% or -2%)
        actual_total = target_sec * 1.03  # simulated 3% slower narrator
        result = ScriptEngine.build_authoritative_narration_timeline(blocks, actual_durations=actual_total)

        assert all(b.is_authoritative is True for b in result)
        assert abs(result[-1].narration_end - actual_total) < 1e-2
        assert abs(sum(b.actual_duration for b in result) - actual_total) < 1e-2


def test_14_multilingual_unicode_narration_blocks():
    """Step 14 & 21: Unicode narration (Urdu, Hindi, Arabic, Chinese) does not corrupt timing."""
    blocks = [
        SceneBlock(
            movie_start=50.0,
            movie_end=80.0,
            narration_text="داؤد کی پارٹی میں شاندار انٹری ہوتی ہے اور سب حیران رہ جاتے ہیں۔",
            word_count=12,
            speech_dur=6.0
        ),
        SceneBlock(
            movie_start=150.0,
            movie_end=180.0,
            narration_text="नायक ने विलेन का पीछा करना शुरू कर दिया और रहस्य गहरा गया।",
            word_count=11,
            speech_dur=5.5
        ),
        SceneBlock(
            movie_start=250.0,
            movie_end=280.0,
            narration_text="تبدأ المطاردة المثيرة في شوارع المدينة المظلمة بكل حماس.",
            word_count=9,
            speech_dur=5.0
        ),
        SceneBlock(
            movie_start=350.0,
            movie_end=380.0,
            narration_text="主角发现了隐藏在背后的巨大阴谋，决定孤身犯险。",
            word_count=8,
            speech_dur=4.5
        ),
    ]
    actual_durations = [6.825, 5.910, 5.120, 4.880]

    result = ScriptEngine.build_authoritative_narration_timeline(blocks, actual_durations=actual_durations)

    assert len(result) == 4
    assert result[0].actual_duration == 6.825
    assert result[0].narration_start == 0.0
    assert result[0].narration_end == 6.825

    assert result[1].actual_duration == 5.910
    assert result[1].narration_start == 6.825
    assert result[1].narration_end == 12.735

    assert result[2].actual_duration == 5.120
    assert result[2].narration_start == 12.735
    assert result[2].narration_end == 17.855

    assert result[3].actual_duration == 4.880
    assert result[3].narration_start == 17.855
    assert result[3].narration_end == 22.735

    assert result[-1].narration_end == 22.735


def test_15_phase3b_plan_and_evidence_traceability_preservation():
    """Step 19: Preserves Phase 3B EvidencePacket and StoryPlanItem traceability on SceneBlock."""
    packet = EvidencePacket(
        packet_id="EP-042",
        movie_start=450.0,
        movie_end=480.0,
        source_text="I will never forgive what happened in the warehouse.",
        act="Act 2B",
        sequence_index=41
    )
    plan_item = StoryPlanItem(
        step=42,
        source_timestamp=450.0,
        act="Act 2B",
        evidence_ref="EP-042",
        core_event="Protagonist confronts past trauma",
        entities=["Protagonist", "Warehouse"],
        narration_purpose="escalation",
        budget_words=25
    )

    block = SceneBlock(
        movie_start=packet.movie_start,
        movie_end=packet.movie_end,
        narration_text="Facing his painful past, he vows revenge.",
        word_count=7,
        speech_dur=5.0,
        estimated_duration=5.0,
        evidence_ref=plan_item.evidence_ref,
        story_step=plan_item.step
    )

    result = ScriptEngine.build_authoritative_narration_timeline([block], actual_durations=[6.25])

    b = result[0]
    assert b.evidence_ref == "EP-042", "Evidence packet link must be preserved"
    assert b.story_step == 42, "Story plan step must be preserved"
    assert b.movie_start == 450.0, "Source timestamp must be preserved"
    assert b.actual_duration == 6.25
    assert b.is_authoritative is True

    # Check to_dict() serialization preserves Phase 3B and Phase 4A fields
    d = b.to_dict()
    assert d["evidence_ref"] == "EP-042"
    assert d["story_step"] == 42
    assert d["movie_start"] == 450.0
    assert d["actual_duration"] == 6.25
    assert d["estimated_duration"] == 5.0
    assert d["is_authoritative"] is True


def test_16_duration_mismatch_observability():
    """Step 10: Validates detect_duration_mismatch() calculations for absolute and relative deltas."""
    blocks = [
        SceneBlock(movie_start=0.0, movie_end=10.0, narration_text="B1", word_count=5, estimated_duration=10.0),
        SceneBlock(movie_start=10.0, movie_end=20.0, narration_text="B2", word_count=5, estimated_duration=10.0),
    ]
    # Apply actual durations: Block 1 is +2.4s, Block 2 is -1.3s
    ScriptEngine.build_authoritative_narration_timeline(blocks, actual_durations=[12.4, 8.7])

    mismatch = ScriptEngine.detect_duration_mismatch(blocks)

    assert mismatch["total_estimated_sec"] == 20.0
    assert mismatch["total_actual_sec"] == 21.1
    assert mismatch["absolute_delta"] == 1.1
    assert mismatch["relative_delta"] == round(1.1 / 20.0, 4)
    assert mismatch["max_block_delta"] == 2.4
    assert mismatch["is_authoritative"] is True

    assert len(mismatch["block_mismatches"]) == 2
    assert mismatch["block_mismatches"][0]["absolute_delta"] == 2.4
    assert mismatch["block_mismatches"][1]["absolute_delta"] == -1.3


def test_17_voice_engine_probe_block_audio_durations(tmp_path, monkeypatch):
    """Step 4 & 11: Validates probe_block_audio_durations across multiple files with mocking."""
    f1 = tmp_path / "audio_1.mp3"
    f2 = tmp_path / "audio_2.mp3"
    f1.write_bytes(b"audio1")
    f2.write_bytes(b"audio2")

    mock_durations = {str(f1): 4.5, str(f2): 9.25}

    def mock_get_dur(path):
        if path in mock_durations:
            return mock_durations[path]
        raise RuntimeError(f"Unknown file {path}")

    monkeypatch.setattr(VoiceEngine, "get_audio_duration", mock_get_dur)

    durations = VoiceEngine.probe_block_audio_durations([str(f1), str(f2)])
    assert durations == [4.5, 9.25]

    # Test passing audio paths directly into build_authoritative_narration_timeline
    blocks = [
        SceneBlock(movie_start=0.0, movie_end=10.0, narration_text="Scene 1", word_count=2),
        SceneBlock(movie_start=10.0, movie_end=20.0, narration_text="Scene 2", word_count=2)
    ]
    timed = ScriptEngine.build_authoritative_narration_timeline(blocks, actual_durations=[str(f1), str(f2)])
    assert timed[0].actual_duration == 4.5
    assert timed[0].narration_start == 0.0
    assert timed[0].narration_end == 4.5
    assert timed[1].actual_duration == 9.25
    assert timed[1].narration_start == 4.5
    assert timed[1].narration_end == 13.75
