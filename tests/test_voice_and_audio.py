import pytest
from app.services.voice_engine import VoiceEngine
from app.services.audio_mixer import AudioMixer
from app.core.config import SUPPORTED_LANGUAGES


def test_default_voices_for_all_supported_languages():
    """Every supported language must have a valid neural voice mapping."""
    for lang_code in SUPPORTED_LANGUAGES.keys():
        voice = VoiceEngine.get_default_voice_for_lang(lang_code)
        assert voice is not None and len(voice) > 0, f"Missing default voice for language: {lang_code}"
        assert "Neural" in voice, f"Voice {voice} for {lang_code} is not a neural voice"


def test_audio_mixer_mood_fallback():
    """AudioMixer must resolve mood folders or fall back gracefully without raising."""
    for mood in ["suspense", "tense", "action", "emotional", "upbeat", "dark", "unknown_mood"]:
        track = AudioMixer.get_mood_music_track(mood)
        # track is either None (if no sample music files in directory) or a valid filepath string
        assert track is None or isinstance(track, str)


def test_voice_engine_get_speech_cues(tmp_path):
    """VoiceEngine must write and retrieve speech cues for synchronized subtitles."""
    audio_file = str(tmp_path / "sample_speech.mp3")
    cues_file = str(tmp_path / "sample_speech_cues.json")
    
    # Initially no cues
    assert VoiceEngine.get_speech_cues(audio_file) == []

    # With companion json
    import json
    sample_cues = [
        {"start": 0.1, "end": 2.5, "text": "پہلا جملہ۔"},
        {"start": 2.6, "end": 5.0, "text": "دوسرا جملہ۔"}
    ]
    with open(cues_file, "w", encoding="utf-8") as f:
        json.dump(sample_cues, f)

    retrieved = VoiceEngine.get_speech_cues(audio_file)
    assert len(retrieved) == 2
    assert retrieved[0]["text"] == "پہلا جملہ۔"
    assert retrieved[1]["end"] == 5.0

