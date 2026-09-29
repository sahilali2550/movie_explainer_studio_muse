import pytest
from app.services.script_engine import ScriptEngine, SceneBlock
from app.services.video_engine import VideoEngine


def test_compress_transcript_to_roadmap_coverage():
    """Verifies that compress_transcript_to_roadmap samples chronological dialogue across the full movie."""
    # Simulate a 90-minute movie (5400s) with 200 subtitle lines
    sub_lines = []
    for m in range(90):
        sub_lines.append(f"{m:02d}:15 Line of dialogue at minute {m} explaining the plot event.")
        sub_lines.append(f"{m:02d}:45 Another line of dialogue at minute {m} with more action.")
    raw_subs = "\n".join(sub_lines)

    roadmap = ScriptEngine.compress_transcript_to_roadmap(raw_subs, total_movie_dur=5400.0, max_points=40)
    assert roadmap, "Roadmap should not be empty"
    lines = roadmap.strip().splitlines()
    assert 20 <= len(lines) <= 45, f"Expected 20-45 roadmap points, got {len(lines)}"

    # First point should be near beginning (0-5 mins)
    assert "[" in lines[0] and "]" in lines[0]
    # Last point should be deep into the movie (> 60 mins), before end credits
    last_line = lines[-1]
    import re
    last_ts_match = re.search(r'\[(\d{1,2}):(\d{2})\]', last_line)
    assert last_ts_match is not None, "Timestamp not found in last roadmap line"
    last_mins = int(last_ts_match.group(1))
    assert last_mins >= 65, f"Expected last roadmap point >= 65 mins, got {last_mins}"


def test_parse_storyboard_blocks():
    """Verifies parse_storyboard_blocks extracts SceneBlock objects with movie bounds and word counts."""
    script = """
    [SCENE: 01:30 - 02:45]
    [VOICEOVER]
    The detective arrives at the abandoned warehouse and notices broken glass on the floor.
    [SFX: HEARTBEAT]
    He draws his flashlight and carefully steps inside the dark hallway.

    [SCENE: 08:10 - 09:30]
    [VOICEOVER]
    Suddenly a shadow darts across the far corner. The suspect is trying to escape through the fire exit!
    """

    blocks = ScriptEngine.parse_storyboard_blocks(script)
    assert len(blocks) == 2, f"Expected 2 SceneBlocks, got {len(blocks)}"

    b1 = blocks[0]
    assert b1.movie_start == 90.0  # 01:30
    assert b1.movie_end == 165.0   # 02:45
    assert b1.word_count > 15
    assert "warehouse" in b1.narration_text
    assert "[SFX:" not in b1.narration_text, "SFX tags should be stripped from narration text"

    b2 = blocks[1]
    assert b2.movie_start == 490.0 # 08:10
    assert b2.movie_end == 570.0   # 09:30
    assert "suspect" in b2.narration_text


def test_assign_narration_timing_proportional_fallback():
    """Verifies assign_narration_timing distributes duration proportionally to word count when cues are absent."""
    b1 = SceneBlock(movie_start=10.0, movie_end=60.0, narration_text="Short block with ten words here for testing narration pacing now.", word_count=10)
    b2 = SceneBlock(movie_start=70.0, movie_end=150.0, narration_text="Longer block with thirty words in it. " * 3, word_count=30)
    
    total_speech_dur = 80.0
    timed_blocks = ScriptEngine.assign_narration_timing([b1, b2], total_speech_dur=total_speech_dur, cues=None)

    assert len(timed_blocks) == 2
    # b1: 10 / 40 = 25% of 80s = 20.0s
    assert abs(timed_blocks[0].speech_dur - 20.0) < 0.1
    assert timed_blocks[0].narration_start == 0.0
    assert abs(timed_blocks[0].narration_end - 20.0) < 0.1

    # b2: 30 / 40 = 75% of 80s = 60.0s
    assert abs(timed_blocks[1].speech_dur - 60.0) < 0.1
    assert abs(timed_blocks[1].narration_start - 20.0) < 0.1
    assert abs(timed_blocks[1].narration_end - 80.0) < 0.1


