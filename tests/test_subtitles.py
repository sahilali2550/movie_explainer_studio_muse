import pytest
import os
import tempfile
from app.services.subtitle_engine import SubtitleEngine


def test_srt_timestamp_formatting():
    """SubtitleEngine must format seconds into standard SRT HH:MM:SS,mmm string."""
    assert SubtitleEngine.format_timestamp_srt(0.0) == "00:00:00,000"
    assert SubtitleEngine.format_timestamp_srt(65.45) == "00:01:05,450"
    assert SubtitleEngine.format_timestamp_srt(3661.125) == "01:01:01,125"


def test_vtt_timestamp_formatting():
    """SubtitleEngine must format seconds into WebVTT HH:MM:SS.mmm string."""
    assert SubtitleEngine.format_timestamp_vtt(65.45) == "00:01:05.450"


def test_script_cues_splitting():
    """SubtitleEngine must split script into cues proportional to total duration."""
    script = (
        "In a dark quiet town, a strange detective arrives at midnight. "
        "He searches for clues left behind by the masked thief. "
        "Will he solve the mystery before time runs out?"
    )
    duration = 30.0
    cues = SubtitleEngine.split_script_into_cues(script, duration)

    assert len(cues) >= 3
    # First cue starts at 0
    assert cues[0][0] == 0.0
    # Last cue finishes at or near total duration
    assert cues[-1][1] == duration
    # Cue texts are non-empty
    for start_t, end_t, text in cues:
        assert end_t > start_t
        assert len(text.strip()) > 0


def test_generate_srt_file_on_disk():
    """SubtitleEngine must write valid .srt file to disk."""
    script = "Yeh kahani hai ek shakhs ki jis ne waqt ko peechay morr diya. Usay koi andaza nahi tha ke anjaam kya hoga."
    duration = 15.0

    with tempfile.TemporaryDirectory() as td:
        target_file = os.path.join(td, "test_subs.srt")
        ok = SubtitleEngine.save_srt_file(script, duration, target_file)
        assert ok is True
        assert os.path.exists(target_file)

        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "-->" in content
        assert "00:00:00,000" in content


def test_ass_subtitles_with_timed_cues(tmp_path):
    """VideoEngine.generate_ass_subtitle_file must format exact Edge-TTS boundary events."""
    from app.services.video_engine import VideoEngine
    ass_file = str(tmp_path / "test_subs.ass")
    timed_cues = [
        {"start": 0.5, "end": 4.2, "text": "پہلا جملہ بولا گیا۔"},
        {"start": 4.5, "end": 9.8, "text": "دوسرا جملہ مکمل ہوا۔"}
    ]
    ok = VideoEngine.generate_ass_subtitle_file(
        scene_subtitles=[],
        total_duration=10.0,
        output_ass_path=ass_file,
        aspect_ratio="horizontal",
        lang="ur",
        timed_cues=timed_cues,
        speed_factor=1.02
    )
    assert ok is True
    assert os.path.exists(ass_file)
    with open(ass_file, "r", encoding="utf-8") as f:
        ass_txt = f.read()
    assert "Dialogue: 0," in ass_txt
    assert "پہلا جملہ بولا گیا۔" in ass_txt
    assert "دوسرا جملہ مکمل ہوا۔" in ass_txt


def test_ass_subtitles_proportional_duration_fallback(tmp_path):
    """Without timed_cues, long sentences must receive proportionally more duration than short ones."""
    from app.services.video_engine import VideoEngine
    ass_file = str(tmp_path / "test_prop.ass")
    # Short sentence (10 chars) vs Long sentence (70 chars)
    short_s = "چھوٹا جملہ"
    long_s = "یہ ایک بہت ہی طویل اور لمبا تفصیلی جملہ ہے جس کو بولنے میں کافی وقت لگتا ہے۔"
    ok = VideoEngine.generate_ass_subtitle_file(
        scene_subtitles=[short_s, long_s],
        total_duration=20.0,
        output_ass_path=ass_file,
        aspect_ratio="horizontal",
        lang="ur",
        speed_factor=1.0
    )
    assert ok is True
    with open(ass_file, "r", encoding="utf-8") as f:
        lines = [line for line in f if line.startswith("Dialogue: 0,")]
    assert len(lines) == 2
    # Parse timestamps for short vs long
    # Dialogue: 0,0:00:00.00,0:00:03.xx,...
    p1 = lines[0].split(",")
    p2 = lines[1].split(",")
    # The end time of cue 1 is the start of cue 2
    cue1_dur = float(p1[2].split(":")[-1])
    cue2_dur = float(p2[2].split(":")[-1]) - float(p2[1].split(":")[-1])
    assert cue2_dur > cue1_dur * 1.5, f"Expected long sentence to have significantly more duration: {cue2_dur} vs {cue1_dur}"


def test_ass_subtitles_noto_nastaliq_font_for_urdu(tmp_path):
    """Verify that Urdu and Arabic use Noto Nastaliq Urdu font in ASS styles."""
    from app.services.video_engine import VideoEngine
    ass_file = str(tmp_path / "test_font.ass")
    ok = VideoEngine.generate_ass_subtitle_file(
        scene_subtitles=["یہ ایک جملہ ہے۔"],
        total_duration=5.0,
        output_ass_path=ass_file,
        lang="ur"
    )
    assert ok is True
    with open(ass_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Style: Default,Noto Nastaliq Urdu," in content


def test_ass_subtitles_production_tag_stripping(tmp_path):
    """Verify that technical tags ([SCENE: ...], [SFX: ...], etc.) are never burned to ASS subtitles."""
    from app.services.video_engine import VideoEngine
    ass_file = str(tmp_path / "test_tags.ass")
    tagged_sub = "[SCENE 1: 00:00 - 00:15] [VOICEOVER] [SFX: HEARTBEAT] اصل کہانی یہاں سے شروع ہوتی ہے [DIALOGUE_REF: 'Help me']"
    ok = VideoEngine.generate_ass_subtitle_file(
        scene_subtitles=[tagged_sub],
        total_duration=6.0,
        output_ass_path=ass_file,
        lang="ur"
    )
    assert ok is True
    with open(ass_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "[SCENE" not in content
    assert "VOICEOVER" not in content
    assert "SFX" not in content
    assert "DIALOGUE_REF" not in content
    assert "اصل کہانی یہاں سے شروع ہوتی ہے" in content


def test_ass_subtitles_long_cue_chunking(tmp_path):
    """Verify that long sentences with chunk_cues=True break into punchy 3-5s lines."""
    from app.services.video_engine import VideoEngine
    ass_file = str(tmp_path / "test_chunk.ass")
    long_paragraph = "یہ ایک بہت بڑا اور تفصیلی پیراگراف ہے جس میں کہانی کے تمام اہم واقعات اور پراسرار راز کھولے گئے ہیں اور ہر بات واضح کی گئی ہے۔"
    ok = VideoEngine.generate_ass_subtitle_file(
        scene_subtitles=[long_paragraph],
        total_duration=15.0,
        output_ass_path=ass_file,
        lang="ur",
        chunk_cues=True
    )
    assert ok is True
    with open(ass_file, "r", encoding="utf-8") as f:
        lines = [line for line in f if line.startswith("Dialogue: 0,")]
    assert len(lines) >= 3  # Long paragraph cleanly divided into multiple punchy lines


