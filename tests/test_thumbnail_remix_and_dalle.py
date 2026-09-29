import os
from PIL import Image
import pytest
from unittest.mock import patch, MagicMock

from app.services.thumbnail_engine import ThumbnailEngine
from app.core.config import THUMBNAILS_DIR


def test_generate_viral_thumbnails_with_dalle_poster(tmp_path):
    # Create a mock base image
    fake_ai_poster = tmp_path / "mock_dalle_poster.jpg"
    im = Image.new("RGB", (1280, 720), color=(10, 10, 30))
    im.save(str(fake_ai_poster))

    with patch("app.services.openai_client.generate_ai_image_with_dalle", return_value=str(fake_ai_poster)):
        with patch("app.services.thumbnail_engine.ThumbnailEngine.extract_candidate_frames", return_value=[]):
            results = ThumbnailEngine.generate_3_thumbnail_options(
                video_path="dummy.mp4",
                movie_title="Nashtar Episode 01",
                plot_summary="Danish Taimoor dramatic confrontation",
                lang="ur",
                job_id="test_dalle_01",
                ai_image_path=str(fake_ai_poster)
            )

            assert len(results) == 3
            # Variation 1 must use the AI cinema poster
            assert results[0]["badge"] == "🔥 AI CINEMA POSTER"
            assert os.path.exists(str(THUMBNAILS_DIR / results[0]["filename"]))


def test_generate_viral_thumbnails_with_youtube_remix(tmp_path):
    # Mock YouTube high-res thumbnail
    fake_yt_thumb = tmp_path / "mock_yt_thumb.jpg"
    im = Image.new("RGB", (1280, 720), color=(40, 20, 10))
    im.save(str(fake_yt_thumb))

    with patch("app.services.thumbnail_engine.ThumbnailEngine.fetch_youtube_viral_thumbnail", return_value=str(fake_yt_thumb)):
        with patch("app.services.thumbnail_engine.ThumbnailEngine.extract_candidate_frames", return_value=[]):
            results = ThumbnailEngine.generate_viral_thumbnails(
                video_path="dummy.mp4",
                movie_title="Nashtar Episode 01",
                plot_summary="Dramatic Pakistani drama",
                lang="ur",
                job_id="test_yt_remix_01",
                youtube_url="https://youtu.be/3MmTsA04Fq8"
            )

            assert len(results) == 3
            badges = [r["badge"] for r in results]
            assert "🔥 OFFICIAL POSTER REMIX" in badges or "🔥 AI CINEMA POSTER" in badges
