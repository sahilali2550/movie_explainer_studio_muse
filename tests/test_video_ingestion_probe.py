import json
import pytest
from unittest.mock import patch, MagicMock
from app.services.video_engine import VideoEngine

def test_probe_media_file_not_found():
    """probe_media must raise FileNotFoundError if source video does not exist."""
    with pytest.raises(FileNotFoundError, match="Source video not found"):
        VideoEngine.probe_media("non_existent_file_xyz123.mp4")

def test_probe_media_valid_video_horizontal(monkeypatch, tmp_path):
    """probe_media should correctly parse metadata for a horizontal video with audio."""
    fake_video = tmp_path / "sample.mp4"
    fake_video.write_text("dummy video content")

    mock_ffprobe_output = {
        "format": {
            "duration": "125.500000",
            "size": "10485760",
            "bit_rate": "668000"
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "60/2",
                "duration": "125.500000"
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac"
            }
        ]
    }

    class MockProcess:
        returncode = 0
        stdout = json.dumps(mock_ffprobe_output)
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockProcess())

    meta = VideoEngine.probe_media(str(fake_video))

    assert meta["file_path"] == str(fake_video)
    assert meta["duration"] == 125.5
    assert meta["width"] == 1920
    assert meta["height"] == 1080
    assert meta["fps"] == 30.0
    assert meta["aspect_ratio"] == "horizontal"
    assert meta["has_audio"] is True
    assert meta["video_codec"] == "h264"
    assert meta["audio_codec"] == "aac"

def test_probe_media_vertical_no_audio(monkeypatch, tmp_path):
    """probe_media should detect vertical aspect ratio and audio absence."""
    fake_video = tmp_path / "vertical.mp4"
    fake_video.write_text("dummy video content")

    mock_ffprobe_output = {
        "format": {
            "duration": "45.0"
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 1080,
                "height": 1920,
                "r_frame_rate": "24/1",
                "duration": "45.0"
            }
        ]
    }

    class MockProcess:
        returncode = 0
        stdout = json.dumps(mock_ffprobe_output)
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockProcess())

    meta = VideoEngine.probe_media(str(fake_video))

    assert meta["duration"] == 45.0
    assert meta["width"] == 1080
    assert meta["height"] == 1920
    assert meta["fps"] == 24.0
    assert meta["aspect_ratio"] == "vertical"
    assert meta["has_audio"] is False
    assert meta["video_codec"] == "hevc"
    assert meta["audio_codec"] == "none"

def test_probe_media_stream_duration_fallback(monkeypatch, tmp_path):
    """If format duration is N/A or missing, stream duration should be used."""
    fake_video = tmp_path / "stream_dur.mp4"
    fake_video.write_text("dummy video content")

    mock_ffprobe_output = {
        "format": {
            "duration": "N/A"
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1280,
                "height": 720,
                "r_frame_rate": "25/1",
                "duration": "88.2"
            }
        ]
    }

    class MockProcess:
        returncode = 0
        stdout = json.dumps(mock_ffprobe_output)
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockProcess())

    meta = VideoEngine.probe_media(str(fake_video))
    assert meta["duration"] == 88.2

def test_probe_media_corrupt_raises_runtime_error(monkeypatch, tmp_path):
    """If duration is invalid or 0, RuntimeError should be raised."""
    fake_video = tmp_path / "corrupt.mp4"
    fake_video.write_text("corrupt content")

    mock_ffprobe_output = {
        "format": {
            "duration": "0.0"
        },
        "streams": []
    }

    class MockProcess:
        returncode = 0
        stdout = json.dumps(mock_ffprobe_output)
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockProcess())

    with pytest.raises(RuntimeError, match="MediaProbeError"):
        VideoEngine.probe_media(str(fake_video))

def test_get_duration_relies_on_probe_media(monkeypatch, tmp_path):
    """get_duration must use probe_media duration."""
    fake_video = tmp_path / "valid.mp4"
    fake_video.write_text("dummy")

    with patch.object(VideoEngine, "probe_media", return_value={"duration": 99.4}):
        dur = VideoEngine.get_duration(str(fake_video))
        assert dur == 99.4

def test_get_duration_raises_runtime_error_on_failure(monkeypatch, tmp_path):
    """get_duration must raise RuntimeError instead of returning 60.0 on failure."""
    fake_video = tmp_path / "failed.mp4"
    fake_video.write_text("dummy")

    with patch.object(VideoEngine, "probe_media", side_effect=RuntimeError("probe failed")):
        class MockProcess:
            returncode = 1
            stdout = ""
            stderr = "probe failure"

        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockProcess())

        with pytest.raises(RuntimeError, match="Unable to determine duration for source"):
            VideoEngine.get_duration(str(fake_video))
