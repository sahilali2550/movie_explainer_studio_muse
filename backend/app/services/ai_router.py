import os
import json
import time
import requests
from typing import Dict, Any, Optional

SETTINGS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "config"
)
AI_SETTINGS_FILE = os.path.join(SETTINGS_DIR, "ai_settings.json")
NINE_ROUTER_SETTINGS_FILE = os.path.join(SETTINGS_DIR, "9router_settings.json")
OPENAI_SETTINGS_FILE = os.path.join(SETTINGS_DIR, "openai_settings.json")

DEFAULT_PROVIDER = "9router"

DEFAULT_CONFIG: Dict[str, Any] = {
    "active_provider": "9router",
    "providers": {
        "9router": {
            "name": "9Router Hub (Local Proxy)",
            "url": "http://127.0.0.1:20128/v1",
            "key": "sk-8c5563ee769fb340-zrhvmr-b3665e89",
            "model": "new-combo"
        },
        "gemini": {
            "name": "Google Gemini (Free Tier)",
            "key": "",
            "model": "gemini-1.5-flash",
            "available_models": ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"]
        },
        "openai": {
            "name": "OpenAI ChatGPT",
            "key": "",
            "model": "gpt-4o",
            "available_models": ["gpt-4o", "gpt-4o-mini", "o3-mini"]
        },
        "custom": {
            "name": "Custom / Groq / Ollama",
            "url": "http://localhost:11434/v1",
            "key": "",
            "model": "llama3"
        }
    }
}


