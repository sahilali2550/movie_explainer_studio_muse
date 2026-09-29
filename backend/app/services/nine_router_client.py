import os
import re
import json
import time
import requests
from typing import List, Dict, Optional, Any

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "config", "9router_settings.json")

DEFAULT_COMBO_MODEL = "new-combo"

LANGUAGE_NAMES = {
    "ur": "Urdu (اردو)",
    "en": "English",
    "hi": "Hindi (हिंदी)",
    "es": "Spanish (Español)",
    "ar": "Arabic (العربية)",
    "fr": "French (Français)",
    "de": "German (Deutsch)",
    "pt": "Portuguese (Português)",
    "id": "Indonesian (Bahasa Indonesia)",
    "tr": "Turkish (Türkçe)",
    "ru": "Russian (Русский)",
    "it": "Italian (Italiano)",
    "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)",
    "zh": "Chinese Simplified (中文)"
}


def load_9router_settings() -> Dict[str, Any]:
    """Loads saved 9Router endpoint, combo name and key from config file."""
    defaults = {
        "url": "http://127.0.0.1:20128/v1",
        "key": os.environ.get("NINE_ROUTER_KEY", ""),
        "combo_model": "new-combo",
        "fallback_models": ["new-combo"]
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                defaults.update(saved)
                if saved.get("combo_model"):
                    defaults["combo_model"] = saved["combo_model"]
                if saved.get("fallback_models"):
                    defaults["fallback_models"] = saved["fallback_models"]
        except Exception:
            pass
    return defaults



def save_9router_settings(url: str, combo_model: str, key: Optional[str] = None) -> bool:
    """Saves updated 9Router endpoint and combo name to config."""
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    cfg = load_9router_settings()
    if url:
        cfg["url"] = url.rstrip("/")
    if combo_model:
        cfg["combo_model"] = combo_model.strip()
        cfg["fallback_models"] = [combo_model.strip()]
    if key is not None:
        cfg["key"] = key.strip()
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"[Save 9Router Settings Error] {e}")
        return False


def test_9router_connection() -> Dict[str, Any]:
    """Pings 9Router and measures live latency in milliseconds."""
    cfg = load_9router_settings()
    url = cfg.get("url", "http://127.0.0.1:20128/v1")
    key = cfg.get("key", "")
    combo = cfg.get("combo_model", "new-combo")

    t0 = time.time()
    try:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        res = requests.get(f"{url}/models", headers=headers, timeout=8.0)
        latency_ms = int((time.time() - t0) * 1000)

        if res.status_code == 200:
            data = res.json()
            model_ids = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            return {
                "online": True,
                "latency_ms": latency_ms,
                "active_combo": combo,
                "models_count": len(model_ids),
                "url": url,
                "message": f"Connected! ({latency_ms}ms, {len(model_ids)} models available)"
            }
        else:
            return {
                "online": False,
                "latency_ms": latency_ms,
                "active_combo": combo,
                "url": url,
                "message": f"HTTP {res.status_code}: 9Router returned an error"
            }
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        return {
            "online": False,
            "latency_ms": latency_ms,
            "active_combo": combo,
            "url": url,
            "message": f"Connection failed: {str(e)[:60]}"
        }


def is_ninerouter_available(timeout_sec: float = 8.0) -> bool:
    """Checks if 9Router proxy is reachable."""
    cfg = load_9router_settings()
    url = cfg.get("url", "http://127.0.0.1:20128/v1")
    key = cfg.get("key", "")
    try:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        res = requests.get(f"{url}/models", headers=headers, timeout=timeout_sec)
        return res.status_code == 200
    except Exception:
        return False


def get_ninerouter_status_info() -> Dict[str, Any]:
    """Returns status info matching legacy endpoint."""
    t_res = test_9router_connection()
    return {
        "available": t_res["online"],
        "active_model": t_res["active_combo"],
        "has_sahil_combo": True,
        "models_count": t_res.get("models_count", 0),
        "latency_ms": t_res.get("latency_ms", 0),
        "url": t_res["url"]
    }


