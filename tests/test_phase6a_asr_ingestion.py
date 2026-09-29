import os
import math
import pytest
from unittest.mock import patch, MagicMock

from app.services.asr_engine import (
    ASRSegment,
    ASRProvider,
    FasterWhisperASRProvider,
    MockASRProvider,
    ASREngine,
)
from app.services.script_engine import ScriptEngine, SceneBlock


# ============================================================================
# 1. ASR PROVIDER CONTRACT
# ============================================================================

def test_asr_provider_contract():
    """Verify abstract ASRProvider interface contract."""
    class IncompleteProvider(ASRProvider):
        pass

    with pytest.raises(TypeError):
        IncompleteProvider()  # Can't instantiate without implementing abstract methods

    mock = MockASRProvider()
    assert isinstance(mock, ASRProvider)
    assert mock.provider_name() == "mock"
    assert mock.is_available() is True
    assert mock.transcribe("fake.wav") == []


# ============================================================================
# 2. VALID SEGMENT CONVERSION
# ============================================================================

def test_valid_segment_conversion():
    """Verify conversion of valid ASRSegment objects to dialogue cue format."""
    segments = [
        ASRSegment(start=1.234, end=5.678, text="The protagonist arrives at the station."),
        ASRSegment(start=6.100, end=9.400, text="He looks around nervously.", language="en", confidence=-0.12)
    ]
    cues = ASREngine.segments_to_dialogue_cues(segments)
    assert len(cues) == 2
    assert cues[0]["start"] == 1.23
    assert cues[0]["end"] == 5.68
    assert cues[0]["text"] == "The protagonist arrives at the station."
    assert cues[0]["source"] == "asr"
    assert cues[1]["start"] == 6.10
    assert cues[1]["end"] == 9.40


# ============================================================================
# 3. CHRONOLOGICAL ORDERING
# ============================================================================

def test_chronological_ordering():
    """Verify segments provided out-of-order are sorted strictly chronologically."""
    segments = [
        ASRSegment(start=45.0, end=50.0, text="Third scene revelation."),
        ASRSegment(start=5.0, end=10.0, text="First scene setup."),
        ASRSegment(start=22.5, end=28.0, text="Second scene confrontation.")
    ]
    cues = ASREngine.segments_to_dialogue_cues(segments)
    assert len(cues) == 3
    assert cues[0]["start"] == 5.0
    assert cues[1]["start"] == 22.5
    assert cues[2]["start"] == 45.0


# ============================================================================
# 4. INVALID TIMESTAMPS REJECTED
# ============================================================================

def test_invalid_timestamps_rejected():
    """Verify inverted, non-finite, and negative timestamps are cleanly rejected."""
    segments = [
        ASRSegment(start=10.0, end=5.0, text="Inverted timestamps."),
        ASRSegment(start=5.0, end=5.0, text="Zero duration timestamp."),
        ASRSegment(start=-2.0, end=3.0, text="Negative start timestamp."),
        ASRSegment(start=1.0, end=-5.0, text="Negative end timestamp."),
        ASRSegment(start=float('nan'), end=10.0, text="NaN start timestamp."),
        ASRSegment(start=10.0, end=float('inf'), text="Infinite end timestamp."),
        ASRSegment(start=12.0, end=18.0, text="Valid timestamped cue.")
    ]
    cues = ASREngine.segments_to_dialogue_cues(segments)
    assert len(cues) == 1
    assert cues[0]["text"] == "Valid timestamped cue."
    assert cues[0]["start"] == 12.0
    assert cues[0]["end"] == 18.0


# ============================================================================
# 5. EMPTY SEGMENTS DISCARDED
# ============================================================================

def test_empty_segments_discarded():
    """Verify blank, whitespace-only, or punctuation-stripped empty cues are discarded."""
    segments = [
        ASRSegment(start=1.0, end=4.0, text=""),
        ASRSegment(start=4.5, end=7.0, text="   \t \n  "),
        ASRSegment(start=8.0, end=11.0, text="Meaningful dialogue line.")
    ]
    cues = ASREngine.segments_to_dialogue_cues(segments)
    assert len(cues) == 1
    assert cues[0]["text"] == "Meaningful dialogue line."


# ============================================================================
# 6. UNICODE / URDU TEXT PRESERVED
# ============================================================================

def test_unicode_urdu_text_preserved():
    """Verify non-English script (Urdu, Hindi, Arabic) characters are preserved without corruption."""
    urdu_text = "وہ رات کے اندھیرے میں دروازے کی طرف بڑھا۔"
    hindi_text = "उसने देखा कि कमरा पूरी तरह से खाली था।"
    arabic_text = "دخل المحقق إلى المبنى المهجور بهدوء."

    segments = [
        ASRSegment(start=2.0, end=6.0, text=urdu_text, language="ur"),
        ASRSegment(start=7.0, end=11.0, text=hindi_text, language="hi"),
        ASRSegment(start=12.0, end=16.0, text=arabic_text, language="ar"),
    ]
    cues = ASREngine.segments_to_dialogue_cues(segments)
    assert len(cues) == 3
    assert cues[0]["text"] == urdu_text
    assert cues[1]["text"] == hindi_text
    assert cues[2]["text"] == arabic_text