def load_ai_settings() -> Dict[str, Any]:
    """Loads unified AI configuration, safely preserving legacy settings."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    
    # 1. Inherit legacy 9Router settings if present
    if os.path.exists(NINE_ROUTER_SETTINGS_FILE):
        try:
            with open(NINE_ROUTER_SETTINGS_FILE, "r", encoding="utf-8") as f:
                nr = json.load(f)
                if nr.get("url"):
                    cfg["providers"]["9router"]["url"] = nr["url"]
                if nr.get("key"):
                    cfg["providers"]["9router"]["key"] = nr["key"]
                if nr.get("combo_model"):
                    cfg["providers"]["9router"]["model"] = nr["combo_model"]
        except Exception:
            pass

    # 2. Inherit legacy OpenAI settings if present
    if os.path.exists(OPENAI_SETTINGS_FILE):
        try:
            with open(OPENAI_SETTINGS_FILE, "r", encoding="utf-8") as f:
                oa = json.load(f)
                if oa.get("api_key"):
                    cfg["providers"]["openai"]["key"] = oa["api_key"]
                if oa.get("model"):
                    cfg["providers"]["openai"]["model"] = oa["model"]
        except Exception:
            pass

    # 3. Overlay unified settings file if present
    if os.path.exists(AI_SETTINGS_FILE):
        try:
            with open(AI_SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if saved.get("active_provider"):
                    cfg["active_provider"] = saved["active_provider"]
                if saved.get("providers"):
                    for p_key, p_val in saved["providers"].items():
                        if p_key in cfg["providers"]:
                            cfg["providers"][p_key].update(p_val)
        except Exception:
            pass

    return cfg


def _is_valid_new_key(val: Optional[str]) -> bool:
    """Returns True if the key string is a genuine new key and not masked or non-ascii."""
    if not val:
        return False
    s = val.strip()
    if not s or s == "***" or s.startswith("...") or any(ord(c) > 127 for c in s):
        return False
    return True


def save_ai_settings(
    provider: Optional[str] = None,
    nine_router_url: Optional[str] = None,
    nine_router_key: Optional[str] = None,
    nine_router_combo: Optional[str] = None,
    gemini_key: Optional[str] = None,
    gemini_model: Optional[str] = None,
    openai_key: Optional[str] = None,
    openai_model: Optional[str] = None,
    custom_url: Optional[str] = None,
    custom_key: Optional[str] = None,
    custom_model: Optional[str] = None
) -> bool:
    """Updates and saves AI configuration."""
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    cfg = load_ai_settings()

    if provider and provider in cfg["providers"]:
        cfg["active_provider"] = provider

    if nine_router_url is not None and nine_router_url.strip():
        cfg["providers"]["9router"]["url"] = nine_router_url.strip().rstrip("/")
    if _is_valid_new_key(nine_router_key):
        cfg["providers"]["9router"]["key"] = nine_router_key.strip()
    if nine_router_combo is not None and nine_router_combo.strip():
        cfg["providers"]["9router"]["model"] = nine_router_combo.strip()

    if _is_valid_new_key(gemini_key):
        cfg["providers"]["gemini"]["key"] = gemini_key.strip()
    if gemini_model is not None and gemini_model.strip():
        cfg["providers"]["gemini"]["model"] = gemini_model.strip()

    if _is_valid_new_key(openai_key):
        cfg["providers"]["openai"]["key"] = openai_key.strip()
    if openai_model is not None and openai_model.strip():
        cfg["providers"]["openai"]["model"] = openai_model.strip()

    if custom_url is not None and custom_url.strip():
        cfg["providers"]["custom"]["url"] = custom_url.strip().rstrip("/")
    if _is_valid_new_key(custom_key):
        cfg["providers"]["custom"]["key"] = custom_key.strip()
    if custom_model is not None and custom_model.strip():
        cfg["providers"]["custom"]["model"] = custom_model.strip()

    try:
        with open(AI_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

        # Synchronize back to legacy 9router config file for complete backward compatibility
        try:
            from app.services.nine_router_client import save_9router_settings
            save_9router_settings(
                url=cfg["providers"]["9router"]["url"],
                combo_model=cfg["providers"]["9router"]["model"],
                key=cfg["providers"]["9router"]["key"]
            )
        except Exception:
            pass

        # Synchronize back to legacy openai config file for backward compatibility
        try:
            from app.services.openai_client import save_openai_settings
            save_openai_settings(
                api_key=cfg["providers"]["openai"]["key"],
                model=cfg["providers"]["openai"]["model"]
            )
        except Exception:
            pass

        return True
    except Exception as e:
        print(f"[Save AI Settings Error] {e}")
        return False


def test_provider_connection(
    provider: str,
    url: Optional[str] = None,
    key: Optional[str] = None,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """Tests connection to a specified AI provider and measures latency in milliseconds."""
    cfg = load_ai_settings()
    p_info = cfg["providers"].get(provider, {})

    target_url = (url or p_info.get("url", "")).rstrip("/")
    target_key = key.strip() if _is_valid_new_key(key) else p_info.get("key", "")
    target_model = model or p_info.get("model", "")

    t0 = time.time()

    if provider == "9router":
        try:
            headers = {"Authorization": f"Bearer {target_key}"} if target_key else {}
            res = requests.get(f"{target_url}/models", headers=headers, timeout=6.0)
            latency_ms = int((time.time() - t0) * 1000)
            if res.status_code == 200:
                data = res.json()
                models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                return {
                    "online": True,
                    "latency_ms": latency_ms,
                    "models_count": len(models),
                    "message": f"Connected to 9Router Proxy! ({latency_ms}ms, {len(models)} models available)"
                }
            return {
                "online": False,
                "latency_ms": latency_ms,
                "message": f"9Router returned status {res.status_code}: {res.text[:120]}"
            }
        except Exception as e:
            return {"online": False, "message": f"Could not reach 9Router at {target_url}: {str(e)}"}

    elif provider == "gemini":
        if not target_key:
            return {"online": False, "message": "Gemini API key is required. Get one free at aistudio.google.com"}
        try:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={target_key}"
            payload = {
                "contents": [{"parts": [{"text": "Hello, respond with PONG."}]}],
                "generationConfig": {"maxOutputTokens": 10}
            }
            res = requests.post(endpoint, json=payload, headers={"Content-Type": "application/json"}, timeout=8.0)
            latency_ms = int((time.time() - t0) * 1000)
            if res.status_code == 200:
                return {
                    "online": True,
                    "latency_ms": latency_ms,
                    "message": f"Connected to Google Gemini ({target_model}) successfully!"
                }
            return {
                "online": False,
                "latency_ms": latency_ms,
                "message": f"Google Gemini returned status {res.status_code}: {res.text[:140]}"
            }
        except Exception as e:
            return {"online": False, "message": f"Gemini connection failed: {str(e)}"}

    elif provider in ("openai", "custom"):
        base_url = target_url if provider == "custom" else "https://api.openai.com/v1"
        try:
            headers = {"Authorization": f"Bearer {target_key}"} if target_key else {}
            res = requests.get(f"{base_url}/models", headers=headers, timeout=6.0)
            latency_ms = int((time.time() - t0) * 1000)
            if res.status_code == 200:
                return {
                    "online": True,
                    "latency_ms": latency_ms,
                    "message": f"Connected to {p_info.get('name', provider)} ({target_model})!"
                }
            return {
                "online": False,
                "latency_ms": latency_ms,
                "message": f"{provider.upper()} returned status {res.status_code}"
            }
        except Exception as e:
            return {"online": False, "message": f"Connection failed: {str(e)}"}

    return {"online": False, "message": f"Unknown provider: {provider}"}


def generate_narrative_text(
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 2500,
    temperature: float = 0.7
) -> Optional[str]:
    """
    Central dispatcher: Routes prompt to whichever AI provider is currently active.
    Falls back gracefully if the active provider fails.
    """
    if not prompt:
        return None

    cfg = load_ai_settings()
    active = cfg.get("active_provider", "9router")
    p_info = cfg["providers"].get(active, {})

    # Dispatch to 9Router
    if active == "9router":
        from app.services.nine_router_client import call_9router_llm
        url = p_info.get("url", "http://127.0.0.1:20128/v1")
        model = p_info.get("model", "new-combo")
        key = p_info.get("key", "")
        return call_9router_llm(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            api_url=url,
            api_key=key
        )

    # Dispatch to Google Gemini
    elif active == "gemini":
        key = p_info.get("key", "")
        model = p_info.get("model", "gemini-1.5-flash")
        if not key:
            print("[AIRouter] Gemini key missing, falling back to 9Router...")
            from app.services.nine_router_client import call_9router_llm
            return call_9router_llm(prompt, system_prompt, max_tokens=max_tokens)

        try:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            contents = []
            if system_prompt:
                contents.append({"role": "user", "parts": [{"text": f"SYSTEM INSTRUCTION: {system_prompt}"}]})
                contents.append({"role": "model", "parts": [{"text": "Understood. I will follow your instructions."}]})
            contents.append({"role": "user", "parts": [{"text": prompt}]})

            payload = {
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens
                }
            }
            res = requests.post(endpoint, json=payload, headers={"Content-Type": "application/json"}, timeout=45.0)
            if res.status_code == 200:
                data = res.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
            print(f"[AIRouter Gemini Error] Status {res.status_code}: {res.text[:200]}")
        except Exception as e:
            print(f"[AIRouter Gemini Exception] {e}")

    # Dispatch to OpenAI
    elif active == "openai":
        from app.services.openai_client import call_chatgpt_llm
        key = p_info.get("key", "")
        model = p_info.get("model", "gpt-4o")
        return call_chatgpt_llm(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=key
        )

    # Dispatch to Custom OpenAI-compatible endpoint
    elif active == "custom":
        url = p_info.get("url", "http://localhost:11434/v1")
        key = p_info.get("key", "")
        model = p_info.get("model", "llama3")
        try:
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            res = requests.post(f"{url}/chat/completions", json=payload, headers=headers, timeout=40.0)
            if res.status_code == 200:
                data = res.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
        except Exception as e:
            print(f"[AIRouter Custom Error] {e}")

    # Fallback to local 9router if active failed
    from app.services.nine_router_client import call_9router_llm
    return call_9router_llm(prompt, system_prompt, max_tokens=max_tokens)
