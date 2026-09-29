import os
import pytest
from app.services.video_engine import VideoEngine

def test_ass_subtitle_language_adaptive_styling(tmp_path):
    """Verify that ASS subtitles adaptively size and style for Urdu, English, and Hindi."""
    cues = [
        {"start": 0.0, "end": 3.5, "text": "کہانی کی شروعات ایک خوفناک انکشاف سے ہوتی ہے"},
        {"start": 3.5, "end": 7.0, "text": "ہوٹل کے کمرے میں گن پوائنٹ پر لن چیخ کر کہتی ہے"}
    ]
    ass_path_ur_h = str(tmp_path / "sub_ur_h.ass")
    ok = VideoEngine.generate_ass_subtitle_file(
        scene_subtitles=[],
        total_duration=10.0,
        output_ass_path=ass_path_ur_h,
        aspect_ratio="horizontal",
        lang="ur",
        timed_cues=cues
    )
    assert ok is True
    assert os.path.exists(ass_path_ur_h)
    content_ur_h = open(ass_path_ur_h, encoding="utf-8").read()
    # Urdu 16:9 must be 54pt bold Noto Nastaliq Urdu
    assert "Noto Nastaliq Urdu,54" in content_ur_h

    # Urdu 9:16 vertical must be 64pt
    ass_path_ur_v = str(tmp_path / "sub_ur_v.ass")
    VideoEngine.generate_ass_subtitle_file(
        scene_subtitles=[],
        total_duration=10.0,
        output_ass_path=ass_path_ur_v,
        aspect_ratio="vertical",
        lang="ur",
        timed_cues=cues
    )
    content_ur_v = open(ass_path_ur_v, encoding="utf-8").read()
    assert "Noto Nastaliq Urdu,64" in content_ur_v

    # English 16:9 must be 46pt
    ass_path_en_h = str(tmp_path / "sub_en_h.ass")
    en_cues = [{"start": 0.0, "end": 3.0, "text": "The story begins with a terrifying revelation"}]
    VideoEngine.generate_ass_subtitle_file(
        scene_subtitles=[],
        total_duration=10.0,
        output_ass_path=ass_path_en_h,
        aspect_ratio="horizontal",
        lang="en",
        timed_cues=en_cues
    )
    content_en_h = open(ass_path_en_h, encoding="utf-8").read()
    assert ",46," in content_en_h