def call_ninerouter_llm(
    prompt: str,
    system_prompt: str = "",
    model: Optional[str] = None,
    temperature: float = 0.3,
    timeout_sec: int = 90,
    max_tokens: int = 4000
) -> Optional[str]:
    """Sends a chat completion request to 9Router strictly using the specified/configured combo."""
    cfg = load_9router_settings()
    base_url = cfg.get("url", "http://127.0.0.1:20128/v1")
    api_key = cfg.get("key", "")
    target_model = model or cfg.get("combo_model", "sahil-combo")

    # Strictly use target_model only (no jumping to other combos or fallback models)
    for attempt in range(2):  # 2 retry attempts strictly for the target model
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": target_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }

            res = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=timeout_sec)
            res.encoding = 'utf-8'
            if res.status_code == 200:
                try:
                    data = res.json()
                    content = data['choices'][0]['message']['content'].strip()
                    if content:
                        return content
                except Exception:
                    collected = []
                    for line in res.text.splitlines():
                        if line.startswith("data: ") and not line.startswith("data: [DONE]"):
                            try:
                                chunk = json.loads(line[6:])
                                delta = chunk.get('choices', [{}])[0].get('delta', {})
                                content_chunk = delta.get('content', '')
                                if content_chunk:
                                    collected.append(content_chunk)
                            except Exception:
                                pass
                    if collected:
                        return "".join(collected).strip()
            else:
                print(f"[9Router LLM Strict Notice] HTTP {res.status_code} on attempt {attempt+1} for model {target_model}")
        except Exception as e:
            print(f"[9Router LLM Strict Error] Attempt {attempt+1} failed: {e}")
            time.sleep(0.5)
            continue
    return None


