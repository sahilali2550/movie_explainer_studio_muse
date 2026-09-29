import pytest
from app.services.video_engine import VideoEngine


def test_parse_timed_subtitles_and_timeline_extraction():
    """
    Verifies that parse_timed_subtitles extracts structured dialogue cues
    with millisecond accuracy.
    """
    vtt_sample = """WEBVTT

1
00:01:10.500 --> 00:01:14.200
Sarah: What are you doing in my house?

2
00:01:15.000 --> 00:01:19.800
David: I came here to warn you before they arrive.

3
00:15:30.100 --> 00:15:35.000
Detective: We found the hidden weapon under the floorboards.
"""
    cues = VideoEngine.parse_timed_subtitles(vtt_sample)
    assert len(cues) == 3
    assert cues[0]["start"] == 70.5
    assert cues[0]["end"] == 74.2
    assert "What are you doing" in cues[0]["text"]
    assert cues[1]["start"] == 75.0
    assert cues[2]["start"] == 930.1


def test_build_dialogue_anchored_scene_map_with_intra_scene_slicing():
    """
    Verifies that when given scene ranges with varying paragraph durations,
    the engine slices micro-clips strictly within each scene's bounds,
    matching total target duration without visual looping or out-of-bounds jumps.
    """
    # Movie is 120 minutes (7200 seconds)
    total_movie_dur = 7200.0
    # 4 distinct story beats across the movie
    scene_ranges = [
        (120.0, 180.0),   # Beat 1: Minute 2 to 3
        (900.0, 960.0),   # Beat 2: Minute 15 to 16
        (2400.0, 2460.0), # Beat 3: Minute 40 to 41
        (5400.0, 5460.0)  # Beat 4: Minute 90 to 91
    ]
    target_duration = 40.0  # 40 seconds explainer (10s per beat)

    cuts = VideoEngine.build_chronological_scene_map(
        scene_ranges=scene_ranges,
        total_movie_dur=total_movie_dur,
        target_duration=target_duration,
        micro_clip_dur=3.5
    )

    assert len(cuts) >= 4
    total_cut_duration = sum(e - s for s, e in cuts)
    assert abs(total_cut_duration - target_duration) < 2.0

    # Verify that all cuts originate from inside one of the 4 scene ranges
    for s, e in cuts:
        assert s >= 0.0 and e <= total_movie_dur
        # Each cut must fall near or within the scene boundaries
        matches_any_scene = any(
            (r_s - 1.0) <= s and e <= (r_e + 1.0)
            for r_s, r_e in scene_ranges
        )
        assert matches_any_scene, f"Cut ({s}, {e}) was outside scene boundaries!"
