import pytest
from app.services.video_engine import VideoEngine


def test_parse_youtube_web_copy_paste_multiline():
    """
    Tests parsing YouTube web UI transcript where timestamps and text
    alternate on separate lines.
    """
    raw_text = """
    0:03
    In a world full of secrets
    0:18
    She was working as an ordinary cashier
    1:05
    Suddenly two armed men walked into the store
    2:15
    Nobody expected her to fight back
    """
    res = VideoEngine.parse_raw_transcript_text(raw_text)

    assert "dialogue_timeline" in res
    cues = res["dialogue_timeline"]
    assert len(cues) == 4
    assert cues[0]["start"] == 3.0
    assert "In a world full of secrets" in cues[0]["text"]
    assert cues[1]["start"] == 18.0
    assert cues[2]["start"] == 65.0
    assert cues[3]["start"] == 135.0

    # Verify timeline summary and subtitles_text formatting
    assert "Key Timeline Milestones" in res["subtitles_text"] or len(res["timeline_summary"]) > 0
    assert res["total_duration"] >= 135.0


def test_parse_same_line_and_bracketed_timestamps():
    """
    Tests parsing transcripts where timestamp and text are on the same line,
    with or without brackets.
    """
    raw_text = """
    [00:15] Detective Miller arrives at the warehouse.
    [01:30] He discovers a secret door behind the shelf.
    02:45 The alarm suddenly goes off.
    """
    res = VideoEngine.parse_raw_transcript_text(raw_text)
    cues = res["dialogue_timeline"]

    assert len(cues) == 3
    assert cues[0]["start"] == 15.0
    assert "Detective Miller arrives" in cues[0]["text"]
    assert cues[1]["start"] == 90.0
    assert cues[2]["start"] == 165.0


def test_parse_srt_or_vtt_format():
    """
    Tests parsing standard SRT or VTT content passed into parse_raw_transcript_text.
    """
    raw_vtt = """WEBVTT

1
00:00:10.500 --> 00:00:14.200
Look who finally decided to show up.

2
00:00:15.000 --> 00:00:20.000
I never wanted any part of this.
"""
    res = VideoEngine.parse_raw_transcript_text(raw_vtt)
    cues = res["dialogue_timeline"]

    assert len(cues) == 2
    assert cues[0]["start"] == 10.5
    assert cues[0]["end"] == 14.2
    assert "Look who finally" in cues[0]["text"]
    assert cues[1]["start"] == 15.0


def test_parse_empty_or_whitespace_transcript():
    """
    Tests graceful fallback on empty or invalid text.
    """
    res = VideoEngine.parse_raw_transcript_text("")
    assert res["dialogue_timeline"] == []
    assert res["subtitles_text"] == ""
    assert res["total_duration"] == 0.0