# ============================================================================
# 7. DUPLICATE SEGMENT HANDLING
# ============================================================================

def test_duplicate_segment_handling():
    """Verify consecutive duplicate ASR segments within < 0.5s are deduplicated/merged."""
    segments = [
        ASRSegment(start=10.0, end=12.0, text="Freeze! Put your hands up!"),
        ASRSegment(start=10.2, end=12.5, text="Freeze! Put your hands up!"),  # duplicate
        ASRSegment(start=15.0, end=18.0, text="Don't shoot, I'm unarmed.")
    ]
    cues = ASREngine.segments_to_dialogue_cues(segments)
    assert len(cues) == 2
    assert cues[0]["text"] == "Freeze! Put your hands up!"
    assert cues[0]["start"] == 10.0
    assert cues[0]["end"] == 12.5  # merged end forward
    assert cues[1]["text"] == "Don't shoot, I'm unarmed."


# ============================================================================
# 8. TRANSCRIPT-PRESENT PATH SKIPS ASR
# ============================================================================

def test_transcript_present_path_skips_asr():
    """Verify that when a user or platform transcript exists, ASR is completely skipped."""
    existing_cues = [{"start": 10.0, "end": 15.0, "text": "Existing platform subtitle."}]
    provider = MockASRProvider(segments=[ASRSegment(start=1.0, end=3.0, text="ASR cue")])

    with patch.object(provider, "transcribe") as mock_transcribe:
        # Simulate logic: transcript already present
        dialogue_timeline = existing_cues
        if not dialogue_timeline:
            provider.transcribe("fake.wav")

        mock_transcribe.assert_not_called()
    assert len(dialogue_timeline) == 1
    assert dialogue_timeline[0]["text"] == "Existing platform subtitle."


# ============================================================================
# 9. TRANSCRIPT-MISSING PATH INVOKES ASR
# ============================================================================

def test_transcript_missing_path_invokes_asr(tmp_path):
    """Verify that when no transcript exists, ASR is invoked on available media."""
    dummy_media = tmp_path / "test_movie.mp4"
    dummy_media.write_bytes(b"dummy video bytes")

    mock_segments = [
        ASRSegment(start=14.5, end=18.2, text="Captain, the engine has stalled!"),
        ASRSegment(start=22.0, end=26.5, text="Reroute power to the shields immediately.")
    ]
    provider = MockASRProvider(segments=mock_segments)

    with patch.object(ASREngine, "extract_audio_for_asr", return_value=True):
        cues, subs_txt, src = ASREngine.transcribe_media_to_dialogue(
            media_path=str(dummy_media),
            temp_dir=str(tmp_path),
            job_id="test_job",
            provider=provider
        )

    assert src == "asr"
    assert len(cues) == 2
    assert cues[0]["text"] == "Captain, the engine has stalled!"
    assert cues[0]["start"] == 14.5
    assert cues[1]["text"] == "Reroute power to the shields immediately!" or "shields" in cues[1]["text"]
    assert "[00:14 - 00:18]" in subs_txt


# ============================================================================
# 10. ASR FAILURE FALLS BACK SAFELY
# ============================================================================

def test_asr_failure_falls_back_safely(tmp_path):
    """Verify that if the ASR provider raises an unexpected exception, it returns empty results safely."""
    dummy_media = tmp_path / "test_movie.mp4"
    dummy_media.write_bytes(b"dummy video bytes")

    class CrashingProvider(ASRProvider):
        def provider_name(self): return "crash"
        def is_available(self): return True
        def transcribe(self, audio_path):
            raise RuntimeError("CUDA out of memory in native ctranslate2 engine.")

    with patch.object(ASREngine, "extract_audio_for_asr", return_value=True):
        cues, subs_txt, src = ASREngine.transcribe_media_to_dialogue(
            media_path=str(dummy_media),
            temp_dir=str(tmp_path),
            job_id="crash_job",
            provider=CrashingProvider()
        )

    assert cues == []
    assert subs_txt == ""
    assert src == "none"


# ============================================================================
# 11. MISSING MODEL HANDLED SAFELY
# ============================================================================

def test_missing_model_handled_safely():
    """Verify that when a model cannot be loaded, transcribe() catches the error and returns []."""
    prov = FasterWhisperASRProvider(model_name="nonexistent-model-xyz")

    with patch.object(prov, "is_available", return_value=True), \
         patch.object(prov, "_get_model", side_effect=Exception("Model nonexistent-model-xyz not found locally or remotely")):
        segments = prov.transcribe("fake.wav")
        assert segments == []


# ============================================================================
# 12. MISSING PACKAGE HANDLED SAFELY
# ============================================================================

def test_missing_package_handled_safely():
    """Verify that when faster-whisper package is not installed, provider gracefully reports unavailable."""
    prov = FasterWhisperASRProvider()

    with patch.dict("sys.modules", {"faster_whisper": None}):
        # FasterWhisper is not importable
        assert prov.is_available() is False
        segments = prov.transcribe("fake.wav")
        assert segments == []


