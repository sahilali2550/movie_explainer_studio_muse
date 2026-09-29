import pytest
from app.services.script_engine import ScriptEngine
from app.services.audio_mixer import AudioMixer
from app.services.video_engine import VideoEngine


def test_script_engine_extract_sfx_cues_and_clean_text():
    """
    Verifies that [SFX: ...] tags are correctly parsed into timed cues
    and stripped completely from spoken voiceover text.
    """
    sample_script = """
    [SCENE: 01:10 - 01:25]
    The detective arrived at the foggy crime scene. [SFX: WHOOSH]
    Everything looked quiet, until he heard a faint sound under the floor. [SFX: HEARTBEAT]
    
    [SCENE: 04:30 - 04:45]
    He opened the trapdoor and discovered the lost treasure! [SFX: SUB_BOOM]
    """
    clean_text, ranges, subs = ScriptEngine.parse_storyboard(sample_script)
    
    # Narration MUST NOT contain any bracketed tags
    assert "[SFX:" not in clean_text
    assert "[SCENE:" not in clean_text
    assert "WHOOSH" not in clean_text
    assert "HEARTBEAT" not in clean_text
    assert "SUB_BOOM" not in clean_text
    assert "detective arrived" in clean_text
    assert "trapdoor" in clean_text
    
    # Scene ranges extracted
    assert len(ranges) == 2
    assert ranges[0] == (70.0, 85.0)   # 01:10 - 01:25
    assert ranges[1] == (270.0, 285.0) # 04:30 - 04:45
    
    # SFX Cues extraction
    cues = ScriptEngine.extract_sfx_cues(sample_script, total_duration=60.0)
    assert len(cues) >= 3
    sfx_names = [c["sfx"] for c in cues]
    assert "whoosh" in sfx_names
    assert "heartbeat" in sfx_names
    assert "sub_boom" in sfx_names
    
    # Timestamps must be in ascending order within 0 to 60s
    for c in cues:
        assert 0.0 <= c["time"] <= 60.0


def test_audio_mixer_integrates_explicit_sfx_cues():
    """
    Verifies that AudioMixer seamlessly accepts explicit AI-directed SFX cues
    and incorporates them into the final timeline.
    """
    explicit_cues = [
        {"time": 5.0, "sfx": "whoosh", "volume": 0.45},
        {"time": 15.2, "sfx": "heartbeat", "volume": 0.50},
        {"time": 25.0, "sfx": "sub_boom", "volume": 0.60}
    ]
    mixed_cues = AudioMixer.build_sfx_cue_points(
        total_duration=30.0,
        explicit_sfx_cues=explicit_cues
    )
    # Explicit cues must be preserved
    cue_times = [c["time"] for c in mixed_cues]
    assert 5.0 in cue_times
    assert 15.2 in cue_times
    assert 25.0 in cue_times


def test_video_engine_clamps_ai_scene_ranges():
    """
    Verifies that build_chronological_scene_map gracefully handles
    AI-directed timestamps, clamping any out-of-bounds times to total_movie_dur.
    """
    movie_dur = 120.0
    # Provide one valid and one out-of-bounds range
    ai_ranges = [(10.0, 25.0), (115.0, 150.0)]
    cuts = VideoEngine.build_chronological_scene_map(
        scene_ranges=ai_ranges,
        total_movie_dur=movie_dur,
        target_duration=30.0,
        micro_clip_dur=3.5
    )
    assert len(cuts) > 0
    # Every cut must be within [0, movie_dur]
    for s, e in cuts:
        assert 0.0 <= s < movie_dur
        assert s < e <= movie_dur


def test_bulletproof_script_and_tts_sanitization():
    """
    Verifies that lines starting with [SFX: ...] are never dropped,
    and all director tags/brackets are completely sanitized for TTS and Storyboard.
    """
    from app.services.voice_engine import VoiceEngine

    messy_script = """
    [SCENE 1: 00:00 - 00:15]
    [VOICEOVER]
    [SFX: HEARTBEAT] کہانی کا آغاز ایک پراسرار کمرے سے ہوتا ہے۔
    [SFX: WHOOSH] [DIALOGUE_REF: "Who is there?"] جہاں ایک شخص خوف سے کانپ رہا تھا۔
    
    [SCENE 2: 00:15 - 00:30]
    [VOICEOVER]
    [SFX: TENSION_RISER] اچانک دروازہ کھلتا ہے اور سچ سامنے آتا ہے۔
    """
    clean_text, ranges, subs = ScriptEngine.parse_storyboard(messy_script)
    assert len(ranges) == 2
    assert "کہانی کا آغاز" in clean_text
    assert "شخص خوف سے کانپ رہا تھا" in clean_text
    assert "اچانک دروازہ کھلتا ہے" in clean_text
    assert "HEARTBEAT" not in clean_text
    assert "WHOOSH" not in clean_text
    assert "TENSION_RISER" not in clean_text
    assert "SCENE" not in clean_text
    assert "VOICEOVER" not in clean_text
    assert "[" not in clean_text
    assert "]" not in clean_text

    blocks = ScriptEngine.parse_storyboard_blocks(messy_script)
    assert len(blocks) == 2
    assert blocks[0].word_count > 0
    assert blocks[1].word_count > 0
    assert "کہانی کا آغاز" in blocks[0].narration_text

    tts_clean = VoiceEngine.sanitize_narration_for_tts(messy_script)
    assert "SCENE" not in tts_clean
    assert "VOICEOVER" not in tts_clean
    assert "SFX" not in tts_clean
    assert "HEARTBEAT" not in tts_clean
    assert "[" not in tts_clean
    assert "]" not in tts_clean
    assert "کہانی کا آغاز ایک پراسرار کمرے سے ہوتا ہے۔" in tts_clean

