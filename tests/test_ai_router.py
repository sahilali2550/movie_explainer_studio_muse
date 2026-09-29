import os
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_ai_router_loads_9router_defaults(tmp_path):
    from app.services.ai_router import load_ai_settings, DEFAULT_PROVIDER
    
    cfg = load_ai_settings()
    assert cfg is not None
    assert "active_provider" in cfg
    assert "providers" in cfg
    assert "9router" in cfg["providers"]
    assert "gemini" in cfg["providers"]
    assert "openai" in cfg["providers"]
    assert "custom" in cfg["providers"]


def test_ai_router_switch_provider_and_save(tmp_path):
    from app.services.ai_router import save_ai_settings, load_ai_settings
    
    ok = save_ai_settings(
        provider="gemini",
        gemini_key="AIzaSyTestFakeKey123",
        gemini_model="gemini-1.5-flash"
    )
    assert ok is True
    cfg = load_ai_settings()
    assert cfg["active_provider"] == "gemini"
    assert cfg["providers"]["gemini"]["key"] == "AIzaSyTestFakeKey123"
    assert cfg["providers"]["gemini"]["model"] == "gemini-1.5-flash"
    
    # Restore 9router default
    save_ai_settings(provider="9router")


def test_ai_router_test_connection_9router_mock():
    from app.services.ai_router import test_provider_connection
    
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "new-combo"}, {"id": "gpt-4o"}]}
        mock_get.return_value = mock_resp
        
        res = test_provider_connection("9router", url="http://127.0.0.1:20128/v1", model="new-combo", key="sk-test")
        assert res["online"] is True
        assert "latency_ms" in res
        assert res["models_count"] == 2


def test_ai_router_test_connection_gemini_mock():
    from app.services.ai_router import test_provider_connection
    
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "PONG"}]}}]
        }
        mock_post.return_value = mock_resp
        
        res = test_provider_connection("gemini", model="gemini-1.5-flash", key="AIzaSyFakeKey")
        assert res["online"] is True
        assert res["message"] == "Connected to Google Gemini (gemini-1.5-flash) successfully!"


def test_ai_router_generate_narrative_text_gemini_mock():
    from app.services.ai_router import generate_narrative_text, save_ai_settings
    
    save_ai_settings(provider="gemini", gemini_key="AIzaSyFakeKey", gemini_model="gemini-1.5-flash")
    
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "This is a dramatic movie recap."}]}}]
        }
        mock_post.return_value = mock_resp
        
        text = generate_narrative_text("Write a recap", system_prompt="You are a writer")
        assert text == "This is a dramatic movie recap."
    
    # Restore 9router
    save_ai_settings(provider="9router")


def test_ai_config_api_endpoints():
    # GET ai-config
    res = client.get("/api/v1/explainer/ai-config")
    assert res.status_code == 200
    data = res.json()
    assert "active_provider" in data
    assert "providers" in data
    
    # POST ai-config
    post_res = client.post(
        "/api/v1/explainer/ai-config",
        data={
            "provider": "9router",
            "nine_router_url": "http://127.0.0.1:20128/v1",
            "nine_router_combo": "new-combo",
            "nine_router_key": "sk-8c5563ee769fb340-zrhvmr-b3665e89"
        }
    )
    assert post_res.status_code == 200
    assert post_res.json()["success"] is True