def generate_explainer_script_with_9router(
    title: str,
    description: str,
    subs_text: str,
    target_lang: str = "ur",
    mood: str = "suspense",
    num_parts: int = 3,
    format_mode: str = "reels_parts",
    target_duration_mins: int = 5,
    plot_summary: str = "",
    genre: str = "movie_recap"
) -> Optional[List[Dict]]:
    """
    Generates a viral cinematic recap/explainer storyboard script in any chosen world language
    using 9Router AI proxy with customizable duration, genre rules, and fast-paced narrator cadence.
    """
    if not is_ninerouter_available():
        return None

    lang_name = LANGUAGE_NAMES.get(target_lang.lower(), target_lang)
    target_words = max(140, target_duration_mins * 160)

    genre_titles = {
        "movie_recap": "movie & drama recap narrator, cinematic storyteller",
        "biography": "biographical documentary narrator, life story chronicler",
        "documentary": "investigative documentary filmmaker, crime & historical events narrator",
        "video_essay": "video essayist, business & tech case study storyteller"
    }
    role_desc = genre_titles.get(genre, "cinematic storyteller and explainer video narrator")

    system_prompt = (
        f"You are a world-class viral {role_desc}, and video storyboard scriptwriter in {lang_name}.\n"
        f"You craft highly engaging, dramatic, fast-paced, high-retention THIRD-PERSON stories for YouTube and Facebook.\n"
        f"CRITICAL CADENCE RULE: Write with breathless momentum, urgency, and dramatic suspense! Use short, punchy, active sentences that keep viewers glued. Do NOT write in a slow, boring, relaxed audiobook reading tone.\n"
        f"CRITICAL LENGTH RULE: The total voiceover script MUST be approximately {target_duration_mins} minutes long (Total Word Count: around {target_words} words across scenes).\n"
        f"Format requirements: Return a STRICT JSON ARRAY of scene objects covering the full story from beginning to climax: "
        f"[{{'part': 1, 'scene_num': 1, 'timestamp': '00:15 - 00:45', 'narration': '...', 'visual_cue': '...'}}]"
    )

    plot_guide_text = f"\nUser Provided Plot Context / Guide:\n{plot_summary}\n" if plot_summary else ""
    user_prompt = (
        f"Genre: {genre}\n"
        f"Title: {title}\n"
        f"Mood / Tone: {mood}\n"
        f"{plot_guide_text}"
        f"Summary/Context: {description[:1000]}\n"
        f"Transcript / Subtitles: {subs_text[:7000]}\n\n"
        f"Task: Generate a comprehensive {target_duration_mins}-minute (~{target_words} words) viral {genre} explainer storyboard in {lang_name}."
    )

    cfg = load_9router_settings()
    active_model = cfg.get("combo_model", DEFAULT_COMBO_MODEL)
    reply = call_ninerouter_llm(prompt=user_prompt, system_prompt=system_prompt, model=active_model, timeout_sec=120, max_tokens=4000)
    if not reply:
        return None

    try:
        clean = reply.strip()
        if clean.startswith("```"):
            lines = clean.splitlines()
            clean = "\n".join([l for l in lines if not l.startswith("```")]).strip()
            if clean.startswith("json"):
                clean = clean[4:].strip()
        parsed = json.loads(clean)
        if isinstance(parsed, list) and len(parsed) > 0:
            for idx, item in enumerate(parsed):
                if isinstance(item, dict):
                    txt = item.get('narration') or item.get('script') or ''
                    item['script'] = txt
                    item['narration'] = txt
                    if 'part' not in item:
                        item['part'] = idx + 1
                    if 'title' not in item:
                        item['title'] = f"Part {item.get('part', idx+1)}"
            return parsed
        elif isinstance(parsed, dict) and 'scenes' in parsed and isinstance(parsed['scenes'], list):
            scenes = parsed['scenes']
            for idx, item in enumerate(scenes):
                txt = item.get('narration') or item.get('script') or ''
                item['script'] = txt
                item['narration'] = txt
            return scenes
    except Exception as e:
        print(f"[9Router Script Parse Notice] {e}. Falling back to clean text parser...")

    # Robust fallback: If LLM returned raw text narrative instead of JSON
    raw_text = reply.strip()
    if raw_text.startswith("```"):
        raw_text = "\n".join([l for l in raw_text.splitlines() if not l.startswith("```")]).strip()
    if len(raw_text) > 40:
        return [{
            "part": 1,
            "title": "Full Story Recap",
            "script": raw_text,
            "narration": raw_text
        }]

    return None