def test_assign_narration_timing_with_tts_cues():
    """Verifies assign_narration_timing locks exact timestamps when Edge-TTS sentence boundary cues exist."""
    text1 = "First scene explanation text here."
    text2 = "Second scene dramatic climax reveal."
    
    b1 = SceneBlock(movie_start=10.0, movie_end=50.0, narration_text=text1, word_count=len(text1.split()))
    b2 = SceneBlock(movie_start=60.0, movie_end=120.0, narration_text=text2, word_count=len(text2.split()))

    cues = [
        {"start": 0.0, "end": 3.8, "text": text1},
        {"start": 3.8, "end": 9.5, "text": text2}
    ]

    timed_blocks = ScriptEngine.assign_narration_timing([b1, b2], total_speech_dur=9.5, cues=cues)
    assert len(timed_blocks) == 2
    assert abs(timed_blocks[0].narration_start - 0.0) < 0.05
    assert abs(timed_blocks[0].narration_end - 3.8) < 0.05
    assert abs(timed_blocks[0].speech_dur - 3.8) < 0.05

    assert abs(timed_blocks[1].narration_start - 3.8) < 0.05
    assert abs(timed_blocks[1].narration_end - 9.5) < 0.05
    assert abs(timed_blocks[1].speech_dur - 5.7) < 0.05


def test_build_chronological_scene_map_proportional_to_blocks():
    """Verifies build_chronological_scene_map allocates micro-clips proportionally to block duration."""
    # Scene 1: 15 seconds speech -> should get ~4 clips
    # Scene 2: 60 seconds speech -> should get ~16 clips
    b1 = SceneBlock(
        movie_start=100.0, movie_end=300.0,
        narration_text="Scene 1", word_count=35,
        speech_dur=15.0, narration_start=0.0, narration_end=15.0
    )
    b2 = SceneBlock(
        movie_start=400.0, movie_end=800.0,
        narration_text="Scene 2", word_count=140,
        speech_dur=60.0, narration_start=15.0, narration_end=75.0
    )

    cuts = VideoEngine.build_chronological_scene_map(
        scene_blocks=[b1, b2],
        total_movie_dur=3600.0,
        target_duration=75.0,
        micro_clip_dur=3.8
    )

    assert len(cuts) > 0
    # Total cut duration should closely match target 75s
    total_cuts_dur = sum(e - s for s, e in cuts)
    assert abs(total_cuts_dur - 75.0) <= 2.5, f"Expected ~75s total cuts, got {total_cuts_dur}"

    # Partition cuts belonging to b1 and b2 based on movie start/end ranges
    b1_cuts = [c for c in cuts if 95.0 <= c[0] <= 305.0]
    b2_cuts = [c for c in cuts if 395.0 <= c[0] <= 805.0]

    assert len(b1_cuts) >= 3, f"Expected at least 3 cuts for Scene 1 (15s), got {len(b1_cuts)}"
    assert len(b2_cuts) >= 12, f"Expected at least 12 cuts for Scene 2 (60s), got {len(b2_cuts)}"
    assert len(b2_cuts) > len(b1_cuts) * 2.5, "Scene 2 (60s) must have significantly more clips than Scene 1 (15s)"

    # Strict containment check: no clips escape the scene's designated movie window
    for s, e in b1_cuts:
        assert s >= 100.0 and e <= 300.0, f"b1 cut ({s}, {e}) escaped [100.0, 300.0]"
    for s, e in b2_cuts:
        assert s >= 400.0 and e <= 800.0, f"b2 cut ({s}, {e}) escaped [400.0, 800.0]"


def test_build_chronological_scene_map_short_window_ping_pong():
    """Verifies that when a scene has a short movie window but long narration, clips remain strictly inside."""
    # 10s movie window (100-110s), but 30s narration
    b1 = SceneBlock(
        movie_start=100.0, movie_end=110.0,
        narration_text="Scene with short footage window", word_count=70,
        speech_dur=30.0, narration_start=0.0, narration_end=30.0
    )

    cuts = VideoEngine.build_chronological_scene_map(
        scene_blocks=[b1],
        total_movie_dur=3600.0,
        target_duration=30.0,
        micro_clip_dur=3.5
    )

    assert len(cuts) >= 6, f"Expected at least 6 micro-clips for 30s narration, got {len(cuts)}"
    for s, e in cuts:
        assert s >= 99.9 and e <= 110.1, f"Cut ({s}, {e}) escaped narrow window [100, 110]"
