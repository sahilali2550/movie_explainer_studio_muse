import os
import pytest
from app.services.subtitle_engine import SubtitleEngine

def test_subtitle_engine_with_timed_cues(tmp_path):
    """Verify that SubtitleEngine uses speech cues directly for precision synchronization."""
    ur_cues = [
        {"start": 0.0, "end": 2.8, "text": "کہانی کی شروعات ایک پراسرار کمرے سے ہوتی ہے"},
        {"start": 2.8, "end": 6.2, "text": "جہاں ہیرو اپنے دشمن کے سامنے بے بس کھڑا ہے"}
    ]
    srt_path = str(tmp_path / "urdu_test.srt")
    ok = SubtitleEngine.save_srt_file(
        script_text="ignored because timed_cues are provided",
        total_duration=10.0,
        output_path=srt_path,
        timed_cues=ur_cues
    )
    assert ok is True
    assert os.path.exists(srt_path)

    content = open(srt_path, encoding="utf-8").read()
    assert "00:00:00,000 --> 00:00:02,800" in content
    assert "کہانی کی شروعات ایک پراسرار کمرے سے ہوتی ہے" in content
    assert "00:00:02,800 --> 00:00:06,200" in content
    assert "جہاں ہیرو اپنے دشمن کے سامنے بے بس کھڑا ہے" in content

def test_subtitle_engine_fallback_multilingual_punctuation():
    """Verify fallback sentence segmentation for Urdu (۔) and English (.) without timed_cues."""
    urdu_script = "یہ پہلا سین ہے اور بہت سنسنی خیز ہے۔ اس کے بعد وہ بھاگنے کی کوشش کرتا ہے مگر ناکام رہتا ہے۔"
    cues_ur = SubtitleEngine.split_script_into_cues(urdu_script, total_duration=8.0)
    assert len(cues_ur) >= 2
    assert "یہ پہلا سین ہے" in cues_ur[0][2]

    en_script = "The detective arrives at the crime scene. He finds a silver pendant on the floor."
    cues_en = SubtitleEngine.split_script_into_cues(en_script, total_duration=8.0)
    assert len(cues_en) == 2
    assert cues_en[0][0] == 0.0
    assert cues_en[-1][1] == 8.0

def test_multi_language_srt_generation(tmp_path):
    """Simulate Global Multiplier generating distinct SRTs for English and Urdu dubs."""
    total_dur = 12.0
    en_cues = [
        {"start": 0.0, "end": 5.5, "text": "Frank Castle tracks down the criminal syndicate."},
        {"start": 5.5, "end": 12.0, "text": "A massive gunfight erupts inside the abandoned warehouse."}
    ]
    ur_cues = [
        {"start": 0.0, "end": 5.2, "text": "فرینک کاسل مجرموں کے گروہ کا پیچھا کرتا ہے۔"},
        {"start": 5.2, "end": 12.0, "text": "ایک ویران گودام کے اندر زبردست فائرنگ شروع ہو جاتی ہے۔"}
    ]

    en_srt = str(tmp_path / "AutoExplainer_SUBS_test_en.srt")
    ur_srt = str(tmp_path / "AutoExplainer_SUBS_test_ur.srt")

    assert SubtitleEngine.save_srt_file("en script", total_dur, en_srt, timed_cues=en_cues) is True
    assert SubtitleEngine.save_srt_file("ur script", total_dur, ur_srt, timed_cues=ur_cues) is True

    en_content = open(en_srt, encoding="utf-8").read()
    ur_content = open(ur_srt, encoding="utf-8").read()

    assert "Frank Castle" in en_content
    assert "00:00:00,000 --> 00:00:05,500" in en_content
    assert "فرینک کاسل" in ur_content
    assert "00:00:00,000 --> 00:00:05,200" in ur_content