def translate_with_9router(dialogues: List[Dict], target_lang: str = "ur", source_lang: str = "en") -> Optional[List[Dict]]:
    """
    Translates dialogue turns into any world language using 9Router's sahil-combo LLM proxy.
    Batches large dialogue sets into reliable chunks and produces natural, fluent colloquial dubbing script.
    """
    if not is_ninerouter_available() or not dialogues:
        return None

    src_name = LANGUAGE_NAMES.get(source_lang.lower(), source_lang)
    target_name = LANGUAGE_NAMES.get(target_lang.lower(), target_lang)
    translated_res = []
    batch_size = 15

    for i in range(0, len(dialogues), batch_size):
        batch = dialogues[i:i + batch_size]
        dialogue_texts = [d.get('orig_text') or d.get('original') or d.get('text', '') for d in batch]

        try:
            sys_p = (
                f"You are an elite film and podcast dubbing translator.\n"
                f"Translate the following JSON array of dialogue strings from {src_name} into natural, conversational, fluent {target_name}.\n"
                f"Rules:\n"
                f"1. Return ONLY a valid JSON array of strings corresponding to each translated dialogue line.\n"
                f"2. Keep the exact count of {len(dialogue_texts)} elements in the array.\n"
                f"3. Make translations highly engaging, natural, fluent and perfectly suitable for realistic voice dubbing.\n"
                f"4. Concise Dubbing Rule: Keep each translated line punchy, natural, and concise. Avoid wordy padding so that spoken duration matches original timing."
            )

            user_content = json.dumps(dialogue_texts, ensure_ascii=False)
            cfg = load_9router_settings()
            active_model = cfg.get("combo_model", DEFAULT_COMBO_MODEL)
            reply = call_ninerouter_llm(prompt=user_content, system_prompt=sys_p, model=active_model, timeout_sec=90)

            batch_parsed = None
            if reply:
                clean_reply = reply.strip()
                if clean_reply.startswith("```"):
                    lines = clean_reply.splitlines()
                    clean_reply = "\n".join([l for l in lines if not l.startswith("```")]).strip()
                    if clean_reply.startswith("json"):
                        clean_reply = clean_reply[4:].strip()

                try:
                    parsed = json.loads(clean_reply)
                    if isinstance(parsed, list) and len(parsed) == len(batch):
                        batch_parsed = parsed
                except Exception:
                    pass

            for idx, d in enumerate(batch):
                raw_orig = d.get('orig_text') or d.get('original') or d.get('text', '')
                if batch_parsed and idx < len(batch_parsed):
                    trans_text = str(batch_parsed[idx]).replace("\n", " ").strip()
                else:
                    trans_text = raw_orig

                translated_res.append({
                    'index': d.get('index', i + idx),
                    'speaker': d.get('speaker', 1),
                    'speaker_name': d.get('speaker_name', f"Speaker {d.get('speaker', 1)}"),
                    'text': trans_text,
                    'orig_text': raw_orig,
                    'original': raw_orig,
                    'start': d.get('start', 0.0),
                    'duration': d.get('duration', 3.0),
                    'time_str': d.get('time_str', '00:00')
                })
        except Exception as e:
            print(f"[9Router Batch Translation Warning] Batch {i//batch_size + 1} error: {e}")
            for idx, d in enumerate(batch):
                raw_orig = d.get('orig_text') or d.get('original') or d.get('text', '')
                translated_res.append({
                    'index': d.get('index', i + idx),
                    'speaker': d.get('speaker', 1),
                    'speaker_name': d.get('speaker_name', f"Speaker {d.get('speaker', 1)}"),
                    'text': raw_orig,
                    'orig_text': raw_orig,
                    'original': raw_orig,
                    'start': d.get('start', 0.0),
                    'duration': d.get('duration', 3.0),
                    'time_str': d.get('time_str', '00:00')
                })

    return translated_res


def generate_viral_metadata(title: str, transcript_sample: str, lang: str = "en") -> Dict[str, Any]:
    """
    Generates 3 high-CTR viral titles, 1 engaging post description, and 10-15 trending hashtags.
    Universal for any video, channel, or topic.
    """
    defaults = {
        "titles": [
            title or "Shocking Revelation | Full Video",
            f"The Truth Behind This Video | Watch Till End",
            f"You Won't Believe What Happened: {title[:40]}"
        ],
        "description": f"Watch the complete detailed breakdown of {title or 'this viral moment'}. Key insights, facts and full story explained in detail. Like, share and follow for more daily updates!",
        "hashtags": "#ViralVideo #TrendingNow #BreakingNews #FacebookReels #YouTubeShorts #MustWatch #VideoViral"
    }
    if not is_ninerouter_available():
        return defaults

    sys_p = (
        "You are an elite social media growth strategist for Facebook, YouTube, and TikTok.\n"
        "Generate ready-to-post metadata for this video.\n"
        "Return ONLY a JSON object with this exact structure:\n"
        "{\n"
        '  "titles": ["Viral Clickable Title 1", "Curiosity Hook Title 2", "Breaking News Title 3"],\n'
        '  "description": "Engaging 2-3 sentence Facebook post description with an emotional hook",\n'
        '  "hashtags": "#Tag1 #Tag2 #Tag3 #Tag4 #Tag5 #Tag6 #Tag7 #Tag8 #Tag9 #Tag10"\n'
        "}"
    )
    user_p = f"Video Title: {title}\nTranscript Highlights: {transcript_sample[:3000]}"
    cfg = load_9router_settings()
    active_model = cfg.get("combo_model", DEFAULT_COMBO_MODEL)
    reply = call_ninerouter_llm(prompt=user_p, system_prompt=sys_p, model=active_model, timeout_sec=40)
    if reply:
        try:
            clean = reply.strip()
            if clean.startswith("```"):
                lines = clean.splitlines()
                clean = "\n".join([l for l in lines if not l.startswith("```")]).strip()
                if clean.startswith("json"):
                    clean = clean[4:].strip()
            parsed = json.loads(clean)
            if isinstance(parsed, dict) and "titles" in parsed:
                return parsed
        except Exception:
            pass
    return defaults


