import os
import pytest
from unittest.mock import patch, MagicMock
from app.services.agent_swarm import AgentSwarmEngine
from app.services.video_engine import VideoEngine


def test_validate_storyboard_success():
    """Verify that a well-spaced chronological storyboard passes validation."""
    scene_ranges = [
        (0.0, 30.0),
        (60.0, 90.0),
        (120.0, 150.0),
        (200.0, 240.0),
        (300.0, 340.0),
    ]
    # Total movie duration is 360 seconds. Span is (340 - 0) / 360 = 94% > 35%.
    is_valid, reason = AgentSwarmEngine.validate_storyboard(scene_ranges, total_movie_dur=360.0)
    assert is_valid is True
    assert "Valid" in reason


def test_validate_storyboard_insufficient_anchors():
    """Verify that a storyboard with fewer than min_anchors is rejected."""
    scene_ranges = [
        (0.0, 20.0),
        (40.0, 60.0),
    ]
    is_valid, reason = AgentSwarmEngine.validate_storyboard(scene_ranges, total_movie_dur=300.0, min_anchors=4)
    assert is_valid is False
    assert "Too few scene anchors" in reason


def test_validate_storyboard_clustered_timeline():
    """Verify that a storyboard where scenes are clustered in only the beginning is rejected."""
    # Scenes only cover the first 45 seconds of a 10-minute (600s) movie
    scene_ranges = [
        (0.0, 10.0),
        (12.0, 22.0),
        (25.0, 35.0),
        (38.0, 45.0),
    ]
    is_valid, reason = AgentSwarmEngine.validate_storyboard(scene_ranges, total_movie_dur=600.0, min_span_pct=0.35)
    assert is_valid is False
    assert "too clustered" in reason


def test_ensure_footage_integrity_sections_sufficient(tmp_path):
    """Verify that when partial sections have sufficient duration and anchors, it returns sections_raw."""
    sections_file = tmp_path / "job1_sections_raw.mp4"
    sections_file.write_bytes(b"dummy video")

    # 6 chronological ranges covering 210s
    scene_ranges = [
        (0.0, 35.0), (40.0, 75.0), (80.0, 115.0),
        (120.0, 155.0), (160.0, 195.0), (200.0, 235.0)
    ]
    speech_dur = 120.0  # 85% is 102s, mock returns 200s

    with patch("app.services.video_engine.VideoEngine.download_youtube_sections", return_value=True), \
         patch("app.services.video_engine.VideoEngine.get_duration", return_value=200.0):
        
        result_path = VideoEngine.ensure_footage_integrity(
            url="https://youtube.com/watch?v=mock",
            job_id="job1",
            speech_dur=speech_dur,
            temp_dir=str(tmp_path),
            resolution="720p",
            scene_ranges=scene_ranges
        )
        assert result_path == str(sections_file)


def test_ensure_footage_integrity_fallback_to_full_raw(tmp_path):
    """Verify that when sections duration is deficient, it downloads and validates full_raw."""
    sections_file = tmp_path / "job2_sections_raw.mp4"
    sections_file.write_bytes(b"short partial")
    full_raw_file = tmp_path / "job2_full_raw.mp4"
    full_raw_file.write_bytes(b"full video content")

    scene_ranges = [(0.0, 20.0)]
    speech_dur = 120.0

    # Test 1: When selective download succeeds, it returns sections_raw without calling download_youtube_video
    with patch("app.services.video_engine.VideoEngine.download_youtube_sections", return_value=True), \
         patch("app.services.video_engine.VideoEngine.download_youtube_video") as mock_full_dl, \
         patch("app.services.video_engine.VideoEngine.get_duration", return_value=120.0):
        
        result_path = VideoEngine.ensure_footage_integrity(
            url="https://youtube.com/watch?v=mock",
            job_id="job2",
            speech_dur=speech_dur,
            temp_dir=str(tmp_path),
            resolution="720p",
            scene_ranges=scene_ranges
        )
        assert result_path == str(sections_file)
        # CRITICAL INVARIANT: download_youtube_video must NEVER be called
        assert not mock_full_dl.called


def test_ensure_footage_integrity_never_downloads_full_movie_on_failure(tmp_path):
    """
    CRITICAL REGRESSION TEST (Section 41):
    Verifies that if selective extraction fails, ensure_footage_integrity NEVER triggers
    a full-movie download and fails loudly with SourceIntegrityError.
    """
    scene_ranges = [(0.0, 15.0)]
    speech_dur = 180.0

    with patch("app.services.video_engine.VideoEngine.download_youtube_sections", return_value=False), \
         patch("app.services.video_engine.VideoEngine.download_youtube_video") as mock_full_dl:
        
        with pytest.raises(RuntimeError) as excinfo:
            VideoEngine.ensure_footage_integrity(
                url="https://youtube.com/watch?v=mock",
                job_id="job3",
                speech_dur=speech_dur,
                temp_dir=str(tmp_path),
                resolution="720p",
                scene_ranges=scene_ranges
            )
        assert "SourceIntegrityError" in str(excinfo.value)
        assert "Full movie download is permanently disabled" in str(excinfo.value)
        assert not mock_full_dl.called



def test_detect_camera_cuts_in_window(tmp_path):
    """Verify that detect_camera_cuts_in_window parses lavfi.scd.time from FFmpeg output."""
    dummy_video = tmp_path / "dummy.mp4"
    dummy_video.write_bytes(b"dummy")

    mock_stderr = (
        "[Parsed_scdet_0 @ 0000021b] lavfi.scd.time: 2.150, lavfi.scd.score: 18.5\n"
        "[Parsed_scdet_0 @ 0000021b] lavfi.scd.time: 5.400, lavfi.scd.score: 22.1\n"
        "[Parsed_scdet_0 @ 0000021b] lavfi.scd.time: 8.900, lavfi.scd.score: 14.3\n"
    )

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = ""
    mock_proc.stderr = mock_stderr

    with patch("subprocess.run", return_value=mock_proc):
        shots = VideoEngine.detect_camera_cuts_in_window(str(dummy_video), start=0.0, end=10.0, threshold=10.0)
        assert len(shots) >= 2
        # Shots should partition the interval
        assert shots[0][0] == 0.0
        assert shots[-1][1] == 10.0


def test_build_chronological_scene_map_clamping():
    """Verify build_chronological_scene_map clamps cuts strictly inside [s_sec, e_sec]."""
    scene_ranges = [
        (10.0, 40.0),
        (50.0, 90.0),
        (100.0, 150.0),
        (160.0, 220.0),
    ]
    # For a target duration of 40s from a 300s movie
    segments = VideoEngine.build_chronological_scene_map(
        scene_ranges=scene_ranges,
        total_movie_dur=300.0,
        target_duration=40.0,
        micro_clip_dur=3.5
    )

    assert len(segments) > 0
    total_alloc = sum(e - s for s, e in segments)
    assert total_alloc >= 38.0

    # Ensure every micro-clip stays strictly within one of the valid scene ranges
    for s_sec, e_sec in segments:
        in_any_range = any(r_s <= s_sec and e_sec <= r_e + 0.1 for r_s, r_e in scene_ranges)
        assert in_any_range, f"Segment ({s_sec}, {e_sec}) escaped scene boundaries!"
