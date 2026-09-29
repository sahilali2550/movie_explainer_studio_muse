import pytest
from app.services.script_engine import ScriptEngine
from app.services.video_engine import VideoEngine

def test_partition_timeline_credits_blacklist_guard():
    """Verify that partition_timeline blacklists the end credits on long movies and dramas."""
    # 92-minute movie (5530 seconds)
    movie_dur = 5530.0
    milestones = ScriptEngine.partition_timeline(movie_dur, 5)
    assert len(milestones) == 5
    epilogue = milestones[-1]
    
    # Epilogue must NEVER reach the end credits (5530s)
    # Must stop at least 3-6 minutes before movie ends (safe_end <= 5530 * 0.94)
    assert epilogue["end_sec"] < movie_dur
    assert epilogue["end_sec"] <= movie_dur * 0.94
    assert epilogue["end_sec"] <= 5530.0 - 180.0

def test_partition_timeline_short_and_medium_content():
    """Verify partition_timeline handles short clips (<10 mins) and medium dramas appropriately."""
    # 30-minute drama (1800 seconds)
    drama_dur = 1800.0
    drama_ms = ScriptEngine.partition_timeline(drama_dur, 5)
    assert drama_ms[-1]["end_sec"] < drama_dur
    assert drama_ms[-1]["end_sec"] <= 1800.0 - 120.0

    # Short video (5 minutes = 300 seconds)
    short_dur = 300.0
    short_ms = ScriptEngine.partition_timeline(short_dur, 3)
    # Short content shouldn't aggressively strip 4 minutes
    assert short_ms[-1]["end_sec"] <= short_dur

def test_safe_movie_timeline_clamping():
    """Verify that video engine clamps timeline cuts away from end credits."""
    total_dur = 5530.0
    # Safe boundary should leave at least 180-360 seconds for credits
    safe_dur = VideoEngine.get_safe_story_duration(total_dur)
    assert safe_dur <= total_dur - 180.0
    assert safe_dur <= total_dur * 0.94
