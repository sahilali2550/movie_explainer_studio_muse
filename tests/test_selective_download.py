import pytest
import os
from unittest.mock import patch, MagicMock
from app.services.video_engine import VideoEngine

def test_build_yt_dlp_section_args_hours_support():
    """
    Verifies that timestamps over 1 hour (3600s) are formatted with HH:MM:SS
    for yt-dlp --download-sections.
    """
    ranges = [
        (120.0, 125.0),         # 02:00 - 02:05
        (4930.0, 4935.0),       # 01:22:10 - 01:22:15 (82 minutes in)
        (5140.0, 5145.0)        # 01:25:40 - 01:25:45 (85 minutes in)
    ]
    args = VideoEngine.build_yt_dlp_section_args(ranges)
    assert "--download-sections" in args
    # Check that the hour-formatted ranges are present
    assert "*01:22:10-01:22:15" in args
    assert "*01:25:40-01:25:45" in args
    assert "*02:00-02:05" in args

def test_ensure_footage_integrity_uses_sections_for_long_movie(tmp_path):
    """
    Verifies that for an 86-minute movie with scenes spanning up to 5100s,
    ensure_footage_integrity ALWAYS calls download_youtube_sections and NEVER
    calls download_youtube_video.
    """
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    job_id = "test_job_long_movie"
    speech_dur = 300.0  # 5 minutes narration

    # Scene ranges span across an 86-minute movie
    scene_ranges = [
        (60.0, 65.0),
        (1200.0, 1205.0),
        (2500.0, 2505.0),
        (3800.0, 3805.0),
        (4500.0, 4505.0),
        (5100.0, 5105.0)
    ]

    temp_dir = str(tmp_path)
    sections_out = os.path.join(temp_dir, f"{job_id}_sections_raw.mp4")

    # Mock download_youtube_sections to succeed and create a dummy file
    def mock_dl_sections(u, r, out, t, j):
        with open(out, "wb") as f:
            f.write(b"dummy_mp4_bytes" * 500)
        return True

    with patch.object(VideoEngine, "download_youtube_sections", side_effect=mock_dl_sections) as mock_sec:
        with patch.object(VideoEngine, "download_youtube_video") as mock_full:
            with patch.object(VideoEngine, "get_duration", return_value=310.0):
                res = VideoEngine.ensure_footage_integrity(
                    url=url,
                    job_id=job_id,
                    speech_dur=speech_dur,
                    temp_dir=temp_dir,
                    scene_ranges=scene_ranges
                )
                assert res == sections_out
                # Must have called download_youtube_sections
                mock_sec.assert_called_once()
                # Must NEVER have called download_youtube_video (full movie download forbidden)
                mock_full.assert_not_called()
