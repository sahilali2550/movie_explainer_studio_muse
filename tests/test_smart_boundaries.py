import pytest
from app.services.script_engine import ScriptEngine
from app.services.video_engine import VideoEngine

def test_partition_timeline_with_dialogue_end_at_climax():
    """
    Scenario 1: Movie is 86 minutes (5160s). Spoken dialogues run until 85:40 (5140s).
    Smart boundary detection must NOT cut off 5.6 minutes (80 mins); it must preserve 100% of the climax
    and span all the way to ~5155s (85:55).
    """
    movie_dur = 5160.0  # 86 minutes
    dialogue_timeline = [
        {"start": 60.0, "end": 65.0, "text": "Who is there?"},
        {"start": 2000.0, "end": 2005.0, "text": "We have to find the truth."},
        {"start": 5130.0, "end": 5140.0, "text": "It was you all along! The case is finally closed."}  # 85:40
    ]

    milestones = ScriptEngine.partition_timeline(
        source_duration_sec=movie_dur,
        target_duration_mins=10,
        dialogue_timeline=dialogue_timeline
    )

    assert len(milestones) == 5
    final_act = milestones[-1]
    # Final act must reach at least 5140s (85:40) to deliver the true climax
    assert final_act["end_sec"] >= 5140.0
    # First act should start near the first dialogue (around 55s), skipping opening logos
    first_act = milestones[0]
    assert first_act["start_sec"] >= 50.0

def test_partition_timeline_with_silent_credits():
    """
    Scenario 2: Movie is 86 minutes (5160s). Final dialogue ends at 78:00 (4680s).
    The remaining 8 minutes are silent rolling credits.
    Smart boundary detection must recognize that dialogues ended at 78:00 and cleanly
    exclude the silent credits, stopping near 4700s.
    """
    movie_dur = 5160.0  # 86 minutes
    dialogue_timeline = [
        {"start": 30.0, "end": 35.0, "text": "Let us begin."},
        {"start": 2500.0, "end": 2505.0, "text": "The conflict escalates."},
        {"start": 4670.0, "end": 4680.0, "text": "Goodbye, my friend. It is over."}  # 78:00
    ]

    milestones = ScriptEngine.partition_timeline(
        source_duration_sec=movie_dur,
        target_duration_mins=10,
        dialogue_timeline=dialogue_timeline
    )

    final_act = milestones[-1]
    # Must stop around 4680s - 4700s, cleanly cutting out the 8 minutes of silent rolling credits
    assert 4680.0 <= final_act["end_sec"] <= 4710.0

def test_partition_timeline_intro_skipping():
    """
    Scenario 3: Movie has 2.5 minutes (150s) of opening studio logos and silent title cards.
    First dialogue is at 150s (02:30).
    Smart boundary detection must start Act 1 at ~145s, skipping the empty intro.
    """
    movie_dur = 3600.0  # 60 mins
    dialogue_timeline = [
        {"start": 150.0, "end": 155.0, "text": "Welcome to the city of mysteries."},  # 02:30
        {"start": 1800.0, "end": 1805.0, "text": "Halfway through."},
        {"start": 3500.0, "end": 3510.0, "text": "The end."}
    ]

    milestones = ScriptEngine.partition_timeline(
        source_duration_sec=movie_dur,
        target_duration_mins=10,
        dialogue_timeline=dialogue_timeline
    )

    first_act = milestones[0]
    assert 140.0 <= first_act["start_sec"] <= 150.0

def test_video_engine_safe_story_duration():
    """
    VideoEngine.get_safe_story_duration must preserve climax when dialogue_timeline reaches end.
    """
    movie_dur = 5160.0
    dialogue_timeline = [
        {"start": 5130.0, "end": 5145.0, "text": "Final climax reveal!"}
    ]

    safe_dur = VideoEngine.get_safe_story_duration(movie_dur, dialogue_timeline=dialogue_timeline)
    assert safe_dur >= 5145.0
