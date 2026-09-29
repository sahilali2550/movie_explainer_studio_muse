import os
import pytest
from PIL import Image
from app.services.thumbnail_engine import ThumbnailEngine


def test_multi_style_thumbnail_layouts(tmp_path):
    # Create a dummy solid image as candidate frame
    dummy_frame = tmp_path / "cand_0.jpg"
    im = Image.new("RGB", (1280, 720), color=(40, 60, 100))
    im.save(dummy_frame)

    dummy_frame2 = tmp_path / "cand_1.jpg"
    im2 = Image.new("RGB", (1280, 720), color=(120, 30, 40))
    im2.save(dummy_frame2)

    # 1. Test Climax Face Zoom layout
    zoom_thumb = ThumbnailEngine.apply_face_zoom_style(im.copy())
    assert zoom_thumb.size == (1920, 1080)

    # 2. Test Split-Screen Confrontation layout
    split_thumb = ThumbnailEngine.apply_split_screen_style(im.copy(), im2.copy())
    assert split_thumb.size == (1920, 1080)

    # 3. Test Cinema Poster layout
    poster_thumb = ThumbnailEngine.apply_cinema_poster_style(im.copy())
    assert poster_thumb.size == (1920, 1080)


def test_fetch_youtube_viral_thumbnail(tmp_path):
    out_path = str(tmp_path / "yt_thumb.jpg")
    # Valid YouTube URL
    url = "https://www.youtube.com/watch?v=vGCQPi43Oo0"
    res = ThumbnailEngine.fetch_youtube_viral_thumbnail(url, out_path)
    # Even if offline, function should fail gracefully returning None or path if fetched
    assert res is None or os.path.exists(res)
