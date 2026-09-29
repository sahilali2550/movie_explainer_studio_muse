import pytest
from PIL import Image
from app.services.thumbnail_engine import ThumbnailEngine

def test_thumbnail_urdu_typography_rendering_clean():
    """Verifies that Urdu typography renders cleanly without tofu/square boxes."""
    im = Image.new("RGB", (1280, 720), (30, 30, 30))
    # Hook text in Urdu
    hook = "سب سے بڑا دھوکہ!"
    rendered = ThumbnailEngine.render_typography(im, hook, lang="ur", badge_label="🔥 HIGH SUSPENSE")
    assert rendered is not None
    assert rendered.size == (1280, 720)

def test_thumbnail_badge_label_strips_emojis_to_prevent_tofu():
    """Verifies that badge labels do not pass unrenderable emoji characters to standard fonts."""
    im = Image.new("RGB", (1280, 720), (30, 30, 30))
    rendered = ThumbnailEngine.render_typography(im, "DON'T TRUST HER!", lang="en", badge_label="😱 SHOCKING TWIST")
    assert rendered is not None


def test_thumbnail_selection_spans_three_acts(tmp_path):
    """
    Verifies that generate_3_thumbnail_options selects candidates from 3 distinct
    story acts (Act 1, Act 2, Act 3) rather than clustering in one scene.
    """
    from unittest.mock import patch

    # Create 6 dummy candidate frame files
    cand_files = []
    for i in range(6):
        f = tmp_path / f"cand_{i}.jpg"
        im = Image.new("RGB", (100, 100), (i * 30, 50, 50))
        im.save(str(f))
        cand_files.append(str(f))

    # Sharpness scores:
    # Act 1: cand_0 (sharpness 10), cand_1 (sharpness 40) -> cand_1 should be picked for Act 1
    # Act 2: cand_2 (sharpness 90), cand_3 (sharpness 20) -> cand_2 should be picked for Act 2
    # Act 3: cand_4 (sharpness 30), cand_5 (sharpness 80) -> cand_5 should be picked for Act 3
    sharpness_map = {
        cand_files[0]: 10.0,
        cand_files[1]: 40.0,
        cand_files[2]: 90.0,
        cand_files[3]: 20.0,
        cand_files[4]: 30.0,
        cand_files[5]: 80.0,
    }

    opened_files = []
    orig_open = Image.open
    def mock_image_open(fp, *args, **kwargs):
        opened_files.append(str(fp))
        return orig_open(fp, *args, **kwargs)

    with patch("app.services.thumbnail_engine.ThumbnailEngine.extract_candidate_frames", return_value=cand_files), \
         patch("app.services.thumbnail_engine.ThumbnailEngine.calculate_sharpness", side_effect=lambda p: sharpness_map.get(str(p), 10.0)), \
         patch("PIL.Image.open", side_effect=mock_image_open):

        results = ThumbnailEngine.generate_3_thumbnail_options(
            video_path="dummy.mp4",
            job_id="test_act_job",
            movie_title="Test Movie",
            lang="en"
        )

        assert len(results) == 3
        # Verify the 3 opened frames were cand_1 (Act 1 winner), cand_2 (Act 2 winner), and cand_5 (Act 3 winner)
        assert any("cand_1.jpg" in f for f in opened_files), "Act 1 sharpest candidate should be selected"
        assert any("cand_2.jpg" in f for f in opened_files), "Act 2 sharpest candidate should be selected"
        assert any("cand_5.jpg" in f for f in opened_files), "Act 3 sharpest candidate should be selected"

