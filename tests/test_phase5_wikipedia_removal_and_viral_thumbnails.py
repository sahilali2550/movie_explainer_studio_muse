import os
import pytest
from PIL import Image
from unittest.mock import patch, MagicMock

from app.services.thumbnail_engine import ThumbnailEngine
from app.services.script_engine import ScriptEngine
from app.api.v1 import explainer

def test_wikipedia_decommissioned_from_script_engine_and_api():
    """Verify that Wikipedia methods and endpoints have been completely removed."""
    assert not hasattr(ScriptEngine, "fetch_wikipedia_plot")
    route_paths = [route.path for route in explainer.router.routes]
    assert "/fetch-wikipedia-plot" not in route_paths

def test_thumbnail_language_adaptive_viral_hooks():
    """Verify that viral hooks automatically adapt to Urdu, Hindi, Spanish, and English."""
    ur_hooks = ThumbnailEngine.get_default_viral_hooks("ur")
    assert any("یہ کیا ہو گیا" in h or "سچ" in h for h in ur_hooks)

    hi_hooks = ThumbnailEngine.get_default_viral_hooks("hi")
    assert any("खौफनाक" in h or "सच" in h for h in hi_hooks)

    es_hooks = ThumbnailEngine.get_default_viral_hooks("es")
    assert any("GIRO" in h or "VERDAD" in h for h in es_hooks)

    en_hooks = ThumbnailEngine.get_default_viral_hooks("en")
    assert any("TWIST" in h or "TRUTH" in h for h in en_hooks)

def test_thumbnail_high_contrast_container_rendering():
    """Verify typography renders with pill container backing plate without crashing."""
    im = Image.new("RGB", (1920, 1080), (120, 20, 20))
    rendered = ThumbnailEngine.render_typography(
        im,
        "خوفناک انکشاف جس نے سب کو ہلا دیا!",
        lang="ur",
        badge_label="🔥 CLIMAX"
    )
    assert rendered is not None
    assert rendered.size == (1920, 1080)

def test_thumbnail_frame_quality_penalizes_dark_screens(tmp_path):
    """Verify calculate_sharpness scores vibrant frames higher than pitch black frames."""
    # Pitch black frame (mean lum = 0)
    dark_path = tmp_path / "dark_frame.jpg"
    im_dark = Image.new("RGB", (320, 180), (0, 0, 0))
    im_dark.save(str(dark_path))

    # Vibrant frame with sharp contrasting colored shapes
    vibrant_path = tmp_path / "vibrant_frame.jpg"
    im_vib = Image.new("RGB", (320, 180), (180, 50, 40))
    from PIL import ImageDraw
    d = ImageDraw.Draw(im_vib)
    d.rectangle([(40, 40), (280, 140)], fill=(255, 230, 0))
    d.line([(0, 0), (320, 180)], fill=(0, 0, 255), width=6)
    im_vib.save(str(vibrant_path))

    dark_score = ThumbnailEngine.calculate_sharpness(str(dark_path))
    vib_score = ThumbnailEngine.calculate_sharpness(str(vibrant_path))

    assert vib_score > dark_score
    assert dark_score < 5.0
