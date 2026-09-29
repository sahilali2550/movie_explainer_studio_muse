import os
import json
import pytest
from unittest.mock import patch, MagicMock

from app.services.openai_client import (
    load_openai_settings,
    save_openai_settings,
    is_openai_available,
    call_chatgpt_llm,
    generate_ai_image_with_dalle
)


def test_load_save_openai_settings(tmp_path):
    test_settings_file = tmp_path / "test_openai.json"
    with patch("app.services.openai_client.OPENAI_SETTINGS_FILE", str(test_settings_file)):
        # Initially empty/default
        cfg = load_openai_settings()
        assert "api_key" in cfg
        assert cfg["model"] == "gpt-4o"

        # Save settings
        ok = save_openai_settings(api_key="sk-test-12345", model="gpt-4o-mini")
        assert ok is True

        # Reload
        reloaded = load_openai_settings()
        assert reloaded["api_key"] == "sk-test-12345"
        assert reloaded["model"] == "gpt-4o-mini"


def test_is_openai_available_without_key():
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
        with patch("app.services.openai_client.load_openai_settings", return_value={"api_key": "", "model": "gpt-4o"}):
            assert is_openai_available() is False


def test_call_chatgpt_llm_success():
    fake_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "[SCENE: 00:15 - 00:30]\n[VOICEOVER]\nیہ ایک پراسرار کہانی کی شروعات ہے۔"
                }
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(fake_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = call_chatgpt_llm(
            prompt="Write a scene in Urdu",
            system_prompt="You are a storyteller",
            api_key="sk-test-mock-key"
        )
        assert res is not None
        assert "[SCENE: 00:15 - 00:30]" in res
        assert "کہانی" in res


def test_call_chatgpt_llm_graceful_fallback_on_error():
    with patch("urllib.request.urlopen", side_effect=Exception("Connection timed out")):
        res = call_chatgpt_llm(
            prompt="Test prompt",
            api_key="sk-test-mock-key"
        )
        assert res is None


def test_generate_ai_image_with_dalle_fallback_on_missing_key():
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
        with patch("app.services.openai_client.load_openai_settings", return_value={"api_key": "", "model": "gpt-4o"}):
            res = generate_ai_image_with_dalle("Cinematic poster")
            assert res is None


def test_generate_ai_image_with_dalle_success(tmp_path):
    fake_img_data = b"FAKE_IMAGE_BYTES_OVER_2000_BYTES" + b"X" * 2500
    mock_api_resp = MagicMock()
    mock_api_resp.read.return_value = json.dumps({
        "data": [{"url": "https://oaidalleapiprodscus.blob.core.windows.net/fake.jpg"}]
    }).encode("utf-8")
    mock_api_resp.__enter__.return_value = mock_api_resp

    mock_img_resp = MagicMock()
    mock_img_resp.read.return_value = fake_img_data
    mock_img_resp.__enter__.return_value = mock_img_resp

    def fake_urlopen(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "images/generations" in url:
            return mock_api_resp
        return mock_img_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        res = generate_ai_image_with_dalle(
            prompt="Pakistani drama poster",
            output_dir=str(tmp_path),
            api_key="sk-test-key"
        )
        assert res is not None
        assert os.path.exists(res)
        assert os.path.getsize(res) > 2000


def test_generate_script_with_openai_provider():
    from app.services.script_engine import ScriptEngine
    fake_script = (
        "[SCENE: 01:00 - 01:25]\n[VOICEOVER]\n"
        "داؤد کی شاندار انٹری تقریب میں ہلچل مچا دیتی ہے۔ سب اس کے رعب اور دبدبے سے واقف ہیں۔\n"
        "[SCENE: 05:00 - 05:30]\n[VOICEOVER]\n"
        "ارباز کی سازشیں بے نقاب ہو جاتی ہیں اور پہلی قسط سسپنس پر اختتام پذیر ہوتی ہے۔ "
        "کہانی کا اگلا موڑ جاننے کے لیے Episode 2 ابھی چینل پر دیکھیں!"
    )

    with patch("app.services.openai_client.call_chatgpt_llm", return_value=fake_script):
        res = ScriptEngine.generate_script(
            title="Nashtar Episode 01",
            description="Drama recap",
            subs_text="[01:00] Dawood enters the hall.",
            target_lang="ur",
            ai_provider="openai",
            openai_api_key="sk-test-mock-key"
        )
        assert res["success"] is True
        assert "openai:" in res["model"]
        assert "Episode 2" in res["script"] or "داؤد" in res["script"]


