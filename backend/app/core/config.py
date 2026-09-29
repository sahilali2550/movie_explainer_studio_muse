import os
import shutil
from pathlib import Path
from typing import Dict, Any, List

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
OUTPUTS_DIR = STORAGE_DIR / "outputs"
TEMP_DIR = STORAGE_DIR / "temp"
THUMBNAILS_DIR = STORAGE_DIR / "outputs" / "thumbnails"
ASSETS_DIR = BASE_DIR / "assets"
MUSIC_DIR = ASSETS_DIR / "music"
FONTS_DIR = ASSETS_DIR / "fonts"
SFX_DIR = ASSETS_DIR / "sfx"
CONFIG_DIR = BASE_DIR.parent / "config"
YOUTUBE_CHANNELS_FILE = CONFIG_DIR / "youtube_channels.json"
YOUTUBE_CREDS_FILE = CONFIG_DIR / "youtube_credentials.json"

# Ensure all directories exist
for folder in [STORAGE_DIR, UPLOADS_DIR, OUTPUTS_DIR, TEMP_DIR, THUMBNAILS_DIR, MUSIC_DIR, FONTS_DIR, SFX_DIR, CONFIG_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

# 9Router AI Defaults
ROUTER_URL = os.getenv("ROUTER_URL", "http://127.0.0.1:20128/v1")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "new-combo")

# FFmpeg Auto-Detection
def get_ffmpeg_binary() -> str:
    # 1. Environment or PATH
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    # 2. imageio-ffmpeg fallback
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    # 3. Common Windows install locations
    for p in [
        r"C:\Program Files\Anas Media Downloader\_internal\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"
    ]:
        if os.path.exists(p):
            return p
    return "ffmpeg"

def get_ffprobe_binary() -> str:
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    for p in [
        r"C:\Program Files\Anas Media Downloader\_internal\bin\ffprobe.exe",
        r"C:\ffmpeg\bin\ffprobe.exe",
        r"C:\Program Files\ffmpeg\bin\ffprobe.exe"
    ]:
        if os.path.exists(p):
            return p
    return "ffprobe"

# Supported 15+ Global Languages
SUPPORTED_LANGUAGES: Dict[str, Dict[str, Any]] = {
    # Tier 1 - Viral Movie Recaps
    "es": {"name": "Spanish", "native": "Español", "rtl": False, "default_voice": "es-MX-DaliaNeural", "fallback_voice": "es-ES-AlvaroNeural"},
    "id": {"name": "Indonesian", "native": "Bahasa Indonesia", "rtl": False, "default_voice": "id-ID-ArdiNeural", "fallback_voice": "id-ID-GadisNeural"},
    "pt": {"name": "Portuguese (Brazil)", "native": "Português (Brasil)", "rtl": False, "default_voice": "pt-BR-AntonioNeural", "fallback_voice": "pt-BR-FranciscaNeural"},
    "hi": {"name": "Hindi", "native": "हिन्दी", "rtl": False, "default_voice": "hi-IN-MadhurNeural", "fallback_voice": "hi-IN-SwaraNeural"},
    "ur": {"name": "Urdu", "native": "اردو", "rtl": True, "default_voice": "ur-PK-AsadNeural", "fallback_voice": "ur-PK-UzmaNeural"},
    "en": {"name": "English", "native": "English", "rtl": False, "default_voice": "en-US-ChristopherNeural", "fallback_voice": "en-US-JennyNeural"},
    
    # Tier 2 - High CPM
    "ar": {"name": "Arabic", "native": "العربية", "rtl": True, "default_voice": "ar-SA-HamedNeural", "fallback_voice": "ar-SA-ZariyahNeural"},
    "de": {"name": "German", "native": "Deutsch", "rtl": False, "default_voice": "de-DE-ConradNeural", "fallback_voice": "de-DE-KatjaNeural"},
    "fr": {"name": "French", "native": "Français", "rtl": False, "default_voice": "fr-FR-HenriNeural", "fallback_voice": "fr-FR-DeniseNeural"},
    "ru": {"name": "Russian", "native": "Русский", "rtl": False, "default_voice": "ru-RU-DmitryNeural", "fallback_voice": "ru-RU-SvetlanaNeural"},
    "it": {"name": "Italian", "native": "Italiano", "rtl": False, "default_voice": "it-IT-DiegoNeural", "fallback_voice": "it-IT-ElsaNeural"},
    "tr": {"name": "Turkish", "native": "Türkçe", "rtl": False, "default_voice": "tr-TR-AhmetNeural", "fallback_voice": "tr-TR-EmelNeural"},

    # Tier 3 - Fast-Growing Asian Markets
    "vi": {"name": "Vietnamese", "native": "Tiếng Việt", "rtl": False, "default_voice": "vi-VN-NamMinhNeural", "fallback_voice": "vi-VN-HoaiMyNeural"},
    "th": {"name": "Thai", "native": "ไทย", "rtl": False, "default_voice": "th-TH-NiwatNeural", "fallback_voice": "th-TH-PremwadeeNeural"},
    "ja": {"name": "Japanese", "native": "日本語", "rtl": False, "default_voice": "ja-JP-KeitaNeural", "fallback_voice": "ja-JP-NanamiNeural"},
    "ko": {"name": "Korean", "native": "한국어", "rtl": False, "default_voice": "ko-KR-InJoonNeural", "fallback_voice": "ko-KR-SunHiNeural"},
}

