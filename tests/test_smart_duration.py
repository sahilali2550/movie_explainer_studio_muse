import pytest
from app.services.script_engine import ScriptEngine
from app.core.config import SUPPORTED_LANGUAGES

def test_language_wpm_matrix_covers_all_supported_languages():
    """Verifies every supported language has a calibrated empirical speaking rate (WPM)."""
    assert hasattr(ScriptEngine, "LANGUAGE_WPM"), "ScriptEngine must define LANGUAGE_WPM dictionary"
    for lang_code in SUPPORTED_LANGUAGES.keys():
        assert lang_code in ScriptEngine.LANGUAGE_WPM, f"Missing WPM calibration for language: {lang_code}"
        assert ScriptEngine.LANGUAGE_WPM[lang_code] >= 120, f"Unrealistic WPM for {lang_code}"

def test_calculate_target_words_language_and_speed_calibration():
    """Verifies target word counts dynamically adapt to selected language and velocity."""
    # Urdu at +15% fast speed: 10 mins * 200 * 1.15 = 2300
    ur_10 = ScriptEngine.calculate_target_words(10, voice_speed="fast", target_lang="ur")
    assert 2250 <= ur_10 <= 2350, f"Expected ~2300 words for 10m Urdu fast, got {ur_10}"

    # English at +15% fast speed: 10 mins * 150 * 1.15 = 1725
    en_10 = ScriptEngine.calculate_target_words(10, voice_speed="fast", target_lang="en")
    assert 1650 <= en_10 <= 1800, f"Expected ~1725 words for 10m English, got {en_10}"

    # Spanish at +15% fast speed: 10 mins * 165 * 1.15 = 1897.5
    es_10 = ScriptEngine.calculate_target_words(10, voice_speed="fast", target_lang="es")
    assert 1850 <= es_10 <= 2050, f"Expected ~1898 words for 10m Spanish, got {es_10}"

    # Arabic at normal speed: 5 mins * 145 * 1.0 = 725
    ar_5 = ScriptEngine.calculate_target_words(5, voice_speed="normal", target_lang="ar")
    assert 700 <= ar_5 <= 750, f"Expected ~725 words for 5m Arabic normal, got {ar_5}"

    # 1 min Hindi at +15% fast speed: 1 min * 160 * 1.15 = 184
    hi_1 = ScriptEngine.calculate_target_words(1, voice_speed="fast", target_lang="hi")
    assert 175 <= hi_1 <= 195, f"Expected ~184 words for 1m Hindi fast, got {hi_1}"

def test_prompt_includes_source_video_duration_and_act_quotas():
    """Verifies build_prompt_for_genre includes source video duration context and explicit act quotas."""
    prompt = ScriptEngine.build_prompt_for_genre(
        genre="movie_recap",
        title="Ten Years Of Loving You",
        description="A Chinese romantic drama",
        subs_text="Dialogue transcripts...",
        target_lang="ur",
        duration_mins=10,
        voice_speed="fast",
        source_video_duration_sec=5400  # 90 minutes
    )
    # Check act quotas are explicitly present to prevent early wrap-up
    assert "Act 1" in prompt
    assert "Act 2" in prompt
    assert "Act 3" in prompt
    assert "words" in prompt.lower()
    # Check source video duration context is present
    assert "90" in prompt or "5400" in prompt or "Source Video" in prompt

def test_expand_script_returns_valid_structure():
    """Verifies expand_script contract and fallback handling."""
    res = ScriptEngine.expand_script(
        current_script="A short story draft.",
        target_lang="en",
        duration_mins=5,
        voice_speed="fast"
    )
    assert "script" in res
    assert "success" in res
