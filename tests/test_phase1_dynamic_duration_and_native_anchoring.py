import pytest
from app.services.script_engine import ScriptEngine, SceneBlock

def test_language_wpm_and_dynamic_duration_scaling():
    """Verify that WPM is properly calibrated and scales dynamically without hardcoded caps."""
    # Urdu at 200 WPM
    assert ScriptEngine.LANGUAGE_WPM["ur"] == 200
    assert ScriptEngine.calculate_target_words(1, voice_speed="normal", target_lang="ur") == 200
    assert ScriptEngine.calculate_target_words(3, voice_speed="normal", target_lang="ur") == 600
    assert ScriptEngine.calculate_target_words(5, voice_speed="normal", target_lang="ur") == 1000
    assert ScriptEngine.calculate_target_words(10, voice_speed="normal", target_lang="ur") == 2000
    assert ScriptEngine.calculate_target_words(15, voice_speed="normal", target_lang="ur") == 3000

    # English at 150 WPM
    assert ScriptEngine.LANGUAGE_WPM["en"] == 150
    assert ScriptEngine.calculate_target_words(3, voice_speed="normal", target_lang="en") == 450
    assert ScriptEngine.calculate_target_words(5, voice_speed="normal", target_lang="en") == 750
    assert ScriptEngine.calculate_target_words(10, voice_speed="normal", target_lang="en") == 1500

    # Fast speed multiplier (1.15x)
    assert ScriptEngine.calculate_target_words(5, voice_speed="fast", target_lang="ur") == 1150
    assert ScriptEngine.calculate_target_words(5, voice_speed="fast", target_lang="en") == 862

def test_detect_transcript_language():
    """Verify automatic language detection from transcript samples."""
    urdu_sample = "کہانی کی شروعات ایک خوفناک انکشاف سے ہوتی ہے جہاں کیتھ زیرا گواہی دینے جا رہا ہے"
    assert ScriptEngine.detect_transcript_language(urdu_sample) == "ur"

    arabic_sample = "تبدأ القصة باكتشاف مرعب حيث يقرر الشاهد الإدلاء بشهادته أمام المحكمة"
    assert ScriptEngine.detect_transcript_language(arabic_sample) == "ar"

    hindi_sample = "कहानी की शुरुआत एक भयानक खुलासे से होती है जहाँ गवाह अदालत में जाता है"
    assert ScriptEngine.detect_transcript_language(hindi_sample) == "hi"

    turkish_sample = "Olaylar çok hızlı gelişti ve polis şüpheliyi yakalamak için harekete geçti"
    assert ScriptEngine.detect_transcript_language(turkish_sample) == "tr"

    english_sample = "1:42 ZERA [narrating]: You know, I remember the first time I set foot in Africa."
    assert ScriptEngine.detect_transcript_language(english_sample) == "en"

def test_prompt_enforces_dialogue_ref():
    """Verify that the storyboard generation prompt mandates [DIALOGUE_REF: ...] for each scene."""
    prompt = ScriptEngine.build_prompt_for_genre(
        genre="movie_recap",
        title="24 Hours to Live",
        description="Action thriller",
        subs_text="1:42 Zera says Africa was hot",
        target_lang="ur",
        duration_mins=5
    )
    assert "DIALOGUE_REF" in prompt
    assert "[DIALOGUE_REF:" in prompt or "DIALOGUE_REF:" in prompt

def test_anchor_scenes_to_dialogue_with_dialogue_ref():
    """Verify that scenes with DIALOGUE_REF anchor with high accuracy to source cues."""
    dialogue_timeline = [
        {"start": 102.5, "end": 108.0, "text": "I remember the first time I set foot in Africa"},
        {"start": 345.0, "end": 350.0, "text": "Put the gun down and get on your knees right now"},
        {"start": 1200.0, "end": 1205.0, "text": "Just follow my voice, stay with me Travis"},
    ]
    blocks = [
        SceneBlock(
            movie_start=10.0,
            movie_end=20.0,
            narration_text="کہانی کی شروعات افریقہ کے صحرا سے ہوتی ہے",
            word_count=10,
            dialogue_ref="first time I set foot in Africa"
        ),
        SceneBlock(
            movie_start=50.0,
            movie_end=60.0,
            narration_text="ہوٹل کے کمرے میں گن پوائنٹ پر لن چیخ کر کہتی ہے",
            word_count=10,
            dialogue_ref="Put the gun down and get on your knees"
        )
    ]
    anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
    assert len(anchored) == 2
    # Block 0 should anchor around 102.5
    assert anchored[0].movie_start == 102.5
    # Block 1 should anchor around 345.0
    assert anchored[1].movie_start == 345.0
