import pytest
from app.services.video_engine import VideoEngine

SAMPLE_VTT = """WEBVTT

1
00:00:15.500 --> 00:00:18.200
In a quiet town, an experiment went wrong.

2
00:05:30.000 --> 00:05:34.000
Dr. Adams discovers the containment breach.

3
00:45:10.000 --> 00:45:14.500
The creature escapes into the city sewers.

4
01:25:00.000 --> 01:25:05.000
Final standoff at the hydroelectric dam.
"""

SAMPLE_SRT = """1
00:01:20,000 --> 00:01:24,500
The detective arrives at the scene.

2
00:12:45,000 --> 00:12:48,000
A hidden diary is found behind the bookshelf.

3
01:10:15,000 --> 01:10:20,000
The true suspect confesses under pressure.
"""

def test_parse_timed_subtitles_vtt():
    cues = VideoEngine.parse_timed_subtitles(SAMPLE_VTT)
    assert len(cues) == 4
    assert round(cues[0]["start"], 1) == 15.5
    assert round(cues[0]["end"], 1) == 18.2
    assert "experiment went wrong" in cues[0]["text"]
    assert cues[3]["start"] == 85 * 60  # 01:25:00 = 5100s

def test_parse_timed_subtitles_srt():
    cues = VideoEngine.parse_timed_subtitles(SAMPLE_SRT)
    assert len(cues) == 3
    assert cues[0]["start"] == 80.0
    assert "detective arrives" in cues[0]["text"]
    assert cues[2]["start"] == 70 * 60 + 15  # 4215s

def test_build_timeline_summary():
    cues = VideoEngine.parse_timed_subtitles(SAMPLE_VTT)
    summary = VideoEngine.build_timeline_summary(cues, max_events=4)
    assert "[00:15]" in summary
    assert "[05:30]" in summary
    assert "[45:10]" in summary
    assert "hydroelectric dam" in summary

def test_build_chronological_scene_map_proportional_fallback():
    # Total movie: 7200 seconds (2 hours)
    # Target explainer: 180 seconds (3 mins)
    total_movie_dur = 7200.0
    target_dur = 180.0

    # No scene ranges provided or all clustered in opening 30 seconds
    clustered_ranges = [(0.0, 15.0), (10.0, 30.0)]
    cuts = VideoEngine.build_chronological_scene_map(
        scene_ranges=clustered_ranges,
        total_movie_dur=total_movie_dur,
        target_duration=target_dur,
        micro_clip_dur=3.5
    )

    assert len(cuts) >= 30  # 180s / ~3.5s = ~51 clips
    # Must NOT be clustered at the start:
    first_clip_start = cuts[0][0]
    mid_clip_start = cuts[len(cuts) // 2][0]
    last_clip_start = cuts[-1][0]

    # First clip should start after intro/logos (e.g. >= 1% of movie = 72s)
    assert first_clip_start >= 60.0
    # Middle clip should be around 25% - 75% of movie (e.g. > 1800s)
    assert mid_clip_start >= 1800.0
    # Last clip should be towards the climax/end (e.g. > 5000s, but before end credits at 95% = 6840s)
    assert last_clip_start >= 5000.0
    assert last_clip_start <= 7000.0

    # Total duration of cuts must approximately equal target_dur
    total_cuts_dur = sum(e - s for s, e in cuts)
    assert abs(total_cuts_dur - target_dur) <= 5.0

def test_build_chronological_scene_map_from_valid_ranges():
    total_movie_dur = 3600.0
    target_dur = 60.0
    valid_ranges = [
        (300.0, 600.0),    # Scene 1: 5m - 10m
        (1200.0, 1500.0),  # Scene 2: 20m - 25m
        (2700.0, 3000.0)   # Scene 3: 45m - 50m
    ]

    cuts = VideoEngine.build_chronological_scene_map(
        scene_ranges=valid_ranges,
        total_movie_dur=total_movie_dur,
        target_duration=target_dur,
        micro_clip_dur=3.5
    )

    assert len(cuts) >= 12
    # Ensure all cuts are strictly chronological
    for i in range(len(cuts) - 1):
        assert cuts[i][0] <= cuts[i+1][0]

    # Ensure cuts come from across the scenes
    starts = [c[0] for c in cuts]
    assert any(300.0 <= s <= 600.0 for s in starts)
    assert any(1200.0 <= s <= 1500.0 for s in starts)
    assert any(2700.0 <= s <= 3000.0 for s in starts)
