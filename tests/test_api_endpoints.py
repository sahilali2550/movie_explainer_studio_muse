import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_api_config_endpoint():
    """GET /api/v1/explainer/config returns status 200 with supported languages."""
    res = client.get("/api/v1/explainer/config")
    assert res.status_code == 200
    data = res.json()
    assert "languages" in data
    assert "ur" in data["languages"]
    assert "en" in data["languages"]
    assert "es" in data["languages"]
    assert "personas" in data
    assert "mood_themes" in data
    assert "genres" in data
    assert "movie_recap" in data["genres"]
    assert "biography" in data["genres"]
    assert "documentary" in data["genres"]
    assert "video_essay" in data["genres"]
    assert "audio_modes" in data
    assert "hybrid" in data["audio_modes"]
    assert "sfx_only" in data["audio_modes"]
    assert "music_only" in data["audio_modes"]



def test_update_thumbnail_endpoint_traversal_rejection():
    """POST /api/v1/explainer/update-thumbnail rejects malicious path traversal attempts."""
    payload = {
        "filename": "../../etc/passwd.jpg",
        "hook_text": "Hacked!",
        "language": "en",
        "badge": "ALERT"
    }
    res = client.post("/api/v1/explainer/update-thumbnail", data=payload)
    # Must reject with 400 Bad Request
    assert res.status_code == 400


def test_download_bundle_zip_endpoint_job_id_validation():
    """GET /api/v1/explainer/download-bundle-zip rejects invalid/traversal job IDs."""
    malicious_job_ids = [
        "../../evil",
        "..\\..\\evil",
        "",
        "ab",  # too short
        "a" * 50,  # too long
        "job!@#$%",
    ]
    for jid in malicious_job_ids:
        res = client.get(f"/api/v1/explainer/download-bundle-zip?job_id={jid}")
        assert res.status_code in (400, 404, 422), f"Failed for job_id: {jid}"


def test_translate_scripts_endpoint_validation():
    """POST /api/v1/explainer/translate-scripts rejects empty script text."""
    res = client.post("/api/v1/explainer/translate-scripts", data={"base_script": ""})
    assert res.status_code == 400


def test_generate_script_endpoint_with_genre():
    """POST /api/v1/explainer/generate-script accepts genre and returns script."""
    payload = {
        "title": "Elon Musk Early Years",
        "genre": "biography",
        "duration_mins": 3,
        "language": "en"
    }
    with patch("app.services.script_engine.ScriptEngine.generate_script") as mock_gen:
        mock_gen.return_value = {
            "success": True,
            "title": "Elon Musk Early Years",
            "script": "A look into the early beginnings and pivotal decisions.",
            "genre": "biography",
            "hook_score": 82
        }
        res = client.post("/api/v1/explainer/generate-script", data=payload)
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") is True
        assert "script" in data
        assert data.get("genre") == "biography"


def test_generate_script_endpoint_with_custom_transcript():
    """POST /api/v1/explainer/generate-script accepts custom_transcript and processes it without YouTube download."""
    raw_transcript = """
    00:10
    The diamond was kept in a high-security vault.
    00:35
    Late at night, an elite hacker cut the power.
    """
    payload = {
        "title": "Heist Case Study",
        "genre": "movie_recap",
        "custom_transcript": raw_transcript,
        "language": "en"
    }
    with patch("app.services.script_engine.ScriptEngine.generate_script") as mock_gen:
        mock_gen.return_value = {
            "success": True,
            "title": "Heist Case Study",
            "script": "A dramatic heist began when an elite hacker cut the power.",
            "hook_score": 88
        }
        res = client.post("/api/v1/explainer/generate-script", data=payload)
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") is True
        assert "script" in data