def extract_story_beats_with_9router(
    title: str,
    dialogues_text: str,
    genre: str = "movie_recap",
    duration_sec: float = 3600.0,
    target_beats: int = 15
) -> List[Dict[str, Any]]:
    """
    Pass 1: Analyzes full chronological dialogue transcripts to extract 12-20 key
    theatrical Story Beats with exact source video timestamps, scene titles, and key actions.
    """
    if not is_ninerouter_available() or not dialogues_text:
        return []

    sys_p = (
        "You are an elite Hollywood Director and Story Analyst.\n"
        "Your task is to analyze the source dialogue timeline and extract the 12 to 20 most critical "
        "chronological STORY BEATS that form the complete backbone of this story from opening to climax.\n"
        "Return ONLY a STRICT JSON ARRAY of beat objects:\n"
        "[\n"
        "  {\n"
        '    "beat": 1,\n'
        '    "timestamp": "01:15 - 01:45",\n'
        '    "title": "Short Beat Title",\n'
        '    "action": "1-2 sentence dramatic summary of what occurs and why it matters",\n'
        '    "key_dialogue": "Most impactful quote spoken in this scene"\n'
        "  }\n"
        "]\n"
        "Rules: Timestamps MUST be in MM:SS - MM:SS or HH:MM:SS format matching the transcript timeline."
    )

    total_mins = round(duration_sec / 60.0, 1) if duration_sec else 60.0
    user_p = (
        f"Title: {title}\n"
        f"Genre: {genre}\n"
        f"Source Video Duration: ~{total_mins} minutes\n"
        f"Dialogue & Timeline Excerpts:\n{dialogues_text[:12000]}\n\n"
        f"Identify approximately {target_beats} chronological story beats covering the entire narrative arc."
    )

    cfg = load_9router_settings()
    active_model = cfg.get("combo_model", DEFAULT_COMBO_MODEL)
    reply = call_ninerouter_llm(prompt=user_p, system_prompt=sys_p, model=active_model, timeout_sec=90, max_tokens=3000)
    if reply:
        try:
            clean = reply.strip()
            if clean.startswith("```"):
                lines = clean.splitlines()
                clean = "\n".join([l for l in lines if not l.startswith("```")]).strip()
                if clean.startswith("json"):
                    clean = clean[4:].strip()
            parsed = json.loads(clean)
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed
        except Exception as e:
            print(f"[9Router Story Beat Parse Notice] {e}")

    return []