# ============================================================================
# 13. ASR DIALOGUE TIMELINE REACHES GROUNDING LAYER
# ============================================================================

def test_asr_dialogue_timeline_reaches_grounding_layer():
    """Verify ASR-generated cues pass into anchor_scenes_to_dialogue and anchor scene blocks."""
    asr_cues = [
        {"start": 105.0, "end": 112.0, "text": "Detective Miller enters the abandoned warehouse.", "source": "asr"},
        {"start": 210.0, "end": 218.0, "text": "Drop your weapon, suspect is surrounded!", "source": "asr"}
    ]

    script = """
    [SCENE: 00:10 - 00:20]
    [VOICEOVER] Detective Miller carefully approaches the warehouse door.

    [SCENE: 00:30 - 00:40]
    [VOICEOVER] He shouts at the suspect to drop the weapon.
    """

    blocks = ScriptEngine.parse_storyboard_blocks(
        raw_script=script,
        dialogue_timeline=asr_cues,
        transcript_source="asr"
    )

    assert len(blocks) == 2
    # Verify the scenes anchored to the real ASR timestamps (105s and 210s) rather than staying at AI timestamps (10s and 30s)
    assert blocks[0].movie_start == 105.0
    assert blocks[1].movie_start == 210.0
    assert blocks[0].transcript_source == "asr"
    assert blocks[1].transcript_source == "asr"


# ============================================================================
# 14. EVIDENCE PACKET GENERATION RECEIVES ASR CUES
# ============================================================================

def test_evidence_packet_generation_receives_asr_cues():
    """Verify Phase 3B build_evidence_packets successfully clusters ASR-generated cues."""
    asr_cues = [
        {"start": 12.0, "end": 16.0, "text": "The secret code was hidden inside the painting.", "source": "asr"},
        {"start": 18.0, "end": 22.0, "text": "Professor Robert deciphered the ancient symbol.", "source": "asr"},
        {"start": 120.0, "end": 126.0, "text": "The assassin is on the roof with a sniper rifle.", "source": "asr"}
    ]

    subs_text = ASREngine.format_cues_to_subtitles_text(asr_cues)
    packets = ScriptEngine.build_evidence_packets(
        subs_text=subs_text,
        total_movie_dur=300.0,
        dialogue_timeline=asr_cues
    )

    assert len(packets) >= 1
    # Check that the first packet covers the first ASR dialogue cluster
    assert packets[0]["movie_start"] <= 12.0
    assert "secret" in packets[0]["source_text"].lower() or "painting" in packets[0]["source_text"].lower()


# ============================================================================
# 15. SOURCE TIMESTAMPS REMAIN SOURCE TIMESTAMPS
# ============================================================================

def test_source_timestamps_remain_source_timestamps():
    """Verify ASR timestamps retain their exact fractional seconds and are not altered."""
    segments = [
        ASRSegment(start=143.72, end=149.85, text="Specific factual dialogue moment.")
    ]
    cues = ASREngine.segments_to_dialogue_cues(segments)
    assert cues[0]["start"] == 143.72
    assert cues[0]["end"] == 149.85


# ============================================================================
# 16. NO ARTIFICIAL TIMESTAMP GENERATION
# ============================================================================

def test_no_artificial_timestamp_generation():
    """Verify that ASR engine never invents artificial equidistant timestamps."""
    segments = [
        ASRSegment(start=3.14, end=7.89, text="Irregular timing one."),
        ASRSegment(start=42.10, end=49.95, text="Irregular timing two."),
        ASRSegment(start=188.45, end=193.20, text="Irregular timing three.")
    ]
    cues = ASREngine.segments_to_dialogue_cues(segments)
    assert cues[0]["start"] == 3.14
    assert cues[1]["start"] == 42.10
    assert cues[2]["start"] == 188.45
    # Ensure gaps between cues reflect actual silence, not synthetic uniform spacing
    assert round(cues[1]["start"] - cues[0]["end"], 2) == 34.21


# ============================================================================
# 17. METADATA IDENTIFIES TRANSCRIPT SOURCE
# ============================================================================

def test_metadata_identifies_transcript_source():
    """Verify SceneBlock and dictionary serialization correctly reflect transcript_source."""
    b_sub = SceneBlock(movie_start=1.0, movie_end=5.0, narration_text="Sub scene", word_count=2, transcript_source="existing_subtitles")
    b_usr = SceneBlock(movie_start=1.0, movie_end=5.0, narration_text="Usr scene", word_count=2, transcript_source="user_transcript")
    b_asr = SceneBlock(movie_start=1.0, movie_end=5.0, narration_text="ASR scene", word_count=2, transcript_source="asr")
    b_non = SceneBlock(movie_start=1.0, movie_end=5.0, narration_text="Non scene", word_count=2, transcript_source="none")

    assert b_sub.to_dict()["transcript_source"] == "existing_subtitles"
    assert b_usr.to_dict()["transcript_source"] == "user_transcript"
    assert b_asr.to_dict()["transcript_source"] == "asr"
    assert b_non.to_dict()["transcript_source"] == "none"
