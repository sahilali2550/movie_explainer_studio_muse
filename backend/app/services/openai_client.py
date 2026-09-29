import os
import json
import uuid
import urllib.request
from typing import Dict, Any, Optional
from app.core.config import THUMBNAILS_DIR

OPENAI_SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
    "openai_settings.json"
)

DEFAULT_OPENAI_MODEL = "gpt-4o"


def load_openai_settings() -> Dict[str, Any]:
    """Loads saved OpenAI API key and preferred model from environment or config file."""
    defaults = {
        "api_key": os.environ.get("OPENAI_API_KEY", "").strip(),
        "model": os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip()
    }
    if os.path.exists(OPENAI_SETTINGS_FILE):
        try:
            with open(OPENAI_SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if saved.get("api_key") and not defaults["api_key"]:
                    defaults["api_key"] = saved["api_key"].strip()
                if saved.get("model"):
                    defaults["model"] = saved["model"].strip()
        except Exception:
            pass
    return defaults


def save_openai_settings(api_key: str, model: str = "gpt-4o") -> bool:
    """Saves updated OpenAI API key and model to config file."""
    os.makedirs(os.path.dirname(OPENAI_SETTINGS_FILE), exist_ok=True)
    cfg = load_openai_settings()
    if api_key is not None:
        cfg["api_key"] = api_key.strip()
    if model:
        cfg["model"] = model.strip()
    try:
        with open(OPENAI_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"[Save OpenAI Settings Error] {e}")
        return False


def is_openai_available(timeout_sec: float = 3.0) -> bool:
    """Checks if a valid OpenAI API key is configured."""
    cfg = load_openai_settings()
    key = cfg.get("api_key", "").strip()
    return bool(key and len(key) > 10)


def call_chatgpt_llm(
    prompt: str,
    system_prompt: str = "",
    model: str = "gpt-4o",
    max_tokens: int = 4000,
    temperature: float = 0.7,
    api_key: Optional[str] = None
) -> Optional[str]:
    """
    Calls OpenAI Chat Completions API (GPT-4o / GPT-4o-mini).
    Zero external dependencies, standard library urllib.
    """
    if not prompt:
        return None

    cfg = load_openai_settings()
    effective_key = (api_key or cfg.get("api_key", "")).strip()
    if not effective_key:
        return None

    effective_model = model or cfg.get("model", DEFAULT_OPENAI_MODEL)
    url = "https://api.openai.com/v1/chat/completions"

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": effective_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {effective_key}"
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if choices and "message" in choices[0]:
                content = choices[0]["message"].get("content", "")
                return content.strip()
    except Exception as e:
        print(f"[OpenAI ChatGPT Call Error] {e}")

    return None


def generate_ai_image_with_dalle(
    prompt: str,
    size: str = "1792x1024",
    output_dir: Optional[str] = None,
    api_key: Optional[str] = None
) -> Optional[str]:
    """
    Generates photorealistic cinema thumbnail poster art via OpenAI DALL-E 3.
    Saves image in output_dir (or default THUMBNAILS_DIR) and returns local file path.
    """
    if not prompt:
        return None

    cfg = load_openai_settings()
    effective_key = (api_key or cfg.get("api_key", "")).strip()
    if not effective_key:
        return None

    url = "https://api.openai.com/v1/images/generations"

    # DALL-E 3 supported sizes: 1024x1024, 1792x1024 (landscape 16:9), 1024x1792 (portrait)
    effective_size = "1792x1024" if "1024" in size and "1792" in size else ("1024x1024" if "1024" in size else "1792x1024")

    payload = {
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,
        "size": effective_size,
        "quality": "standard",
        "response_format": "url"
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {effective_key}"
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        target_dir = output_dir or str(THUMBNAILS_DIR)
        os.makedirs(target_dir, exist_ok=True)

        with urllib.request.urlopen(req, timeout=75) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("data", [])
            if items and items[0].get("url"):
                img_url = items[0]["url"]
                out_path = os.path.join(target_dir, f"dalle_{uuid.uuid4().hex[:8]}.jpg")
                img_req = urllib.request.Request(img_url, headers={"User-Agent": "AutoExplainer/1.0"})
                with urllib.request.urlopen(img_req, timeout=30) as img_resp:
                    content = img_resp.read()
                    if len(content) > 2000:
                        with open(out_path, "wb") as f:
                            f.write(content)
                        return out_path
    except Exception as e:
        print(f"[DALL-E 3 Generation Error] {e}")

    return None
