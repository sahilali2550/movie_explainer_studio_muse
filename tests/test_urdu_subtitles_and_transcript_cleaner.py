import pytest
from app.services.subtitle_engine import SubtitleEngine
from app.services.video_engine import VideoEngine


def test_urdu_fullstop_split_in_subtitles():
    # Urdu script with traditional Urdu full stops (۔ U+06D4) without newlines
    urdu_script = "یہ کہانی شروع ہوتی ہے ایک پراسرار جزیرے سے۔ جہاں رات ہوتے ہی خطرناک مخلوقات حملہ کر دیتی ہیں۔ فرینک اپنی جان بچانے کے لیے آخری حد تک لڑتا ہے۔"
    cues = SubtitleEngine.split_script_into_cues(urdu_script, total_duration=30.0)

    # Must be split into at least 3 distinct cues based on '۔'
    assert len(cues) >= 3
    # Check that sentences are bounded cleanly
    assert any("پراسرار جزیرے" in c[2] for c in cues)
    assert any("خطرناک مخلوقات" in c[2] for c in cues)
    assert any("آخری حد تک" in c[2] for c in cues)


def test_srt_generation_with_authoritative_timed_cues():
    script = "Sentence one. Sentence two."
    timed_cues = [
        {"start": 0.0, "end": 4.2, "text": "Sentence one."},
        {"start": 4.5, "end": 9.8, "text": "Sentence two."}
    ]
    srt = SubtitleEngine.generate_srt_content(script, total_duration=10.0, timed_cues=timed_cues)
    assert "00:00:00,000 --> 00:00:04,200" in srt
    assert "Sentence one." in srt
    assert "00:00:04,500 --> 00:00:09,800" in srt
    assert "Sentence two." in srt


def test_parse_raw_transcript_text_cleans_youtube_aria_noise():
    # YouTube web transcript format copied from browser panel
    raw_youtube_transcript = """1:20:451 hour, 20 minutes, 45 seconds[Music]
1:20:531 hour, 20 minutes, 53 secondsFrank realized the truth.
1:21:101 hour, 21 minutes, 10 secondsHe opened the bunker door."""

    res = VideoEngine.parse_raw_transcript_text(raw_youtube_transcript)
    cues = res["dialogue_timeline"]
    assert len(cues) >= 2

    # Noise must be cleaned out
    for c in cues:
        assert "1 hour, 20 minutes" not in c["text"]
        assert "[Music]" not in c["text"]

    # Valid dialogue should be preserved
    all_text = " ".join([c["text"] for c in cues])
    assert "Frank realized the truth" in all_text
    assert "He opened the bunker door" in all_text
