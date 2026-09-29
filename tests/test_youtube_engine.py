import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import os

from app.services.youtube_engine import (
    format_publish_at_iso,
    build_video_insert_body,
    save_channel_profile,
    get_channel_profiles,
    delete_channel_profile,
    get_client_credentials,
    save_client_credentials,
)

def test_format_publish_at_iso_valid_future():
    # A future time string: e.g. "2026-10-15 19:00:00" in PKT (UTC+5)
    iso_str = format_publish_at_iso("2026-10-15 19:00:00", tz_offset_hours=5.0)
    # 19:00 - 5 hours = 14:00 UTC
    assert iso_str == "2026-10-15T14:00:00Z"

def test_format_publish_at_iso_iso_input_with_z():
    # Input already in ISO format
    iso_str = format_publish_at_iso("2026-12-01T15:30:00Z")
    assert iso_str == "2026-12-01T15:30:00Z"

def test_format_publish_at_iso_rejects_past_time():
    # Past time should raise ValueError
    past_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    with pytest.raises(ValueError, match="future"):
        format_publish_at_iso(past_date, tz_offset_hours=0.0)

def test_build_video_insert_body_structure():
    title = "Test AI Movie Explainer"
    description = "Full movie explanation and recap."
    tags = ["movie recap", "ai explainer", "cinema"]
    publish_at = "2026-10-15T14:00:00Z"
    
    body = build_video_insert_body(
        title=title,
        description=description,
        tags=tags,
        category_id="1",  # Film & Animation
        publish_at_iso=publish_at,
        made_for_kids=False
    )
    
    assert body["snippet"]["title"] == title
    assert body["snippet"]["description"] == description
    assert body["snippet"]["tags"] == tags
    assert body["snippet"]["categoryId"] == "1"
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == publish_at
    assert body["status"]["selfDeclaredMadeForKids"] is False

def test_channel_profile_crud(tmp_path, monkeypatch):
    test_channels_file = tmp_path / "test_channels.json"
    test_creds_file = tmp_path / "test_creds.json"
    
    monkeypatch.setattr("app.core.config.YOUTUBE_CHANNELS_FILE", test_channels_file)
    monkeypatch.setattr("app.core.config.YOUTUBE_CREDS_FILE", test_creds_file)
    
    # Initially empty
    channels = get_channel_profiles()
    assert channels == []
    
    # Save client credentials
    save_client_credentials("test-client-id-123", "test-client-secret-456")
    creds = get_client_credentials()
    assert creds["client_id"] == "test-client-id-123"
    assert creds["client_secret"] == "test-client-secret-456"
    
    # Save a channel
    channel_data = {
        "channel_id": "UC123456789",
        "title": "AutoExplainer Urdu",
        "custom_url": "@autoexplainer_urdu",
        "thumbnail_url": "https://yt3.ggpht.com/sample.jpg",
        "language": "ur",
        "refresh_token": "1//sample_refresh_token",
        "connected_at": "2026-09-12T10:00:00Z"
    }
    save_channel_profile(channel_data)
    
    # List channels
    channels = get_channel_profiles()
    assert len(channels) == 1
    assert channels[0]["channel_id"] == "UC123456789"
    assert channels[0]["title"] == "AutoExplainer Urdu"
    assert channels[0]["language"] == "ur"
    
    # Delete channel
    deleted = delete_channel_profile("UC123456789")
    assert deleted is True
    assert len(get_channel_profiles()) == 0

def test_youtube_api_status_and_setup(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    test_channels_file = tmp_path / "test_channels.json"
    test_creds_file = tmp_path / "test_creds.json"
    monkeypatch.setattr("app.core.config.YOUTUBE_CHANNELS_FILE", test_channels_file)
    monkeypatch.setattr("app.core.config.YOUTUBE_CREDS_FILE", test_creds_file)

    client = TestClient(app)

    # 1. Check initial status
    resp = client.get("/api/v1/youtube/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is False
    assert data["channels_count"] == 0

    # 2. Setup client
    resp = client.post("/api/v1/youtube/setup-client", json={
        "client_id": "test-client-id.apps.googleusercontent.com",
        "client_secret": "GOCSPX-secret123"
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # Status now shows configured
    resp = client.get("/api/v1/youtube/status")
    assert resp.status_code == 200
    assert resp.json()["configured"] is True

def test_youtube_api_channels_and_schedule_validation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    test_channels_file = tmp_path / "test_channels.json"
    test_creds_file = tmp_path / "test_creds.json"
    monkeypatch.setattr("app.core.config.YOUTUBE_CHANNELS_FILE", test_channels_file)
    monkeypatch.setattr("app.core.config.YOUTUBE_CREDS_FILE", test_creds_file)

    client = TestClient(app)

    # Add a mock channel directly
    save_channel_profile({
        "channel_id": "UC999",
        "title": "Recap Urdu",
        "custom_url": "@recap_urdu",
        "thumbnail_url": "https://example.com/avatar.jpg",
        "language": "ur",
        "refresh_token": "token123"
    })

    # List channels via API
    resp = client.get("/api/v1/youtube/channels")
    assert resp.status_code == 200
    channels = resp.json()["channels"]
    assert len(channels) == 1
    # Check that refresh_token is not leaked
    assert "refresh_token" not in channels[0]

    # Delete channel
    resp = client.delete("/api/v1/youtube/channels/UC999")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

def test_youtube_api_schedule_workflow(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    test_channels_file = tmp_path / "test_channels.json"
    test_creds_file = tmp_path / "test_creds.json"
    monkeypatch.setattr("app.core.config.YOUTUBE_CHANNELS_FILE", test_channels_file)
    monkeypatch.setattr("app.core.config.YOUTUBE_CREDS_FILE", test_creds_file)

    client = TestClient(app)

    # Save mock channel
    save_channel_profile({
        "channel_id": "UC_TEST_SCHED",
        "title": "Sched Channel",
        "custom_url": "@sched",
        "language": "en",
        "refresh_token": "token_sched_test"
    })

    # Create dummy video file
    dummy_video = tmp_path / "test_video.mp4"
    dummy_video.write_bytes(b"dummy mp4 video bytes")

    # Future publish datetime (tomorrow at 19:00 UTC)
    future_time = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d 19:00:00")

    # Schedule payload
    payload = {
        "channel_id": "UC_TEST_SCHED",
        "video_path": str(dummy_video),
        "title": "AI Explainer Sci-Fi Movie",
        "description": "An intense thrilling sci-fi summary.",
        "tags": ["scifi", "movie recap"],
        "publish_at": future_time,
        "tz_offset_hours": 0.0,
        "language": "en"
    }

    resp = client.post("/api/v1/youtube/schedule", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert "task_id" in data
    task_id = data["task_id"]

    # Poll task status
    task_resp = client.get(f"/api/v1/youtube/tasks/{task_id}")
    assert task_resp.status_code == 200
    task_data = task_resp.json()
    assert task_data["task_id"] == task_id
    assert task_data["channel_id"] == "UC_TEST_SCHED"