def generate_ai_thumbnail_strategy_with_9router(
    title: str,
    story_beats: List[Dict[str, Any]],
    target_lang: str = "en"
) -> Optional[Dict[str, Any]]:
    """
    Directs the thumbnail strategy: Selects the single highest-climax visual timestamp
    from the story beats, plus 3 high-CTR curiosity-inducing hook phrases in the target language.
    """
    if not is_ninerouter_available() or not story_beats:
        return None

    lang_name = LANGUAGE_NAMES.get(target_lang.lower(), target_lang)
    sys_p = (
        f"You are a master YouTube CTR Optimization Strategist and Thumbnail Art Director in {lang_name}.\n"
        f"Analyze the story beats and select the single most shocking, dramatic, or high-stakes climax moment "
        f"to capture as the video thumbnail keyframe.\n"
        f"Return ONLY a JSON object with this exact structure:\n"
        "{\n"
        '  "best_timestamp_sec": 1420.0,\n'
        '  "best_timestamp_formatted": "23:40",\n'
        f'  "hook_phrases": ["3-5 WORD HIGH CTR HOOK 1 IN {lang_name.upper()}", "HOOK 2", "HOOK 3"],\n'
        '  "badge": "HIGH SUSPENSE"\n'
        "}"
    )

    beats_summary = "\n".join([
        f"Beat {b.get('beat', i+1)} [{b.get('timestamp', '00:00')}]: {b.get('title', '')} - {b.get('action', '')}"
        for i, b in enumerate(story_beats[:20])
    ])

    user_p = f"Title: {title}\nStory Beats Timeline:\n{beats_summary}\n\nSelect the best thumbnail climax moment and 3 viral hook phrases in {lang_name}."

    cfg = load_9router_settings()
    active_model = cfg.get("combo_model", DEFAULT_COMBO_MODEL)
    reply = call_ninerouter_llm(prompt=user_p, system_prompt=sys_p, model=active_model, timeout_sec=40)
    if reply:
        try:
            clean = reply.strip()
            if clean.startswith("```"):
                lines = clean.splitlines()
                clean = "\n".join([l for l in lines if not l.startswith("```")]).strip()
                if clean.startswith("json"):
                    clean = clean[4:].strip()
            parsed = json.loads(clean)
            if isinstance(parsed, dict) and "best_timestamp_sec" in parsed:
                return parsed
        except Exception:
            pass

    return None


def craft_cinematic_thumbnail_prompt(
    title: str,
    plot_summary: str = "",
    climax_beat: str = "",
    genre: str = "movie_recap"
) -> str:
    """
    Crafts an ultra-detailed, photorealistic visual prompt for 9Router image generation.
    Produces 16:9 cinematic YouTube thumbnail visuals featuring main character expressions and drama.
    """
    clean_title = title.strip() if title else "Suspense Story"
    plot_snippet = plot_summary[:250].strip() if plot_summary else ""
    climax_snippet = climax_beat[:180].strip() if climax_beat else ""

    genre_vibes = {
        "horror": "dark supernatural thriller, eerie volumetric shadows, horrific revelation, high contrast cinematic horror movie poster",
        "action": "high-octane action thriller, intense confrontation, sparks and neon reflections, explosive drama, Hollywood blockbuster poster",
        "romantic_drama": "tragic emotional drama, tearful expression, poignant romantic heartbreak, moody rain atmosphere, cinematic emotional lighting",
        "crime_mystery": "neo-noir detective investigation, mysterious silhouette, interrogation tension, dramatic hard shadows, film noir cinematic"
    }
    vibe = genre_vibes.get(genre.lower(), "cinematic movie thriller poster, intense dramatic stakes, hyper-realistic emotional character expression")

    prompt = (
        f"Ultra-realistic cinematic 8K photo, dramatic movie poster for '{clean_title}'. {vibe}. "
        f"Central focus: main character with an intense, shocked emotional expression. "
    )
    if climax_snippet:
        prompt += f"Scene context: {climax_snippet}. "
    elif plot_snippet:
        prompt += f"Story context: {plot_snippet}. "

    prompt += (
        "Volumetric cinematic lighting, deep color saturation, sharp focal depth, "
        "hyper-detailed realistic skin texture and clothing, 16:9 widescreen YouTube thumbnail ratio, professional studio photography, no text, no watermarks."
    )
    return prompt


