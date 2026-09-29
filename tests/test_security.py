import pytest
from pathlib import Path
from app.services.thumbnail_engine import ThumbnailEngine
from app.services.video_engine import VideoEngine
from app.core.config import THUMBNAILS_DIR


def test_youtube_url_validator_accepts_valid_urls():
    """VideoEngine must validate legitimate YouTube URLs."""
    valid_urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "http://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ"
    ]
    for u in valid_urls:
        assert VideoEngine.is_valid_youtube_url(u) is True, f"Failed for valid URL: {u}"


def test_youtube_url_validator_rejects_malicious_and_ssrf_urls():
    """VideoEngine must reject SSRF, command injection, and non-YouTube URLs."""
    malicious_inputs = [
        "--exec 'calc.exe'",
        "--output /tmp/evil",
        "http://127.0.0.1:8000/api/v1/explainer/config",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:22",
        "file:///etc/passwd",
        "https://evil-phishing-site.com/watch?v=12345",
        "",
        "   "
    ]
    for u in malicious_inputs:
        assert VideoEngine.is_valid_youtube_url(u) is False, f"Did not reject malicious input: {u}"


def test_thumbnail_path_traversal_rejection():
    """re_render_thumbnail must refuse to process path traversal payloads."""
    traversal_filenames = [
        "../../test.jpg",
        "..\\..\\test.jpg",
        "/etc/passwd.jpg",
        "something/../../evil.jpg",
        "valid_name.jpg;rm -rf",
        "valid.png"  # non-jpg
    ]
    for fn in traversal_filenames:
        result = ThumbnailEngine.re_render_thumbnail(
            filename=fn,
            new_hook_text="Test Hook",
            lang="en"
        )
        assert result is None, f"Expected None for traversal filename: {fn}"


def test_ffmpeg_drawtext_escaping():
    """escape_ffmpeg_drawtext must escape %, commas, single quotes, and colons."""
    raw_text = "Save 50% on action, drama: it's 'epic'!"
    escaped = VideoEngine.escape_ffmpeg_drawtext(raw_text)

    # % must be escaped for strftime
    assert "%" not in escaped or "\\%" in escaped
    # Commas must be escaped for filtergraph joining
    assert "," not in escaped or "\\," in escaped
    # Colons must be escaped for option separators
    assert ":" not in escaped or "\\:" in escaped
