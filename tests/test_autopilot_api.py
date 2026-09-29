import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

SAMPLE_TRANSCRIPT = """
00:00 The vault in Geneva was breached at midnight.
00:20 Detective Ray arrived with forensic officers.
01:15 A suspicious fingerprint led to a cyber criminal known as Cipher.
02:00 The chase across Zurich ended at the airport hangar.
"""

def test_auto_detect_context_endpoint():
    """Verify /api/v1/explainer/auto-detect-context returns detected title, genre, persona, mood."""
    response = client.post(
        "/api/v1/explainer/auto-detect-context",
        data={
            "transcript_text": SAMPLE_TRANSCRIPT,
            "url": "https://www.youtube.com/watch?v=mock123",
            "title_hint": "The Geneva Vault Heist"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True
    assert "title" in data
    assert "genre" in data
    assert "persona" in data
    assert "mood" in data
    assert "story_beats" in data
    assert len(data["story_beats"]) >= 1

def test_run_autopilot_endpoint_validation():
    """Verify /api/v1/explainer/run-autopilot rejects empty sources gracefully."""
    response = client.post(
        "/api/v1/explainer/run-autopilot",
        data={
            "url": "",
            "transcript_text": "",
            "target_lang": "ur"
        }
    )
    assert response.status_code in [400, 422]

def test_run_autopilot_endpoint_workflow_mock(tmp_path):
    """Verify /api/v1/explainer/run-autopilot coordinates the full agent swarm pipeline."""
    dummy_video = tmp_path / "mock_vid.mp4"
    dummy_video.write_bytes(b"dummy video data")

    dummy_speech = tmp_path / "mock_speech.mp3"
    dummy_speech.write_bytes(b"dummy speech data")

    mock_swarm = {
        "success": True,
        "context": {
            "title": "The Geneva Vault Heist",
            "genre": "true_crime",
            "persona": "documentary",
            "mood": "tense",
            "story_beats": [{"beat": 1, "time_range": "00:00 - 00:30", "summary": "Vault breached"}]
        },
        "script": "[SCENE: 00:00 - 00:30]\n[VOICEOVER]\nIn Geneva, the vault was shattered.\n[SFX: SUB_BOOM]\nNobody saw it coming.",
        "hook_score": {"score": 92, "rating": "Viral Platinum 🔥"},
        "thumbnail_strategy": {
            "climax_timestamp": 120.0,
            "hook_options": ["THE SECRET VAULT", "CAUGHT ON CAMERA", "NEVER BEFORE SEEN"]
        },
        "seo_pack": {
            "viral_titles": ["The Geneva Vault Mystery Explained"],
            "description": "Full story breakdown.",
            "tags": ["heist", "geneva", "recap"],
            "pinned_comment": "Did you suspect Cipher?"
        },
        "narrator_voice": "ur-PK-AsadNeural",
        "speech_velocity": "fast",
        "story_beats": [{"beat": 1, "time_range": "00:00 - 00:30", "summary": "Vault breached"}]
    }

    def mock_download_sections(url, scene_ranges, output_video, temp_dir, job_id):
        with open(output_video, "wb") as f:
            f.write(b"mock video data")
        return True

    def mock_download_video(url, output_video, **kwargs):
        with open(output_video, "wb") as f:
            f.write(b"mock full video data")
        return True

    def mock_slice(*args, **kwargs):
        output_video = kwargs.get("output_video")
        if not output_video:
            output_video = str(tmp_path / "mock_sliced.mp4")
        with open(output_video, "wb") as f:
            f.write(b"mock sliced data")
        return output_video

    def mock_render(video_source, audio_source, output_path, duration, **kwargs):
        with open(output_path, "wb") as f:
            f.write(b"mock rendered video data")
        return True

    import os
    with patch("app.services.agent_swarm.AgentSwarmEngine.run_parallel_swarm", return_value=mock_swarm), \
         patch("app.services.video_engine.VideoEngine.download_youtube_sections", side_effect=mock_download_sections), \
         patch("app.services.video_engine.VideoEngine.download_youtube_video", side_effect=mock_download_video), \
         patch("app.services.video_engine.VideoEngine.get_duration", return_value=120.0), \
         patch("app.services.video_engine.VideoEngine.slice_and_assemble_scenes", side_effect=mock_slice), \
         patch("app.services.voice_engine.VoiceEngine.synthesize_speech", return_value=True), \
         patch("app.services.voice_engine.VoiceEngine.get_audio_duration", return_value=30.0), \
         patch("app.services.audio_mixer.AudioMixer.mix_soundtrack", return_value=True), \
         patch("app.services.video_engine.VideoEngine.render_final_explainer", side_effect=mock_render), \
         patch("app.services.thumbnail_engine.ThumbnailEngine.generate_3_thumbnail_options", return_value=[{"id": 1, "url": "t1.jpg"}]):

        response = client.post(
            "/api/v1/explainer/run-autopilot",
            data={
                "url": "https://www.youtube.com/watch?v=mock123",
                "transcript_text": SAMPLE_TRANSCRIPT,
                "target_lang": "ur",
                "narrator_voice": "ur-PK-AsadNeural",
                "speech_velocity": "fast",
                "resolution": "720p",
                "aspect_ratio": "vertical"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "video_url" in data
        assert "script" in data
        assert "seo_pack" in data
        assert "thumbnails" in data
        assert "hook_score" in data