def generate_ai_image_with_9router(
    prompt: str,
    size: str = "1792x1024",
    output_dir: Optional[str] = None
) -> Optional[str]:
    """
    Sends image generation request to 9Router's /images/generations endpoint.
    Downloads the image file and saves it in output_dir (or default THUMBNAILS_DIR).
    Returns local file path if successful, or None if offline or unsupported.
    """
    if not prompt:
        return None

    cfg = load_9router_settings()
    base_url = cfg.get("url", "http://127.0.0.1:20128/v1").rstrip("/")
    api_key = cfg.get("key", "")
    target_endpoint = f"{base_url}/images/generations"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    img_model = os.environ.get("NINE_ROUTER_IMAGE_MODEL", "flux")

    payload = {
        "prompt": prompt,
        "model": img_model,
        "n": 1,
        "size": "1024x1024" if "1024" in size and "1792" not in size else size,
        "response_format": "url"
    }

    try:
        import uuid
        import urllib.request
        from app.core.config import THUMBNAILS_DIR

        target_dir = output_dir or str(THUMBNAILS_DIR)
        os.makedirs(target_dir, exist_ok=True)

        resp = requests.post(target_endpoint, json=payload, headers=headers, timeout=50)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", [])
            if items:
                img_url = items[0].get("url")
                b64 = items[0].get("b64_json")
                out_path = os.path.join(target_dir, f"ai_gen_{uuid.uuid4().hex[:8]}.jpg")

                if img_url:
                    urllib.request.urlretrieve(img_url, out_path)
                    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                        return out_path
                elif b64:
                    import base64
                    with open(out_path, "wb") as f:
                        f.write(base64.b64decode(b64))
                    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                        return out_path
    except Exception as e:
        print(f"[9Router Image Gen Notice] Fallback triggered: {e}")

    return None


def generate_movie_specific_hooks(
    title: str,
    plot_summary: str = "",
    lang: str = "en"
) -> List[str]:
    """
    Generates 3 punchy, movie-specific clickbait thumbnail hook phrases tailored to the actual story.
    """
    lang_name = LANGUAGE_NAMES.get(lang.lower(), lang)
    sys_p = (
        f"You are a viral YouTube CTR specialist in {lang_name}.\n"
        f"Based on the movie title and plot, write EXACTLY 3 short, curiosity-inducing clickbait thumbnail hooks in {lang_name}.\n"
        f"Rules:\n"
        f"1. Each hook must be 2 to 6 words maximum.\n"
        f"2. Must relate directly to the specific plot twists or characters of this movie.\n"
        f"3. Return ONLY the 3 lines, numbered 1 to 3."
    )
    user_p = f"Movie Title: {title}\nPlot Summary: {plot_summary[:400]}"

    cfg = load_9router_settings()
    active_model = cfg.get("combo_model", DEFAULT_COMBO_MODEL)
    reply = call_ninerouter_llm(prompt=user_p, system_prompt=sys_p, model=active_model, timeout_sec=25)

    hooks = []
    if reply:
        for line in reply.splitlines():
            clean = re.sub(r'^\d+[\.\)]\s*', '', line).strip()
            clean = re.sub(r'[*"\'`]', '', clean).strip()
            if 3 <= len(clean) <= 45:
                hooks.append(clean)
            if len(hooks) >= 3:
                break

    if len(hooks) < 3:
        fallbacks = {
            "ur": [f"وہ سچ جو سب نے چھپایا!", f"{title}: سب سے بڑا موڑ!", "یہ خوفناک انجام تھا!"],
            "hi": [f"खौफनाक सच सामने आया!", f"{title}: सबसे बड़ा धोखा!", "रोंगटे खड़े कर देगा!"],
            "en": [f"THE TRUTH THEY HID!", f"{title}: THE BIGGEST TWIST!", "NOBODY SAW THIS COMING!"]
        }
        lang_defaults = fallbacks.get(lang.lower(), fallbacks["en"])
        while len(hooks) < 3:
            hooks.append(lang_defaults[len(hooks)])

    return hooks[:3]



