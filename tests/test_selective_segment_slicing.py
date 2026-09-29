import pytest
from unittest.mock import patch, MagicMock
from app.services.video_engine import VideoEngine


def test_build_yt_dlp_section_args():
    """
    Verifies that build_yt_dlp_section_args converts numeric seconds ranges
    into proper yt-dlp --download-sections arguments formatted as *MM:SS-MM:SS.
    """
    ranges = [(18.0, 53.0), (75.0, 192.0)]
    args = VideoEngine.build_yt_dlp_section_args(ranges)

    expected = [
        "--download-sections", "*00:18-00:53",
        "--download-sections", "*01:15-03:12"
    ]
    assert args == expected


def test_build_yt_dlp_section_args_empty_or_invalid():
    """
    Verifies that empty or invalid ranges return an empty argument list.
    """
    assert VideoEngine.build_yt_dlp_section_args([]) == []
    assert VideoEngine.build_yt_dlp_section_args([(50.0, 40.0)]) == []


def test_get_yt_dlp_download_cmd_includes_concurrency_and_720p():
    """
    Verifies that full video download commands include multi-thread concurrency (-N 5)
    and 720p resolution default to eliminate YouTube throttling.
    """
    cmd = VideoEngine.get_yt_dlp_download_cmd(
        url="https://youtu.be/dummy123",
        output_path="/tmp/video.mp4",
        resolution="720p"
    )

    assert "-N" in cmd
    assert "5" in cmd
    assert any("height<=720" in arg for arg in cmd)


def test_download_youtube_sections_execution():
    """
    Verifies that download_youtube_sections runs yt-dlp with section arguments
    and returns True when slices are generated.
    """
    ranges = [(10.0, 20.0), (30.0, 40.0)]
    with patch("subprocess.run") as mock_run, \
         patch("os.path.exists", return_value=True), \
         patch("os.listdir", return_value=["test_job_sec_0.mp4"]), \
         patch("shutil.copyfile") as mock_copy, \
         patch("os.path.getsize", return_value=50000):

        mock_run.return_value = MagicMock(returncode=0)

        ok = VideoEngine.download_youtube_sections(
            url="https://youtu.be/dummy123",
            scene_ranges=ranges,
            output_video="/tmp/slice.mp4",
            temp_dir="/tmp",
            job_id="test_job"
        )

        assert ok is True
        assert mock_run.called
        assert any("--download-sections" in call_args[0][0] for call_args in mock_run.call_args_list)