# Story Tones / Personas
STORY_PERSONAS = {
    "hollywood_trailer": {
        "title": "🎬 Hollywood Trailer Narrator",
        "description": "Deep cinematic pitch, breathless suspense, dramatic pauses, high stakes"
    },
    "viral_fast": {
        "title": "⚡ Viral Fast-Paced Storyteller",
        "description": "Rapid momentum, urgent delivery, short punchy sentences for TikTok & Reels"
    },
    "sarcastic_roaster": {
        "title": "🍿 Sarcastic Movie Roaster",
        "description": "Humorous, witty, pointing out plot absurdities with funny commentary"
    },
    "documentary": {
        "title": "🔍 Crime & Investigative Documentary",
        "description": "Serious, dark mystery tone, uncovering secret motives and plot twists"
    }
}

# Universal Content Genres
CONTENT_GENRES: Dict[str, Dict[str, Any]] = {
    "movie_recap": {
        "id": "movie_recap",
        "title": "🎬 Movie / Series Recap",
        "description": "Engaging, suspenseful storytelling summarizing movie plots, twists, and character arcs.",
        "pacing_factor": 1.0,
        "default_persona": "hollywood_trailer",
        "sfx_theme": "cinematic"
    },
    "biography": {
        "id": "biography",
        "title": "👤 Biography & Real Story",
        "description": "Life story, humble beginnings, struggle, turning points, rise to success, and historical legacy.",
        "pacing_factor": 0.95,
        "default_persona": "documentary",
        "sfx_theme": "historical"
    },
    "documentary": {
        "id": "documentary",
        "title": "🔍 Investigative / True Crime / History",
        "description": "Deep-dive factual investigation, evidence breakdown, timeline events, and mystery unveiling.",
        "pacing_factor": 0.95,
        "default_persona": "documentary",
        "sfx_theme": "investigative"
    },
    "true_crime": {
        "id": "true_crime",
        "title": "🕵️ True Crime & Forensic Mystery",
        "description": "Chilling real-life crimes, investigative forensics, mystery timelines, and courtroom verdicts.",
        "pacing_factor": 0.95,
        "default_persona": "documentary",
        "sfx_theme": "investigative"
    },
    "tech_science": {
        "id": "tech_science",
        "title": "💡 Tech, Business & Science Case Study",
        "description": "Insightful analytical breakdown, case studies, business failures/successes, and tech explainers.",
        "pacing_factor": 1.0,
        "default_persona": "viral_fast",
        "sfx_theme": "modern"
    },
    "video_essay": {
        "id": "video_essay",
        "title": "💡 Video Essay & Analysis",
        "description": "Insightful analytical breakdown, case studies, business failures/successes, and tech explainers.",
        "pacing_factor": 1.0,
        "default_persona": "viral_fast",
        "sfx_theme": "modern"
    }
}

# Mood Categories
MOOD_THEMES = ["suspense", "action", "emotional", "upbeat", "horror"]

# Audio Modes
AUDIO_MODES: Dict[str, Dict[str, Any]] = {
    "hybrid": {
        "id": "hybrid",
        "title": "🎵 + 💥 Hybrid (Music + SFX)",
        "description": "Theatrical blend of ducked mood music and dynamic sound effect hits at scene cuts."
    },
    "sfx_only": {
        "id": "sfx_only",
        "title": "💥 Pure SFX (No Music)",
        "description": "Zero music (100% Halal / 0% Copyright Risk). Pure voiceover enhanced with dynamic whooshes, cinematic booms, and sound cues."
    },
    "music_only": {
        "id": "music_only",
        "title": "🎵 Music Only (Classic)",
        "description": "Classic movie explainer soundtrack with background music ducked under voiceover."
    }
}


# ---------------------------------------------------------------------------
# SECURITY: API token (auto-generated once, persisted with restricted perms).
# The frontend served by this server gets the token injected automatically;
# external API clients must send it via the X-API-Token header or ?token=.
# Override with the API_TOKEN environment variable.
# ---------------------------------------------------------------------------
import secrets as _secrets
import time as _time

API_TOKEN_FILE = STORAGE_DIR / ".api_token"

def _load_or_create_api_token() -> str:
    env_token = os.getenv("API_TOKEN", "").strip()
    if env_token:
        return env_token
    try:
        if API_TOKEN_FILE.exists():
            saved = API_TOKEN_FILE.read_text(encoding="utf-8").strip()
            if saved:
                return saved
    except OSError:
        pass
    token = _secrets.token_urlsafe(32)
    try:
        API_TOKEN_FILE.write_text(token, encoding="utf-8")
        os.chmod(API_TOKEN_FILE, 0o600)
    except OSError:
        pass
    return token

API_TOKEN = _load_or_create_api_token()

# ---------------------------------------------------------------------------
# Temp-file lifecycle: every render job scatters intermediate files across
# TEMP_DIR / UPLOADS_DIR. These helpers guarantee per-job cleanup (called from
# endpoint `finally` blocks) plus a startup purge of stale crash leftovers.
# ---------------------------------------------------------------------------

def cleanup_job_temp_files(job_id: str) -> int:
    """Deletes every temp/upload file belonging to `job_id`. Returns count removed."""
    if not job_id or len(job_id) < 4:
        return 0
    removed = 0
    for folder in (TEMP_DIR, UPLOADS_DIR):
        try:
            for entry in folder.iterdir():
                if entry.is_file() and job_id in entry.name:
                    try:
                        entry.unlink()
                        removed += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return removed


def purge_stale_temp_files(max_age_hours: float = 24.0) -> int:
    """Deletes temp/upload files older than `max_age_hours` (crash leftovers)."""
    cutoff = _time.time() - max_age_hours * 3600
    removed = 0
    for folder in (TEMP_DIR, UPLOADS_DIR):
        try:
            for entry in folder.iterdir():
                if entry.is_file() and entry.name != ".api_token":
                    try:
                        if entry.stat().st_mtime < cutoff:
                            entry.unlink()
                            removed += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return removed
