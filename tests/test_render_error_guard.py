import os
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import OUTPUTS_DIR

client = TestClient(app)


def test_render_video_defines_final_video_path():
    """
    Verifies that render_video explicitly defines final_video_path and passes
    it to VideoEngine.render_final_explainer without UnboundLocalError.
    """
    passed_output_path = []

    def mock_render_final(*args, **kwargs):
        passed_output_path.append(kwargs.get("output_path"))
        p = kwargs.get("output_path")
        if p:
            with open(p, "wb") as f:
                f.write(b"dummy video content 1234567890" * 100)
        return True

    def mock_download_video(url, output_video, **kwargs):
        try:
            with open(output_video, "wb") as f:
                f.write(b"dummy video content 1234567890" * 100)
        except Exception:
            pass
        return True

    def mock_download_sections(url, scene_ranges, output_video, *args, **kwargs):
        try:
            with open(output_video, "wb") as f:
                f.write(b"dummy video content 1234567890" * 100)
        except Exception:
            pass
        return True

    with patch("app.services.video_engine.VideoEngine.extract_youtube_info", return_value={"subtitles_text": "sample dialogue"}), \
         patch("app.services.video_engine.VideoEngine.download_youtube_video", side_effect=mock_download_video), \
         patch("app.services.video_engine.VideoEngine.download_youtube_sections", side_effect=mock_download_sections), \
         patch("app.services.video_engine.VideoEngine.get_duration", return_value=60.0), \
         patch("app.services.voice_engine.VoiceEngine.synthesize_speech", return_value=True), \
         patch("app.services.voice_engine.VoiceEngine.get_audio_duration", return_value=10.0), \
         patch("app.services.video_engine.VideoEngine.slice_and_assemble_scenes", return_value="mock_slice.mp4"), \
         patch("app.services.audio_mixer.AudioMixer.mix_soundtrack", return_value=None), \
         patch("app.services.thumbnail_engine.ThumbnailEngine.generate_3_thumbnail_options", return_value=[]), \
         patch("app.services.metadata_engine.MetadataEngine.generate_viral_metadata", return_value={}), \
         patch("app.services.video_engine.VideoEngine.render_final_explainer", side_effect=mock_render_final):

        orig_exists = os.path.exists
        with patch("os.path.exists", side_effect=lambda p: True if "mock" in str(p) or "speech" in str(p) or "explainer_" in str(p) or "uploads" in str(p) or "raw" in str(p) else orig_exists(p)):
            res = client.post(
                "/api/v1/explainer/render-video",
                data={
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "script_text": "This is a test narration for the video.",
                    "language": "ur",
                    "voice": "ur-IN-SalmanNeural",
                    "aspect_ratio": "horizontal",
                    "genre": "movie_recap",
                    "audio_mode": "sfx_only",
                    "mood_theme": "suspense"
                }
            )
            assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
            data = res.json()
            assert data["success"] is True
            assert "explainer_" in data["video_filename"]
            assert len(passed_output_path) == 1
            assert passed_output_path[0] is not None
            assert str(OUTPUTS_DIR) in str(passed_output_path[0])


def test_render_video_returns_json_on_unhandled_exception():
    """
    Verifies that unhandled pipeline exceptions return clean JSON (status 500)
    rather than unhandled Starlette plain text, preventing frontend JSON parse errors.
    """
    with patch("app.services.video_engine.VideoEngine.extract_youtube_info", return_value={"subtitles_text": "hello"}), \
         patch("app.services.video_engine.VideoEngine.ensure_footage_integrity", side_effect=RuntimeError("Test crash inside pipeline")):
        res = client.post(
            "/api/v1/explainer/render-video",
            data={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "script_text": "Narration text",
                "language": "en"
            }
        )
        assert res.status_code == 500
        data = res.json()
        assert "detail" in data or "error" in data
