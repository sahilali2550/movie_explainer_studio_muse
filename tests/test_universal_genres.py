import pytest
from app.services.script_engine import ScriptEngine
from app.core.config import CONTENT_GENRES

def test_content_genres_defined():
    # Verify the 4 primary universal genres exist
    assert "movie_recap" in CONTENT_GENRES
    assert "biography" in CONTENT_GENRES
    assert "documentary" in CONTENT_GENRES
    assert "true_crime" in CONTENT_GENRES
    assert "tech_science" in CONTENT_GENRES
    assert "video_essay" in CONTENT_GENRES

def test_script_target_words_scaling():
    # Verify word count scales properly across durations
    # 1 min: ~150-180 words
    res_1 = ScriptEngine.calculate_target_words(duration_mins=1, voice_speed="fast")
    assert 140 <= res_1 <= 180

    # 3 min: ~450-500 words
    res_3 = ScriptEngine.calculate_target_words(duration_mins=3, voice_speed="fast")
    assert 440 <= res_3 <= 520

    # 10 min: ~1600-1900 words
    res_10 = ScriptEngine.calculate_target_words(duration_mins=10, voice_speed="ultra_fast")
    assert 1700 <= res_10 <= 1950

def test_genre_prompt_customization():
    # Biography genre prompt must contain biographical anchors (early life, turning point, legacy)
    prompt_bio = ScriptEngine.build_prompt_for_genre(
        genre="biography",
        title="Steve Jobs",
        description="Apple co-founder story",
        subs_text="",
        target_lang="en",
        duration_mins=5
    )
    assert "Biography" in prompt_bio or "biographical" in prompt_bio.lower()
    assert "Early Life" in prompt_bio or "Humble Beginnings" in prompt_bio or "struggle" in prompt_bio.lower()

    # Documentary genre prompt must emphasize investigation and facts
    prompt_doc = ScriptEngine.build_prompt_for_genre(
        genre="documentary",
        title="Mystery of the Bermuda Triangle",
        description="Naval investigations",
        subs_text="",
        target_lang="en",
        duration_mins=5
    )
    assert "Documentary" in prompt_doc or "investigative" in prompt_doc.lower()

    # True crime genre prompt must emphasize crime, forensics, timeline
    prompt_crime = ScriptEngine.build_prompt_for_genre(
        genre="true_crime",
        title="The Zodiac Mystery",
        description="Cold case homicide investigation",
        subs_text="",
        target_lang="en",
        duration_mins=5
    )
    assert "True Crime" in prompt_crime or "crime" in prompt_crime.lower()
    assert "Forensic" in prompt_crime or "incident" in prompt_crime.lower()

    # Tech science genre prompt must emphasize case study / business / tech
    prompt_tech = ScriptEngine.build_prompt_for_genre(
        genre="tech_science",
        title="How NVIDIA Conquered AI",
        description="Semiconductor disruption",
        subs_text="",
        target_lang="en",
        duration_mins=5
    )
    assert "Tech" in prompt_tech or "Business" in prompt_tech or "case study" in prompt_tech.lower()

