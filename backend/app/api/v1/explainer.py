import os
import re
import uuid
import shutil
import json
import zipfile
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, FileResponse

from app.core.config import (
    SUPPORTED_LANGUAGES, STORY_PERSONAS, MOOD_THEMES,
    CONTENT_GENRES, AUDIO_MODES,
    UPLOADS_DIR, OUTPUTS_DIR, TEMP_DIR, THUMBNAILS_DIR,
    cleanup_job_temp_files
)
from app.core.logger import log_event, EngineLogger
from app.services.script_engine import ScriptEngine
from app.services.voice_engine import VoiceEngine
from app.services.audio_mixer import AudioMixer
from app.services.video_engine import VideoEngine
from app.services.thumbnail_engine import ThumbnailEngine
from app.services.metadata_engine import MetadataEngine
from app.services.subtitle_engine import SubtitleEngine

router = APIRouter(prefix="/explainer", tags=["Explainer"])

MAX_VIDEO_BYTES = 500 * 1024 * 1024  # 500 MB
MAX_AUDIO_BYTES = 50 * 1024 * 1024   # 50 MB
ALLOWED_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".aac", ".m4a", ".ogg"}

def validate_uploaded_media(file: Optional[UploadFile], is_video: bool = True):
    """Validates extension and declared size of uploaded video/audio file."""
    if not file or not file.filename:
        return
    max_bytes = MAX_VIDEO_BYTES if is_video else MAX_AUDIO_BYTES
    ext = os.path.splitext(file.filename)[1].lower()
    allowed = ALLOWED_VIDEO_EXTS if is_video else ALLOWED_AUDIO_EXTS
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: '{ext}'. Allowed: {', '.join(sorted(allowed))}"
        )
    # Pre-check the client-declared size (Content-Length). The streaming
    # writer below re-verifies the actual bytes as a second layer.
    declared = getattr(file, "size", None)
    if declared is not None and declared > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: '{file.filename}' exceeds the {max_bytes // (1024 * 1024)} MB limit."
        )


def save_upload_with_limit(upload_file: UploadFile, dest_path: str, max_bytes: int) -> str:
    """
    Streams an uploaded file to disk in chunks, aborting with HTTP 413 if the
    actual byte count exceeds max_bytes. Removes any partial file on rejection.
    """
    total = 0
    try:
        with open(dest_path, "wb") as buffer:
            while True:
                chunk = upload_file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large: '{upload_file.filename}' exceeds the {max_bytes // (1024 * 1024)} MB limit."
                    )
                buffer.write(chunk)
    except HTTPException:
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except OSError:
            pass
        raise
    return dest_path

@router.get("/logs")
def get_live_logs():
    """Returns real-time engine activity and diagnostics logs."""
    return {"success": True, "logs": EngineLogger.get_logs()}

@router.post("/clear-logs")
def clear_logs_endpoint():
    """Clears the live log buffer."""
    EngineLogger.clear()
    return {"success": True}

@router.post("/open-output-folder")
def open_output_folder():
    """Opens the local outputs storage directory in system file explorer."""
    import platform, subprocess
    folder = str(OUTPUTS_DIR)
    try:
        if platform.system() == "Windows":
            os.startfile(folder)
        elif platform.system() == "Darwin":
            subprocess.run(["open", folder])
        else:
            subprocess.run(["xdg-open", folder])
        return {"success": True, "folder": folder}
    except Exception as e:
        return {"success": False, "error": str(e), "folder": folder}

@router.get("/ai-status")
def get_ai_status():
    """Checks 9Router connection status and models availability."""
    from app.services.ai_router import load_ai_settings, test_provider_connection
    cfg = load_ai_settings()
    active = cfg.get("active_provider", "9router")
    p_info = cfg["providers"].get(active, {})
    conn = test_provider_connection(active)
    return {
        "success": True,
        "online": conn.get("online", False),
        "active_provider": active,
        "active_combo": p_info.get("model", "new-combo"),
        "latency_ms": conn.get("latency_ms", 0),
        "models_count": conn.get("models_count", 0),
        "url": p_info.get("url", ""),
        "message": conn.get("message", "")
    }

@router.get("/ai-config")
def get_ai_config():
    """Returns current AI configuration for all supported providers."""
    from app.services.ai_router import load_ai_settings
    cfg = load_ai_settings()
    sanitized = json.loads(json.dumps(cfg))
    for p_name, p_data in sanitized.get("providers", {}).items():
        k = p_data.get("key", "")
        if k:
            p_data["key_masked"] = f"{k[:5]}...{k[-4:]}" if len(k) > 10 else "***"
        else:
            p_data["key_masked"] = ""
        # SECURITY: never expose the raw API key to the browser.
        p_data.pop("key", None)
    return sanitized

@router.post("/ai-config")
def update_ai_config(
    provider: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    combo_model: Optional[str] = Form(None),
    key: Optional[str] = Form(None),
    nine_router_url: Optional[str] = Form(None),
    nine_router_combo: Optional[str] = Form(None),
    nine_router_key: Optional[str] = Form(None),
    gemini_key: Optional[str] = Form(None),
    gemini_model: Optional[str] = Form(None),
    openai_key: Optional[str] = Form(None),
    openai_model: Optional[str] = Form(None),
    custom_url: Optional[str] = Form(None),
    custom_key: Optional[str] = Form(None),
    custom_model: Optional[str] = Form(None)
):
    """Updates AI configuration for 9Router, Gemini, OpenAI, or Custom providers."""
    from app.services.ai_router import save_ai_settings, test_provider_connection, load_ai_settings
    if url is not None and nine_router_url is None:
        nine_router_url = url
    if combo_model is not None and nine_router_combo is None:
        nine_router_combo = combo_model
    if key is not None and nine_router_key is None and (not provider or provider == "9router"):
        nine_router_key = key

    saved = save_ai_settings(
        provider=provider,
        nine_router_url=nine_router_url,
        nine_router_key=nine_router_key,
        nine_router_combo=nine_router_combo,
        gemini_key=gemini_key,
        gemini_model=gemini_model,
        openai_key=openai_key,
        openai_model=openai_model,
        custom_url=custom_url,
        custom_key=custom_key,
        custom_model=custom_model
    )
    active = load_ai_settings().get("active_provider", "9router")
    conn = test_provider_connection(active)
    return {
        "success": saved,
        "active_provider": active,
        "online": conn.get("online", False),
        "message": conn.get("message", "Settings updated successfully.")
    }

@router.post("/test-ai-connection")
def test_ai_connection_endpoint(
    provider: str = Form("9router"),
    url: Optional[str] = Form(None),
    key: Optional[str] = Form(None),
    model: Optional[str] = Form(None)
):
    """Tests connection to a specific AI provider on demand."""
    from app.services.ai_router import test_provider_connection
    return test_provider_connection(provider=provider, url=url, key=key, model=model)

@router.get("/openai-status")
def get_openai_status():
    """Checks OpenAI API key status and preferred model."""
    from app.services.openai_client import load_openai_settings, is_openai_available
    cfg = load_openai_settings()
    has_key = is_openai_available()
    key = cfg.get("api_key", "")
    masked = f"{key[:7]}...{key[-4:]}" if len(key) > 11 else ("***" if key else "")
    return {
        "success": True,
        "available": has_key,
        "model": cfg.get("model", "gpt-4o"),
        "key_masked": masked
    }

@router.post("/openai-config")
def update_openai_config(
    api_key: str = Form(...),
    model: str = Form("gpt-4o")
):
    """Saves OpenAI API key and model preference."""
    from app.services.openai_client import save_openai_settings, is_openai_available
    saved = save_openai_settings(api_key=api_key, model=model)
    return {
        "success": saved,
        "available": is_openai_available(),
        "model": model,
        "message": "OpenAI settings updated successfully."
    }

@router.post("/preview-clone")
async def preview_clone_endpoint(
    clone_sample_file: UploadFile = File(...),
    language: str = Form("ur")
):
    """Generates an instant 8-10s audition preview of the cloned voice."""
    if not clone_sample_file or not clone_sample_file.filename:
        raise HTTPException(status_code=400, detail="Voice sample file is required.")

    ext = os.path.splitext(clone_sample_file.filename)[1].lower() or ".mp3"
    job_id = str(uuid.uuid4())[:8]
    sample_path = str(TEMP_DIR / f"sample_upload_{job_id}{ext}")

    save_upload_with_limit(clone_sample_file, sample_path, MAX_AUDIO_BYTES)

    try:
        preview_file = await VoiceEngine.generate_cloned_preview(sample_path, language=language)
        if preview_file:
            return {
                "success": True,
                "preview_url": f"/outputs/temp/{preview_file}",
                "sample_path": sample_path
            }
        raise HTTPException(status_code=500, detail="Could not generate cloned voice audition sample.")
    finally:
        cleanup_job_temp_files(job_id)

@router.post("/instant-thumbnails")
async def instant_thumbnails_endpoint(
    url: Optional[str] = Form(None),
    language: str = Form("en"),
    title: Optional[str] = Form("Movie Story Recap"),
    plot_summary: Optional[str] = Form(""),
    local_file: Optional[UploadFile] = File(None)
):
    """
    Instant Thumbnail Studio:
    Extracts 3 high-contrast candidate frames and renders localized typography
    hooks in 2-3 seconds without waiting for video rendering!
    """
    job_id = str(uuid.uuid4())[:8]
    log_event(f"🖼️ Instant Thumbnail Generator triggered for '{title}' ({language.upper()})", "INFO")

    raw_video_path = str(UPLOADS_DIR / f"{job_id}_thumb_raw.mp4")
    movie_title = title or "Movie Story Recap"

    try:
        if local_file and local_file.filename:
            log_event(f"📁 Processing local video file: {local_file.filename}", "INFO")
            save_upload_with_limit(local_file, raw_video_path, MAX_VIDEO_BYTES)
            movie_title = os.path.splitext(local_file.filename)[0]
        elif url:
            log_event(f"🌐 Fetching highlight frames from YouTube: {url[:50]}...", "INFO")
            dl_ok = VideoEngine.download_youtube_video(url, raw_video_path)
            if not dl_ok or not os.path.exists(raw_video_path):
                log_event(f"❌ Failed to download video stream from YouTube", "ERROR")
                raise HTTPException(status_code=400, detail="Could not download video stream from YouTube.")
        else:
            raise HTTPException(status_code=400, detail="Please provide a YouTube URL or upload a local video file.")

        ai_image_path = None
        try:
            from app.services.nine_router_client import (
                is_ninerouter_available,
                craft_cinematic_thumbnail_prompt,
                generate_ai_image_with_9router
            )
            if await asyncio.to_thread(is_ninerouter_available):
                prompt = craft_cinematic_thumbnail_prompt(
                    title=movie_title,
                    plot_summary=plot_summary[:400] if plot_summary else movie_title,
                    genre="movie_recap"
                )
                log_event("🎨 Generating 9Router photorealistic cinema poster thumbnail...", "INFO")
                ai_image_path = await asyncio.to_thread(
                    generate_ai_image_with_9router,
                    prompt,
                    "1280x720",
                    str(THUMBNAILS_DIR),
                )
                if ai_image_path and os.path.exists(ai_image_path):
                    log_event("✨ 9Router AI Photorealistic Cinema Poster generated successfully!", "SUCCESS")
        except Exception as e:
            print(f"[9Router AI Thumbnail Endpoint Notice] {e}")

        log_event("🔍 Analyzing timeline sharpness & extracting 3 milestone scene frames...", "INFO")
        thumbnails = ThumbnailEngine.generate_3_thumbnail_options(
            video_path=raw_video_path,
            job_id=job_id,
            movie_title=movie_title,
            lang=language,
            plot_summary=plot_summary or "",
            ai_image_path=ai_image_path,
            youtube_url=url
        )

        log_event(f"✅ 3 High-CTR A/B test thumbnails successfully generated in {language.upper()}!", "SUCCESS")
        return {
            "success": True,
            "job_id": job_id,
            "movie_title": movie_title,
            "language": language,
            "thumbnails": thumbnails
        }
    finally:
        if os.path.exists(raw_video_path):
            try: os.remove(raw_video_path)
            except Exception: pass
        cleanup_job_temp_files(job_id)

@router.get("/config")
def get_explainer_config():
    """Returns supported languages, story personas, mood themes, genres, and audio modes."""
    return {
        "languages": SUPPORTED_LANGUAGES,
        "personas": STORY_PERSONAS,
        "mood_themes": MOOD_THEMES,
        "genres": CONTENT_GENRES,
        "audio_modes": AUDIO_MODES
    }

@router.post("/generate-script")
async def generate_script_endpoint(
    url: Optional[str] = Form(None),
    title: Optional[str] = Form("Movie Story Explanation"),
    plot_summary: Optional[str] = Form(""),
    language: str = Form("en"),
    persona: str = Form("hollywood_trailer"),
    mood: str = Form("suspense"),
    duration_mins: int = Form(3),
    spoiler_mode: str = Form("full_recap"),
    format_mode: str = Form("reels_parts"),
    num_parts: int = Form(3),
    voice_speed: str = Form("fast"),
    genre: str = Form("movie_recap"),
    ai_provider: Optional[str] = Form("auto"),
    openai_api_key: Optional[str] = Form(None),
    local_file: Optional[UploadFile] = File(None),
    custom_transcript: Optional[str] = Form(None)
):
    """
    Analyzes video context / subtitles and writes a high-converting, viral storytelling script for any genre.
    """
    job_id = str(uuid.uuid4())[:8]
    desc = ""
    subs = ""
    movie_title = title
    if local_file and local_file.filename:
        clean_local = os.path.splitext(local_file.filename)[0].replace('_', ' ').replace('-', ' ').strip()
        if not movie_title or movie_title in ["Movie Story Explanation", "Movie Story Recap"]:
            movie_title = clean_local

    log_event(f"🧠 Script request received for '{movie_title}' [Genre: {genre}] in {language.upper()} ({persona}, Speed: {voice_speed})", "INFO")

    source_dur = 0.0
    dialogue_timeline = []
    transcript_source = "none"
    if custom_transcript and custom_transcript.strip():
        log_event(f"📋 Ingesting user-pasted transcript ({len(custom_transcript)} chars) directly...", "INFO")
        parsed_t = VideoEngine.parse_raw_transcript_text(custom_transcript)
        subs = parsed_t.get("subtitles_text", "")
        source_dur = float(parsed_t.get("total_duration", 0) or 0)
        dialogue_timeline = parsed_t.get("dialogue_timeline", [])
        transcript_source = "user_transcript"
        log_event(f"⚡ Instant transcript processed! {len(dialogue_timeline)} timed cues mapped. Bypassing YouTube download delay!", "SUCCESS")
    elif url and ("youtube.com" in url or "youtu.be" in url):
        log_event(f"🌐 Fetching metadata & subtitles from YouTube: {url[:50]}...", "INFO")
        info = VideoEngine.extract_youtube_info(url, str(TEMP_DIR), job_id)
        movie_title = info.get("title", movie_title)
        desc = info.get("description", "")
        subs = info.get("subtitles_text", "")
        source_dur = float(info.get("duration", 0) or 0)
        dialogue_timeline = info.get("dialogue_timeline", [])
        if subs:
            transcript_source = "existing_subtitles"
            log_event(f"📝 Extracted {len(subs)} characters of dialogue transcripts & timeline milestones (Source: {round(source_dur/60, 1)}m)", "INFO")

    # Priority 3: Automated ASR Ingestion (Phase 6A) if no usable transcript exists
    if not dialogue_timeline:
        asr_media_path = None
        cleanup_asr_media = False
        if local_file and local_file.filename:
            clean_ext = os.path.splitext(local_file.filename)[1].lower() or ".mp4"
            asr_media_path = str(TEMP_DIR / f"{job_id}_local_media{clean_ext}")
            save_upload_with_limit(local_file, asr_media_path, MAX_VIDEO_BYTES)
            cleanup_asr_media = True

        if asr_media_path and os.path.exists(asr_media_path):
            log_event("🎙️ No subtitles found. Invoking Automated Speech Recognition (ASR) on source media...", "INFO")
            from app.services.asr_engine import ASREngine
            try:
                asr_cues, asr_subs, asr_src = await asyncio.to_thread(
                    ASREngine.transcribe_media_to_dialogue,
                    media_path=asr_media_path,
                    temp_dir=str(TEMP_DIR),
                    job_id=job_id
                )
                if asr_cues:
                    dialogue_timeline = asr_cues
                    subs = asr_subs
                    transcript_source = asr_src
                    if source_dur <= 0:
                        source_dur = VideoEngine.get_duration(asr_media_path)
                    log_event(f"⚡ ASR successfully extracted {len(dialogue_timeline)} dialogue cues (transcript_source=asr)", "SUCCESS")
                else:
                    log_event("⚠️ ASR produced no usable dialogue cues, continuing with non-transcript fallback", "WARNING")
            except Exception as e:
                log_event(f"⚠️ ASR invocation failed ({e}), continuing with non-transcript fallback", "WARNING")
            finally:
                if cleanup_asr_media and os.path.exists(asr_media_path):
                    try:
                        os.remove(asr_media_path)
                    except OSError:
                        pass

    if persona == "auto" or mood == "auto" or genre == "auto" or spoiler_mode == "auto":
        detected = ScriptEngine.auto_detect_creative_context(
            title=movie_title,
            description=desc,
            transcript_sample=subs[:1000] if subs else (plot_summary[:500] if plot_summary else "")
        )
        if persona == "auto":
            persona = detected.get("persona", "hollywood_trailer")
        if mood == "auto":
            mood = detected.get("mood", "suspense")
        if genre == "auto":
            genre = detected.get("genre", "movie_recap")
        if spoiler_mode == "auto":
            spoiler_mode = detected.get("spoiler_mode", "full_recap")
        log_event(f"✨ Auto-detected creative context: Genre='{genre}', Persona='{persona}', Mood='{mood}'", "INFO")

    result = ScriptEngine.generate_script(
        title=movie_title,
        description=desc,
        subs_text=subs,
        target_lang=language,
        persona=persona,
        mood=mood,
        format_mode=format_mode,
        num_parts=num_parts,
        duration_mins=duration_mins,
        spoiler_mode=spoiler_mode,
        plot_summary=plot_summary,
        voice_speed=voice_speed,
        genre=genre,
        source_video_duration_sec=source_dur,
        openai_api_key=openai_api_key,
        ai_provider=ai_provider or "auto",
        dialogue_timeline=dialogue_timeline
    )

    raw_hook = result.get("hook_score", 0)
    h_score = raw_hook.get("score", 0) if isinstance(raw_hook, dict) else (raw_hook or 0)
    log_event(f"✍️ Storyboard script ready! ({result.get('actual_words', result.get('target_words', 0))} words • Hook Score: {h_score}/100)", "SUCCESS")
    result["title"] = movie_title
    result["transcript_source"] = transcript_source
    return result


@router.post("/expand-script")
async def expand_script_endpoint(
    script: str = Form(...),
    language: str = Form("en"),
    duration_mins: int = Form(10),
    voice_speed: str = Form("fast"),
    genre: str = Form("movie_recap")
):
    """
    Expands an existing script to meet the required full-length word count.
    """
    if not script.strip():
        raise HTTPException(status_code=400, detail="Script text cannot be empty.")
    
    log_event(f"⚡ Expanding script to full {duration_mins}-minute length in {language.upper()}...", "INFO")
    res = ScriptEngine.expand_script(
        current_script=script.strip(),
        target_lang=language,
        duration_mins=duration_mins,
        voice_speed=voice_speed,
        genre=genre
    )
    if res.get("success"):
        log_event(f"✅ Script expanded successfully! ({res.get('actual_words', 0)} words)", "SUCCESS")
    return res

@router.post("/translate-scripts")
async def translate_scripts_endpoint(
    base_script: Optional[str] = Form(None),
    primary_script: Optional[str] = Form(None),
    target_languages: Optional[str] = Form(None),
    languages: Optional[str] = Form(None),
    base_language: Optional[str] = Form("en")
):
    """
    Translates primary script across all selected languages in advance so creators
    can preview, inspect and edit scripts in the Multi-Script Deck before rendering.
    """
    text = (base_script or primary_script or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Must provide base_script or primary_script.")

    langs_str = target_languages or languages or "en,es,ur"
    lang_list = [l.strip() for l in langs_str.split(",") if l.strip()]
    if not lang_list:
        lang_list = ["en"]

    scripts_map = ScriptEngine.translate_script_to_languages(text, lang_list)
    return {
        "success": True,
        "translated_scripts": scripts_map,
        "scripts": scripts_map
    }

@router.post("/preview-voice")
async def preview_voice_endpoint(
    voice: str = Form(...),
    language: str = Form("en")
):
    """Generates an instant 5-second voice audition sample."""
    filename = await VoiceEngine.generate_preview(voice, language)
    if filename:
        return {"success": True, "preview_url": f"/outputs/temp/{filename}"}
    raise HTTPException(status_code=500, detail="Voice audition synthesis failed.")

@router.post("/render-video")
async def render_video_endpoint(
    script_text: str = Form(...),
    language: str = Form("en"),
    url: Optional[str] = Form(None),
    voice: Optional[str] = Form(None),
    voice_speed: str = Form("fast"),
    voice_mode: str = Form("ai"), # 'ai', 'custom_audio', 'clone'
    aspect_ratio: str = Form("vertical"),
    mood_theme: str = Form("suspense"),
    burn_subtitles: bool = Form(True),
    watermark: Optional[str] = Form(""),
    title: Optional[str] = Form("Movie Story Recap"),
    genre: str = Form("movie_recap"),
    audio_mode: str = Form("hybrid"),
    resolution: str = Form("720p"),
    transcript_text: Optional[str] = Form(None),
    local_file: Optional[UploadFile] = File(None),
    custom_audio_file: Optional[UploadFile] = File(None),
    clone_sample_file: Optional[UploadFile] = File(None)
):
    """
    Full-Auto End-to-End Explainer Video Pipeline:
    1. Parse narration & scene timestamps from script (Dialogue-Anchored).
    2. Handle Voiceover Audio (AI Neural / Custom PC Upload / Cloned Voice).
    3. Slice video scenes matching audio duration.
    4. Mix ducked mood background score.
    5. Render final video.
    6. Generate 3 viral thumbnail options (Option 3).
    7. Generate YouTube & TikTok viral metadata suite.
    """
    validate_uploaded_media(local_file, is_video=True)
    validate_uploaded_media(custom_audio_file, is_video=False)
    validate_uploaded_media(clone_sample_file, is_video=False)

    job_id = str(uuid.uuid4())[:8]
    chosen_voice = voice or VoiceEngine.get_default_voice_for_lang(language)

    # 1. Ingest Video Source
    raw_video_path = str(UPLOADS_DIR / f"{job_id}_raw.mp4")
    speech_path = str(TEMP_DIR / f"{job_id}_speech.mp3")
    video_slice_path = str(TEMP_DIR / f"{job_id}_sliced.mp4")
    mixed_audio_path = str(TEMP_DIR / f"{job_id}_mixed.mp3")
    movie_title = title or "Movie Story Recap"
    if mood_theme == "auto" or genre == "auto":
        detected = ScriptEngine.auto_detect_creative_context(
            title=movie_title,
            transcript_sample=script_text[:1000]
        )
        if mood_theme == "auto":
            mood_theme = detected.get("mood", "suspense")
        if genre == "auto":
            genre = detected.get("genre", "movie_recap")
        log_event(f"✨ Auto-detected creative context: Genre='{genre}', Mood='{mood_theme}'", "INFO")

    log_event(f"🚀 Render pipeline triggered for '{movie_title}' [Genre: {genre}, Audio: {audio_mode.upper()}] in {language.upper()} ({aspect_ratio})", "INFO")

    try:
        # 1. Parse Storyboard Script and Anchor Scenes to Dialogue
        dialogue_timeline = []
        transcript_source = "none"
        raw_transcript = (transcript_text or "").strip()
        if raw_transcript:
            parsed_trans = VideoEngine.parse_raw_transcript_text(raw_transcript)
            dialogue_timeline = parsed_trans.get("dialogue_timeline", [])
            transcript_source = "user_transcript"
        elif url and VideoEngine.is_valid_youtube_url(url):
            try:
                info = VideoEngine.extract_youtube_info(url, str(TEMP_DIR), job_id)
                subs_raw = info.get("subtitles_text", "")
                if subs_raw:
                    parsed_trans = VideoEngine.parse_raw_transcript_text(subs_raw)
                    dialogue_timeline = parsed_trans.get("dialogue_timeline", [])
                    transcript_source = "existing_subtitles"
            except Exception as e:
                log_event(f"⚠️ Subtitle/dialogue extraction failed, continuing without dialogue timeline: {e}", "WARNING")

        # Phase 6A: Ingest local video early if needed so ASR can run when no subtitles exist
        if local_file and local_file.filename and not os.path.exists(raw_video_path):
            log_event(f"📁 Ingesting local video file: {local_file.filename}", "INFO")
            save_upload_with_limit(local_file, raw_video_path, MAX_VIDEO_BYTES)
            movie_title = os.path.splitext(local_file.filename)[0]

        # Phase 6A: If still no dialogue timeline, attempt ASR on available media
        if not dialogue_timeline:
            media_for_asr = None
            try:
                if raw_video_path and os.path.exists(raw_video_path) and os.path.getsize(raw_video_path) > 0:
                    media_for_asr = raw_video_path
            except OSError:
                media_for_asr = None
            if media_for_asr:
                log_event("🎙️ No subtitles found. Invoking ASR on local media for scene synchronization...", "INFO")
                from app.services.asr_engine import ASREngine
                try:
                    asr_cues, asr_subs, asr_src = await asyncio.to_thread(
                        ASREngine.transcribe_media_to_dialogue,
                        media_path=media_for_asr,
                        temp_dir=str(TEMP_DIR),
                        job_id=job_id
                    )
                    if asr_cues:
                        dialogue_timeline = asr_cues
                        transcript_source = asr_src
                        log_event(f"⚡ ASR generated {len(dialogue_timeline)} dialogue cues for scene grounding (transcript_source=asr)", "SUCCESS")
                except Exception as e:
                    log_event(f"⚠️ ASR invocation failed ({e}), continuing with non-transcript fallback", "WARNING")

        clean_narration, scene_ranges, scene_subs = ScriptEngine.parse_storyboard(script_text)
        embedding_prov = ScriptEngine.get_configured_embedding_provider()
        scene_blocks = ScriptEngine.parse_storyboard_blocks(
            script_text,
            dialogue_timeline=dialogue_timeline,
            embedding_provider=embedding_prov,
            transcript_source=transcript_source
        )
        if scene_blocks:
            scene_ranges = [(b.movie_start, b.movie_end) for b in scene_blocks]
        if not clean_narration:
            clean_narration = script_text.strip()
        if dialogue_timeline:
            log_event(f"🎯 Dialogue-Anchored Synchronization: Matched {len(scene_blocks)} scene blocks to actual dialogue moments in movie", "INFO")
        log_event(f"📝 Parsed narrative script: {len(clean_narration.split())} words, {len(scene_ranges)} scene cuts, {len(scene_blocks)} scene blocks", "INFO")

        # 2. Handle Voiceover Audio First (Mode A: AI Voice, Mode B: Custom Audio, Mode C: Cloned Voice)
        speech_path = str(TEMP_DIR / f"{job_id}_speech.mp3")
        rate_val = "+18%" if voice_speed == "ultra_fast" else ("+15%" if voice_speed == "fast" else "+0%")
        pitch_val = "-12Hz"  # Cinema Trailer Pitch Booster

        if voice_mode == "custom_audio" and custom_audio_file and custom_audio_file.filename:
            ext = os.path.splitext(custom_audio_file.filename)[1].lower() or ".mp3"
            custom_target = str(TEMP_DIR / f"{job_id}_custom_audio{ext}")
            save_upload_with_limit(custom_audio_file, custom_target, MAX_AUDIO_BYTES)
            speech_path = custom_target
            log_event(f"📁 Using pre-recorded custom audio file from PC: {custom_audio_file.filename}", "INFO")
        elif voice_mode == "clone" and clone_sample_file and clone_sample_file.filename:
            ext = os.path.splitext(clone_sample_file.filename)[1].lower() or ".mp3"
            sample_path = str(TEMP_DIR / f"{job_id}_clone_sample{ext}")
            save_upload_with_limit(clone_sample_file, sample_path, MAX_AUDIO_BYTES)
            log_event("⚡ Synthesizing script using custom AI Voice Clone profile...", "INFO")
            clone_ok = await VoiceEngine.synthesize_cloned_story(clean_narration, language, speech_path, rate=rate_val)
            if not clone_ok or not os.path.exists(speech_path):
                log_event("⚠️ Cloned voice synthesis fell back to neural voice", "WARNING")
                await VoiceEngine.synthesize_speech(clean_narration, chosen_voice, speech_path, rate=rate_val, pitch=pitch_val)
        else:
            # Default AI Voiceover
            log_event(f"🎙️ Synthesizing Neural AI voiceover narration [{chosen_voice}, speed: {rate_val}]...", "INFO")
            tts_ok = await VoiceEngine.synthesize_speech(clean_narration, chosen_voice, speech_path, rate=rate_val, pitch=pitch_val)
            if not tts_ok or not os.path.exists(speech_path):
                log_event("❌ Voiceover synthesis failed", "ERROR")
                raise HTTPException(status_code=500, detail="Voiceover synthesis failed. Check language and voice selection.")

        speech_dur = VoiceEngine.get_audio_duration(speech_path)
        if speech_dur <= 0.5:
            speech_dur = VideoEngine.get_duration(speech_path)
        log_event(f"⏱️ Voiceover audio ready: {round(speech_dur, 1)}s duration. Auto-syncing timeline scenes!", "INFO")

        # Exact Narration-to-Scene Time-Lock using authoritative Edge-TTS sentence boundary cues
        speech_cues = VoiceEngine.get_speech_cues(speech_path)
        if scene_blocks:
            scene_blocks = ScriptEngine.assign_narration_timing(scene_blocks, speech_dur, speech_cues)
            log_event(f"🔒 Locked exact narration-to-scene timing across {len(scene_blocks)} scene blocks (Zero Drift)", "INFO")

        # 3. Ingest Video Source with Bulletproof Footage Integrity
        if local_file and local_file.filename:
            if not os.path.exists(raw_video_path):
                log_event(f"📁 Ingesting local video file: {local_file.filename}", "INFO")
                save_upload_with_limit(local_file, raw_video_path, MAX_VIDEO_BYTES)
                movie_title = os.path.splitext(local_file.filename)[0]
        elif url:
            log_event("🌐 Ensuring footage integrity from YouTube...", "INFO")
            raw_video_path = await asyncio.to_thread(
                VideoEngine.ensure_footage_integrity,
                url=url,
                job_id=job_id,
                speech_dur=speech_dur,
                temp_dir=str(TEMP_DIR),
                resolution=resolution,
                scene_ranges=scene_ranges
            )
        else:
            raise HTTPException(status_code=400, detail="Must provide either a YouTube URL or a video file.")

        raw_dur = VideoEngine.get_duration(raw_video_path) if (raw_video_path and os.path.exists(raw_video_path)) else 0.0

        # 4. Slice & Assemble Video — Audio-Locked (each clip duration == narration window)
        video_slice_path = str(TEMP_DIR / f"{job_id}_slice.mp4")
        log_event(f"🎬 Building {len(scene_blocks)} audio-locked scene clips (narration-to-visual deterministic sync)...", "INFO")
        assembled_video = await asyncio.to_thread(
            VideoEngine.build_audio_locked_scene_clips,
            input_video=raw_video_path,
            scene_blocks=scene_blocks,
            temp_dir=str(TEMP_DIR),
            job_id=job_id,
            output_video=video_slice_path,
        )
        # Fallback: legacy slice if audio-locked produced no output
        if not assembled_video or not os.path.exists(assembled_video):
            expected_cuts = max(8, int(round(speech_dur / 3.8)))
            log_event(f"⚠️ Audio-locked sync fallback: slicing ~{expected_cuts} narrative cuts...", "WARNING")
            assembled_video = await asyncio.to_thread(
                VideoEngine.slice_and_assemble_scenes,
                input_video=raw_video_path,
                scene_ranges=scene_ranges,
                target_duration=speech_dur,
                output_video=video_slice_path,
                temp_dir=str(TEMP_DIR),
                job_id=job_id,
                scene_blocks=scene_blocks
            )

        # 5. Compose Soundscape (Hybrid, SFX Only, or Music Only)
        log_event(f"🎵 Composing soundtrack [{audio_mode.upper()} • {genre} • Mood: {mood_theme}]...", "INFO")
        bgm_track = AudioMixer.get_mood_music_track(mood_theme)
        if not bgm_track and audio_mode != "sfx_only":
            procedural_bgm = str(TEMP_DIR / f"{job_id}_procedural.mp3")
            AudioMixer.generate_procedural_synth(procedural_bgm, speech_dur + 3.0, mood=mood_theme)
            bgm_track = procedural_bgm

        mixed_audio_path = str(TEMP_DIR / f"{job_id}_master_audio.mp3")
        ai_sfx_cues = ScriptEngine.extract_sfx_cues(script_text, total_duration=speech_dur)
        if ai_sfx_cues:
            log_event(f"✨ Integrated {len(ai_sfx_cues)} AI Sound Designer cues into soundtrack timeline", "INFO")

        await asyncio.to_thread(
            AudioMixer.mix_soundtrack,
            voice_path=speech_path,
            bgm_path=bgm_track,
            output_path=mixed_audio_path,
            voice_duration=speech_dur,
            audio_mode=audio_mode,
            scene_starts=[s for s, _ in scene_ranges],
            genre=genre,
            bgm_volume=0.14,
            explicit_sfx_cues=ai_sfx_cues
        )
        final_audio = mixed_audio_path if os.path.exists(mixed_audio_path) else speech_path

        # 6. Render Final Video
        final_filename = f"explainer_{job_id}_{language}.mp4"
        final_video_path = str(OUTPUTS_DIR / final_filename)
        sub_log_txt = "burnt-in subtitles" if burn_subtitles else "clean visuals, subtitles unburned"
        log_event(f"🛡️ FFmpeg rendering anti-copyright armor ({aspect_ratio} • {sub_log_txt})...", "INFO")

        speech_cues = VoiceEngine.get_speech_cues(speech_path)
        render_ok = await asyncio.to_thread(
            VideoEngine.render_final_explainer,
            video_source=assembled_video,
            audio_source=final_audio,
            output_path=final_video_path,
            duration=speech_dur,
            aspect_ratio=aspect_ratio,
            burn_subtitles=burn_subtitles,
            scene_subtitles=scene_subs,
            watermark=watermark or "",
            part_number=1,
            lang=language,
            timed_cues=speech_cues
        )

        if not render_ok or not os.path.exists(final_video_path):
            log_event("❌ Video rendering assembly failed", "ERROR")
            raise HTTPException(status_code=500, detail="Video rendering assembly failed.")

        # 7. Generate 3 Viral Thumbnail Variations (Option 3) with 9Router AI Strategy & AI Cinema Poster
        ai_target_timestamps = None
        ai_image_path = None
        try:
            from app.services.nine_router_client import (
                is_ninerouter_available,
                generate_ai_thumbnail_strategy_with_9router,
                craft_cinematic_thumbnail_prompt,
                generate_ai_image_with_9router
            )
            if await asyncio.to_thread(is_ninerouter_available, 3.0):
                if scene_ranges:
                    mock_beats = [
                        {
                            "beat": i + 1,
                            "timestamp": f"{int(s // 60):02d}:{int(s % 60):02d} - {int(e // 60):02d}:{int(e % 60):02d}",
                            "title": f"Scene {i + 1}"
                        }
                        for i, (s, e) in enumerate(scene_ranges)
                    ]
                    strategy = await asyncio.to_thread(
                        generate_ai_thumbnail_strategy_with_9router,
                        title=movie_title,
                        story_beats=mock_beats,
                        target_lang=language,
                    )
                    if strategy and "best_timestamp_sec" in strategy:
                        ai_target_timestamps = [float(strategy["best_timestamp_sec"])]
                        log_event(f"🎯 9Router AI Art Director picked climax timestamp: {strategy.get('best_timestamp_formatted', ai_target_timestamps[0])}", "INFO")

                prompt = craft_cinematic_thumbnail_prompt(
                    title=movie_title,
                    plot_summary=clean_narration[:400],
                    genre=genre
                )
                log_event("🎨 Generating 9Router photorealistic cinema poster thumbnail...", "INFO")
                ai_image_path = await asyncio.to_thread(
                    generate_ai_image_with_9router,
                    prompt=prompt,
                    size="1280x720",
                    output_dir=str(THUMBNAILS_DIR)
                )
                if ai_image_path and os.path.exists(ai_image_path):
                    log_event("✨ 9Router AI Photorealistic Cinema Poster generated successfully!", "SUCCESS")
        except Exception as e:
            print(f"[AI Thumbnail Director Warning] {e}")

        final_target_timestamps = ai_target_timestamps or ([s for s, _ in scene_ranges] if scene_ranges else None)
        log_event(f"🖼️ Rendering 3 High-CTR A/B test thumbnails in {language.upper()}...", "INFO")
        thumbnails = await asyncio.to_thread(
            ThumbnailEngine.generate_3_thumbnail_options,
            video_path=raw_video_path,
            job_id=job_id,
            movie_title=movie_title,
            lang=language,
            target_timestamps=final_target_timestamps,
            plot_summary=clean_narration[:400],
            ai_image_path=ai_image_path,
            youtube_url=url
        )

        # 8. Generate Social Media Metadata Suite
        log_event("📦 Generating YouTube & TikTok viral metadata suite...", "INFO")
        metadata_pack = MetadataEngine.generate_viral_metadata(
            movie_title=movie_title,
            script_snippet=clean_narration[:400],
            lang=language
        )
        log_event(f"🎉 Complete Explainer Package Ready: '{final_filename}' ({round(speech_dur, 1)}s)!", "SUCCESS")

        return {
            "success": True,
            "job_id": job_id,
            "video_filename": final_filename,
            "video_url": f"/outputs/{final_filename}",
            "duration": round(speech_dur, 1),
            "aspect_ratio": aspect_ratio,
            "thumbnails": thumbnails,
            "metadata_pack": metadata_pack
        }
    except HTTPException:
        raise
    except Exception as exc:
        log_event(f"❌ Pipeline processing error: {exc}", "ERROR")
        raise HTTPException(status_code=500, detail=f"Pipeline processing error: {str(exc)}")
    finally:
        # Guaranteed cleanup of all intermediate working files
        for p in [speech_path, video_slice_path, mixed_audio_path, raw_video_path]:
            if p and os.path.exists(p):
                try: os.remove(p)
                except Exception: pass
        # Catch-all: any other job-scoped temp/upload leftovers
        cleanup_job_temp_files(job_id)


@router.post("/update-thumbnail")
async def update_thumbnail_endpoint(
    filename: str = Form(...),
    hook_text: str = Form(...),
    language: str = Form("en"),
    badge: str = Form("🎬 RECAP")
):
    """
    Live Interactive Thumbnail Editor:
    Re-renders the thumbnail with custom typed hook text and returns the fresh image URL.
    """
    clean_fn = os.path.basename(filename).strip()
    if not re.match(r"^[a-zA-Z0-9_-]+\.jpg$", clean_fn, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Invalid thumbnail filename format.")

    updated_url = ThumbnailEngine.re_render_thumbnail(
        filename=clean_fn,
        new_hook_text=hook_text,
        lang=language,
        badge_label=badge
    )
    if updated_url:
        return {"success": True, "updated_url": updated_url}
    raise HTTPException(status_code=400, detail="Thumbnail base frame not found or invalid path.")


@router.post("/render-batch")
async def render_batch_endpoint(
    script_text: str = Form(...),
    languages: str = Form("en,es,ur"),
    export_mode: str = Form("youtube_audio_pack"),
    url: Optional[str] = Form(None),
    voice_speed: str = Form("fast"),
    aspect_ratio: str = Form("vertical"),
    mood_theme: str = Form("suspense"),
    burn_subtitles: bool = Form(True),
    watermark: Optional[str] = Form(""),
    title: Optional[str] = Form("Movie Story Recap"),
    genre: str = Form("movie_recap"),
    audio_mode: str = Form("hybrid"),
    scripts_json: Optional[str] = Form(None),
    voices_json: Optional[str] = Form(None),
    transcript_text: Optional[str] = Form(None),
    local_file: Optional[UploadFile] = File(None)
):
    """
    1-Click Multi-Language Multiplier Engine:
    Mode A: 'youtube_audio_pack' (1 Master Video + Multi-Language Dubs + SRT Subtitles) - 80% faster, YouTube native.
    Mode B: 'independent_videos' (Full separate MP4s per language) - For multi-channel creators.
    """
    validate_uploaded_media(local_file, is_video=True)

    job_id = str(uuid.uuid4())[:8]
    lang_list = [l.strip() for l in languages.split(",") if l.strip() and l.strip() in SUPPORTED_LANGUAGES]
    if not lang_list:
        lang_list = ["en"]

    # Parse dialogue timeline from transcript if provided
    dialogue_timeline = []
    raw_trans = (transcript_text or "").strip()
    if raw_trans:
        parsed_trans = VideoEngine.parse_raw_transcript_text(raw_trans)
        dialogue_timeline = parsed_trans.get("dialogue_timeline", [])
    elif url and VideoEngine.is_valid_youtube_url(url):
        try:
            info = VideoEngine.extract_youtube_info(url, str(TEMP_DIR), job_id)
            subs_raw = info.get("subtitles_text", "")
            if subs_raw:
                parsed_trans = VideoEngine.parse_raw_transcript_text(subs_raw)
                dialogue_timeline = parsed_trans.get("dialogue_timeline", [])
        except Exception as e:
            log_event(f"⚠️ [Batch] Subtitle/dialogue extraction failed for job {job_id}, continuing without it: {e}", "WARNING")

    # Parse pre-translated scripts and custom voices if provided
    pre_scripts: Dict[str, str] = {}
    if scripts_json:
        try:
            pre_scripts = json.loads(scripts_json)
        except Exception as pe:
            print(f"[scripts_json parse error] {pe}")

    custom_voices: Dict[str, str] = {}
    if voices_json:
        try:
            custom_voices = json.loads(voices_json)
        except Exception as pe:
            print(f"[voices_json parse error] {pe}")

    # 1. Ingest Video Source Once
    raw_video_path = str(UPLOADS_DIR / f"{job_id}_batch_raw.mp4")
    movie_title = title or "Movie Story Recap"
    master_video_filename = None
    master_video_url = None

    try:
        if local_file and local_file.filename:
            save_upload_with_limit(local_file, raw_video_path, MAX_VIDEO_BYTES)
            movie_title = os.path.splitext(local_file.filename)[0]
        elif url:
            dl_ok = VideoEngine.download_youtube_video(url, raw_video_path)
            if not dl_ok or not os.path.exists(raw_video_path):
                raise HTTPException(status_code=400, detail="Failed to download YouTube video.")
        else:
            raise HTTPException(status_code=400, detail="Must provide either a YouTube URL or video file.")

        # Phase 6A: ASR for batch endpoint if no dialogue timeline exists
        if not dialogue_timeline and raw_video_path and os.path.exists(raw_video_path):
            from app.services.asr_engine import ASREngine
            try:
                asr_cues, asr_subs, asr_src = await asyncio.to_thread(
                    ASREngine.transcribe_media_to_dialogue,
                    media_path=raw_video_path,
                    temp_dir=str(TEMP_DIR),
                    job_id=job_id
                )
                if asr_cues:
                    dialogue_timeline = asr_cues
                    log_event(f"⚡ [Batch] ASR extracted {len(dialogue_timeline)} dialogue cues (transcript_source=asr)", "SUCCESS")
            except Exception as e:
                log_event(f"⚠️ [Batch] ASR invocation failed: {e}", "WARNING")

        results_by_lang = {}

        # Mode A: YouTube Multi-Audio Pack (1 Master Video + Synced Dub Tracks + SRTs)
        if export_mode == "youtube_audio_pack":
            log_event(f"🎬 Processing YouTube Multi-Audio Pack for '{movie_title}' across {len(lang_list)} languages...", "INFO")
            
            # Baseline language for timing (use first selected language)
            base_lang = lang_list[0]
            base_script = pre_scripts.get(base_lang, script_text)
            clean_base_narr, base_scene_ranges, base_scene_subs = ScriptEngine.parse_storyboard(base_script)
            if not clean_base_narr:
                clean_base_narr = base_script.strip()

            base_voice = custom_voices.get(base_lang) or VoiceEngine.get_default_voice_for_lang(base_lang)
            base_speech_path = str(TEMP_DIR / f"{job_id}_{base_lang}_speech.mp3")
            rate_val = "+20%" if voice_speed == "ultra_fast" else ("+15%" if voice_speed == "fast" else "+0%")
            
            await VoiceEngine.synthesize_speech(clean_base_narr, base_voice, base_speech_path, rate=rate_val, pitch="-12Hz")
            base_duration = VideoEngine.get_duration(base_speech_path) if os.path.exists(base_speech_path) else 60.0
            base_speech_cues = VoiceEngine.get_speech_cues(base_speech_path)
            embedding_prov = ScriptEngine.get_configured_embedding_provider()
            base_scene_blocks = ScriptEngine.parse_storyboard_blocks(
                base_script,
                dialogue_timeline=dialogue_timeline,
                embedding_provider=embedding_prov
            )
            if base_scene_blocks:
                base_scene_blocks = ScriptEngine.assign_narration_timing(base_scene_blocks, base_duration, base_speech_cues)

            # 1. Slice master video — Audio-Locked (deterministic A/V sync)
            master_slice_path = str(TEMP_DIR / f"{job_id}_master_slice.mp4")
            assembled_master = VideoEngine.build_audio_locked_scene_clips(
                input_video=raw_video_path,
                scene_blocks=base_scene_blocks,
                temp_dir=str(TEMP_DIR),
                job_id=f"{job_id}_master",
                output_video=master_slice_path,
            )
            if not assembled_master or not os.path.exists(assembled_master):
                assembled_master = VideoEngine.slice_and_assemble_scenes(
                    input_video=raw_video_path,
                    scene_ranges=base_scene_ranges,
                    target_duration=base_duration,
                    output_video=master_slice_path,
                    temp_dir=str(TEMP_DIR),
                    job_id=f"{job_id}_master",
                    scene_blocks=base_scene_blocks
                )

            # 2. Render 1 Clean Master Video (1080p, no burnt-in subtitles so multi-audio viewers see clean visuals)
            master_video_filename = f"AutoExplainer_{job_id}_MASTER.mp4"
            master_video_path = str(OUTPUTS_DIR / master_video_filename)
            
            # Master video audio track (AudioMixer soundscape)
            bgm_track = AudioMixer.get_mood_music_track(mood_theme)
            if not bgm_track and audio_mode != "sfx_only":
                procedural_bgm = str(TEMP_DIR / f"{job_id}_master_bgm.mp3")
                AudioMixer.generate_procedural_synth(procedural_bgm, base_duration + 3.0, mood=mood_theme)
                bgm_track = procedural_bgm

            base_sfx_cues = ScriptEngine.extract_sfx_cues(base_script, total_duration=base_duration)
            master_audio_mixed = str(TEMP_DIR / f"{job_id}_master_mixed.mp3")
            AudioMixer.mix_soundtrack(
                voice_path=base_speech_path,
                bgm_path=bgm_track,
                output_path=master_audio_mixed,
                voice_duration=base_duration,
                audio_mode=audio_mode,
                scene_starts=[s for s, _ in base_scene_ranges],
                genre=genre,
                bgm_volume=0.14,
                explicit_sfx_cues=base_sfx_cues
            )
            primary_audio = master_audio_mixed if os.path.exists(master_audio_mixed) else base_speech_path

            VideoEngine.render_final_explainer(
                video_source=assembled_master,
                audio_source=primary_audio,
                output_path=master_video_path,
                duration=base_duration,
                aspect_ratio=aspect_ratio,
                burn_subtitles=False,  # Clean visuals for YouTube Multi-Audio
                scene_subtitles=[],
                watermark=watermark or "",
                part_number=1,
                lang=base_lang
            )
            master_video_url = f"/outputs/{master_video_filename}"

            # Cleanup master slices
            for mp in [base_speech_path, master_slice_path, master_audio_mixed]:
                if mp and os.path.exists(mp):
                    try: os.remove(mp)
                    except Exception: pass

            # 3. For each language: Generate Synced Dub Track (.mp3), SRT file, Thumbnails & SEO
            for lang in lang_list:
                try:
                    if lang in pre_scripts and pre_scripts[lang] and pre_scripts[lang].strip():
                        localized_script = pre_scripts[lang].strip()
                    else:
                        localized_script = script_text
                        if lang != "en":
                            try:
                                from deep_translator import GoogleTranslator
                                localized_script = GoogleTranslator(source="auto", target=lang).translate(script_text)
                            except Exception as e:
                                log_event(f"⚠️ [Batch] Translation to '{lang}' failed, using original script: {e}", "WARNING")

                    clean_narr, _, _ = ScriptEngine.parse_storyboard(localized_script)
                    if not clean_narr:
                        clean_narr = localized_script.strip()

                    chosen_voice = custom_voices.get(lang) or VoiceEngine.get_default_voice_for_lang(lang)
                    speech_path = str(TEMP_DIR / f"{job_id}_{lang}_speech.mp3")

                    tts_ok = await VoiceEngine.synthesize_speech(clean_narr, chosen_voice, speech_path, rate=rate_val, pitch="-12Hz")
                    if not tts_ok or not os.path.exists(speech_path):
                        continue

                    # Create YouTube Studio-Ready Full Dub Track (.mp3)
                    dub_filename = f"AutoExplainer_AUDIO_{job_id}_{lang}.mp3"
                    dub_path = str(OUTPUTS_DIR / dub_filename)
                    AudioMixer.create_isolated_dub_track(
                        voice_path=speech_path,
                        bgm_path=bgm_track if audio_mode != "sfx_only" else None,
                        output_path=dub_path,
                        target_duration=base_duration,
                        bgm_volume=0.16
                    )

                    # Create SRT Subtitles file synchronized with exact speech cues
                    loc_speech_cues = VoiceEngine.get_speech_cues(speech_path)
                    srt_filename = f"AutoExplainer_SUBS_{job_id}_{lang}.srt"
                    srt_path = str(OUTPUTS_DIR / srt_filename)
                    SubtitleEngine.save_srt_file(localized_script, base_duration, srt_path, timed_cues=loc_speech_cues)

                    # Thumbnails
                    thumbs = ThumbnailEngine.generate_3_thumbnail_options(
                        video_path=raw_video_path,
                        job_id=f"{job_id}_{lang}",
                        movie_title=movie_title,
                        lang=lang
                    )

                    # SEO metadata
                    meta_pack = MetadataEngine.generate_viral_metadata(
                        movie_title=movie_title,
                        script_snippet=clean_narr[:400],
                        lang=lang
                    )
                    seo_filename = f"seo_{job_id}_{lang}.txt"
                    seo_file_path = str(OUTPUTS_DIR / seo_filename)
                    try:
                        with open(seo_file_path, "w", encoding="utf-8") as sf:
                            sf.write(f"=== {SUPPORTED_LANGUAGES.get(lang, {}).get('name', lang).upper()} VIRAL SEO PACK ===\n\n")
                            sf.write(f"TITLE:\n{meta_pack.get('title', '')}\n\n")
                            sf.write(f"DESCRIPTION:\n{meta_pack.get('description', '')}\n\n")
                            sf.write(f"TAGS:\n{', '.join(meta_pack.get('tags', []))}\n\n")
                            sf.write(f"HASHTAGS:\n{' '.join(meta_pack.get('hashtags', []))}\n\n")
                            sf.write(f"PINNED COMMENT:\n{meta_pack.get('pinned_comment', '')}\n")
                    except Exception as e:
                        log_event(f"⚠️ [Batch] Failed to write SEO pack file for '{lang}': {e}", "WARNING")

                    results_by_lang[lang] = {
                        "language": lang,
                        "language_name": SUPPORTED_LANGUAGES.get(lang, {}).get("name", lang),
                        "audio_filename": dub_filename,
                        "audio_url": f"/outputs/{dub_filename}",
                        "srt_filename": srt_filename,
                        "srt_url": f"/outputs/{srt_filename}",
                        "video_filename": master_video_filename,
                        "video_url": master_video_url,
                        "duration": round(base_duration, 1),
                        "thumbnails": thumbs,
                        "metadata_pack": meta_pack,
                        "seo_url": f"/outputs/{seo_filename}"
                    }

                    if os.path.exists(speech_path):
                        try: os.remove(speech_path)
                        except Exception: pass

                except Exception as le:
                    print(f"[Multi-Audio Error {lang}] {le}")

        # Mode B: Independent Full Videos per Language
        else:
            for lang in lang_list:
                try:
                    if lang in pre_scripts and pre_scripts[lang] and pre_scripts[lang].strip():
                        localized_script = pre_scripts[lang].strip()
                    else:
                        localized_script = script_text
                        if lang != "en":
                            try:
                                from deep_translator import GoogleTranslator
                                if len(script_text) > 2500:
                                    chunks = [script_text[i:i+2000] for i in range(0, len(script_text), 2000)]
                                    localized_script = " ".join([GoogleTranslator(source="auto", target=lang).translate(c) for c in chunks])
                                else:
                                    localized_script = GoogleTranslator(source="auto", target=lang).translate(script_text)
                            except Exception as te:
                                print(f"[Batch Translator Warning {lang}] {te}")

                    clean_narration, scene_ranges, scene_subs = ScriptEngine.parse_storyboard(localized_script)
                    if not clean_narration:
                        clean_narration = localized_script.strip()

                    chosen_voice = custom_voices.get(lang) or VoiceEngine.get_default_voice_for_lang(lang)
                    speech_path = str(TEMP_DIR / f"{job_id}_{lang}_speech.mp3")
                    rate_val = "+20%" if voice_speed == "ultra_fast" else ("+15%" if voice_speed == "fast" else "+0%")

                    tts_ok = await VoiceEngine.synthesize_speech(clean_narration, chosen_voice, speech_path, rate=rate_val, pitch="-12Hz")
                    if not tts_ok or not os.path.exists(speech_path):
                        continue

                    speech_dur = VideoEngine.get_duration(speech_path)
                    speech_cues = VoiceEngine.get_speech_cues(speech_path)
                    embedding_prov = ScriptEngine.get_configured_embedding_provider()
                    loc_scene_blocks = ScriptEngine.parse_storyboard_blocks(
                        localized_script,
                        dialogue_timeline=dialogue_timeline,
                        embedding_provider=embedding_prov
                    )
                    if loc_scene_blocks:
                        loc_scene_blocks = ScriptEngine.assign_narration_timing(loc_scene_blocks, speech_dur, speech_cues)

                    video_slice_path = str(TEMP_DIR / f"{job_id}_{lang}_slice.mp4")
                    assembled_video = VideoEngine.build_audio_locked_scene_clips(
                        input_video=raw_video_path,
                        scene_blocks=loc_scene_blocks,
                        temp_dir=str(TEMP_DIR),
                        job_id=f"{job_id}_{lang}",
                        output_video=video_slice_path,
                    )
                    if not assembled_video or not os.path.exists(assembled_video):
                        assembled_video = VideoEngine.slice_and_assemble_scenes(
                            input_video=raw_video_path,
                            scene_ranges=scene_ranges,
                            target_duration=speech_dur,
                            output_video=video_slice_path,
                            temp_dir=str(TEMP_DIR),
                            job_id=f"{job_id}_{lang}",
                            scene_blocks=loc_scene_blocks
                        )

                    bgm_track = AudioMixer.get_mood_music_track(mood_theme)
                    if not bgm_track and audio_mode != "sfx_only":
                        procedural_bgm = str(TEMP_DIR / f"{job_id}_{lang}_bgm.mp3")
                        AudioMixer.generate_procedural_synth(procedural_bgm, speech_dur + 3.0, mood=mood_theme)
                        bgm_track = procedural_bgm

                    mixed_audio_path = str(TEMP_DIR / f"{job_id}_{lang}_master.mp3")
                    loc_sfx_cues = ScriptEngine.extract_sfx_cues(localized_script, total_duration=speech_dur)
                    AudioMixer.mix_soundtrack(
                        voice_path=speech_path,
                        bgm_path=bgm_track,
                        output_path=mixed_audio_path,
                        voice_duration=speech_dur,
                        audio_mode=audio_mode,
                        scene_starts=[s for s, _ in scene_ranges],
                        genre=genre,
                        bgm_volume=0.14,
                        explicit_sfx_cues=loc_sfx_cues
                    )
                    final_audio = mixed_audio_path if os.path.exists(mixed_audio_path) else speech_path

                    final_filename = f"explainer_{job_id}_{lang}.mp4"
                    final_video_path = str(OUTPUTS_DIR / final_filename)

                    render_ok = VideoEngine.render_final_explainer(
                        video_source=assembled_video,
                        audio_source=final_audio,
                        output_path=final_video_path,
                        duration=speech_dur,
                        aspect_ratio=aspect_ratio,
                        burn_subtitles=burn_subtitles,
                        scene_subtitles=scene_subs,
                        watermark=watermark or "",
                        part_number=1,
                        lang=lang,
                        timed_cues=speech_cues
                    )

                    if render_ok and os.path.exists(final_video_path):
                        thumbs = ThumbnailEngine.generate_3_thumbnail_options(
                            video_path=raw_video_path,
                            job_id=f"{job_id}_{lang}",
                            movie_title=movie_title,
                            lang=lang
                        )
                        meta_pack = MetadataEngine.generate_viral_metadata(
                            movie_title=movie_title,
                            script_snippet=clean_narration[:400],
                            lang=lang
                        )

                        seo_filename = f"seo_{job_id}_{lang}.txt"
                        seo_file_path = str(OUTPUTS_DIR / seo_filename)
                        try:
                            with open(seo_file_path, "w", encoding="utf-8") as sf:
                                sf.write(f"=== {SUPPORTED_LANGUAGES.get(lang, {}).get('name', lang).upper()} VIRAL SEO PACK ===\n\n")
                                sf.write(f"TITLE:\n{meta_pack.get('title', '')}\n\n")
                                sf.write(f"DESCRIPTION:\n{meta_pack.get('description', '')}\n\n")
                                sf.write(f"TAGS:\n{', '.join(meta_pack.get('tags', []))}\n\n")
                                sf.write(f"HASHTAGS:\n{' '.join(meta_pack.get('hashtags', []))}\n\n")
                                sf.write(f"PINNED COMMENT:\n{meta_pack.get('pinned_comment', '')}\n")
                        except Exception as se:
                            print(f"[SEO save warning] {se}")

                        results_by_lang[lang] = {
                            "language": lang,
                            "language_name": SUPPORTED_LANGUAGES.get(lang, {}).get("name", lang),
                            "video_filename": final_filename,
                            "video_url": f"/outputs/{final_filename}",
                            "duration": round(speech_dur, 1),
                            "thumbnails": thumbs,
                            "metadata_pack": meta_pack,
                            "seo_url": f"/outputs/{seo_filename}"
                        }

                    for tp in [speech_path, video_slice_path, mixed_audio_path]:
                        if tp and os.path.exists(tp):
                            try: os.remove(tp)
                            except Exception: pass

                except Exception as e:
                    print(f"[Batch Multiplier Error {lang}] {e}")

        if len(results_by_lang) == 0:
            raise HTTPException(status_code=500, detail="Batch rendering failed for all selected languages.")

        return {
            "success": True,
            "job_id": job_id,
            "export_mode": export_mode,
            "master_video_filename": master_video_filename,
            "master_video_url": master_video_url,
            "languages_count": len(results_by_lang),
            "results": results_by_lang,
            "zip_url": f"/api/v1/explainer/download-bundle-zip?job_id={job_id}"
        }
    finally:
        # Guaranteed cleanup of raw ingested video
        if os.path.exists(raw_video_path):
            try: os.remove(raw_video_path)
            except Exception: pass
        # Catch-all: batch leftovers ({job_id}_{lang}_* etc.)
        cleanup_job_temp_files(job_id)


@router.get("/download-bundle-zip")
async def download_bundle_zip_endpoint(job_id: str):
    """
    Creates and streams a YouTube Studio-Ready structured master .zip archive:
    ├── 00_MASTER_VIDEO/
    ├── 01_YOUTUBE_AUDIO_TRACKS/
    ├── 02_SUBTITLES_SRT/
    ├── 03_THUMBNAILS/
    └── 04_SEO_METADATA/
    """
    clean_job_id = job_id.strip()
    if not re.match(r"^[a-zA-Z0-9_-]{4,32}$", clean_job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format.")

    zip_filename = f"AutoExplainer_Bundle_{clean_job_id}.zip"
    zip_path = (OUTPUTS_DIR / zip_filename).resolve()

    # Traversal security check
    if not str(zip_path).startswith(str(OUTPUTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Illegal output path.")

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        added_files = 0

        # 1. MP4 Master & Localized Videos
        if os.path.exists(OUTPUTS_DIR):
            for f in os.listdir(OUTPUTS_DIR):
                if clean_job_id in f and f.endswith(".mp4"):
                    full_p = OUTPUTS_DIR / f
                    if "MASTER" in f:
                        zf.write(str(full_p), arcname=f"00_MASTER_VIDEO/{f}")
                    else:
                        parts = f.replace(".mp4", "").split("_")
                        lang_code = parts[-1] if len(parts) >= 3 else "general"
                        lang_name = SUPPORTED_LANGUAGES.get(lang_code, {}).get("name", lang_code)
                        zf.write(str(full_p), arcname=f"00_MASTER_VIDEO/{lang_code.upper()}_{lang_name}/{f}")
                    added_files += 1

        # 2. YouTube Audio Tracks (.mp3)
        if os.path.exists(OUTPUTS_DIR):
            for f in os.listdir(OUTPUTS_DIR):
                if clean_job_id in f and f.endswith(".mp3"):
                    full_p = OUTPUTS_DIR / f
                    parts = f.replace(".mp3", "").split("_")
                    lang_code = parts[-1] if len(parts) >= 3 else "general"
                    lang_name = SUPPORTED_LANGUAGES.get(lang_code, {}).get("name", lang_code)
                    zf.write(str(full_p), arcname=f"01_YOUTUBE_AUDIO_TRACKS/Audio_Track_{lang_code.upper()}_{lang_name}.mp3")
                    added_files += 1

        # 3. Subtitles (.srt)
        if os.path.exists(OUTPUTS_DIR):
            for f in os.listdir(OUTPUTS_DIR):
                if clean_job_id in f and f.endswith(".srt"):
                    full_p = OUTPUTS_DIR / f
                    parts = f.replace(".srt", "").split("_")
                    lang_code = parts[-1] if len(parts) >= 3 else "general"
                    zf.write(str(full_p), arcname=f"02_SUBTITLES_SRT/Subtitles_{lang_code.upper()}.srt")
                    added_files += 1

        # 4. Thumbnails (skip _base.jpg)
        if os.path.exists(THUMBNAILS_DIR):
            for f in os.listdir(THUMBNAILS_DIR):
                if clean_job_id in f and f.endswith(".jpg") and not f.endswith("_base.jpg"):
                    full_p = THUMBNAILS_DIR / f
                    parts = f.replace(".jpg", "").split("_")
                    lang_code = parts[2] if len(parts) >= 4 and parts[2] in SUPPORTED_LANGUAGES else "general"
                    zf.write(str(full_p), arcname=f"03_THUMBNAILS/{lang_code.upper()}/{f}")
                    added_files += 1

        # 5. SEO Metadata Packs (.txt)
        if os.path.exists(OUTPUTS_DIR):
            for f in os.listdir(OUTPUTS_DIR):
                if clean_job_id in f and f.endswith(".txt"):
                    full_p = OUTPUTS_DIR / f
                    parts = f.replace(".txt", "").split("_")
                    lang_code = parts[-1] if len(parts) >= 3 else "general"
                    lang_name = SUPPORTED_LANGUAGES.get(lang_code, {}).get("name", lang_code)
                    zf.write(str(full_p), arcname=f"04_SEO_METADATA/YouTube_SEO_{lang_code.upper()}_{lang_name}.txt")
                    added_files += 1

    if added_files == 0:
        if os.path.exists(str(zip_path)):
            try: os.remove(str(zip_path))
            except Exception: pass
        raise HTTPException(status_code=404, detail=f"No rendered files found for job ID {clean_job_id}")

    return FileResponse(
        path=str(zip_path),
        filename=zip_filename,
        media_type="application/zip"
    )


@router.post("/auto-detect-context")
async def auto_detect_context_endpoint(
    transcript_text: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    title_hint: Optional[str] = Form(None)
):
    """
    Agent 1 Detective: Instant context extraction from transcript or URL.
    Returns auto-detected title, genre, persona, mood, and initial story beats.
    """
    from app.services.agent_swarm import AgentSwarmEngine
    raw_text = (transcript_text or "").strip()
    hint = (title_hint or "").strip()

    if not raw_text and url:
        try:
            temp_id = str(uuid.uuid4())[:8]
            info = VideoEngine.extract_youtube_info(url, str(TEMP_DIR), temp_id)
            hint = hint or info.get("title", "")
            raw_text = info.get("subtitles_text", "")
        except Exception as e:
            log_event(f"⚠️ [Autopilot] YouTube info/hint extraction failed, continuing without it: {e}", "WARNING")

    context = AgentSwarmEngine.detective_agent(raw_text, hint)
    return {
        "success": True,
        "title": context.get("title", hint or "Movie Recap"),
        "genre": context.get("genre", "movie_recap"),
        "persona": context.get("persona", "hollywood_trailer"),
        "mood": context.get("mood", "suspense"),
        "story_beats": context.get("story_beats", [])
    }


@router.post("/run-autopilot")
async def run_autopilot_endpoint(
    url: Optional[str] = Form(None),
    transcript_text: Optional[str] = Form(None),
    target_lang: str = Form("ur"),
    narrator_voice: str = Form("ur-PK-AsadNeural"),
    speech_velocity: str = Form("fast"),
    duration_mins: int = Form(3),
    resolution: str = Form("720p"),
    aspect_ratio: str = Form("vertical"),
    burn_subtitles: bool = Form(True),
    watermark: Optional[str] = Form(""),
    audio_mode: str = Form("hybrid"),
    notes: Optional[str] = Form(""),
    local_file: Optional[UploadFile] = File(None)
):
    """
    1-Click Master Autopilot Pipeline:
    Executes the 5-Agent Swarm (Detective, Screenwriter, Hook Critic, Art Director, SEO Agent),
    slices video via yt-dlp section downloads, synthesizes voiceover, mixes SFX/music,
    burns dynamic subtitles, and generates 3 viral climax thumbnails and SEO metadata.
    """
    from app.services.agent_swarm import AgentSwarmEngine
    from app.services.subtitle_engine import SubtitleEngine

    raw_transcript = (transcript_text or "").strip()
    clean_url = (url or "").strip()
    if not raw_transcript and not clean_url and not local_file:
        raise HTTPException(status_code=400, detail="Please provide a YouTube URL, transcript text, or upload a local video file.")

    job_id = str(uuid.uuid4())[:8]
    log_event(f"🚀 [Autopilot] Launching 5-Agent Swarm for job '{job_id}'...", "INFO")

    speech_path = None
    mixed_audio_path = None
    video_slice_path = None
    raw_video_path = None

    try:
        # Step 0: Extract timestamped subtitles from YouTube if transcript wasn't manually provided
        if not raw_transcript and clean_url:
            try:
                log_event("🔍 [Autopilot] Extracting timestamped subtitles and story timeline from YouTube...", "INFO")
                info = await asyncio.to_thread(VideoEngine.extract_youtube_info, clean_url, str(TEMP_DIR), job_id)
                if info and info.get("subtitles_text"):
                    raw_transcript = info.get("subtitles_text")
                    if not notes and info.get("title"):
                        notes = info.get("title")
                    log_event(f"✅ [Autopilot] Loaded {len(raw_transcript.split())} words of timestamped source transcript", "SUCCESS")
            except Exception as e:
                log_event(f"⚠️ [Autopilot] YouTube subtitle extraction notice: {e}", "WARNING")

        # Step 1: Execute Parallel AI Agent Swarm with transcript anchoring
        log_event("🤖 [Autopilot] Agent Swarm running: Detective + Screenwriter + Art Director + SEO...", "INFO")
        swarm = await AgentSwarmEngine.run_parallel_swarm(
            transcript_text=raw_transcript,
            video_title_hint=notes or "",
            target_lang=target_lang,
            duration_minutes=duration_mins,
            speech_velocity=speech_velocity,
            narrator_voice=narrator_voice,
            notes=notes or ""
        )

        context = swarm.get("context", {})
        final_script = swarm.get("script", "")
        seo_pack = swarm.get("seo_pack", {})
        art_strat = swarm.get("thumbnail_strategy", {})
        hook_critique = swarm.get("hook_score", {})
        movie_title = context.get("title", "Movie Recap")
        genre = context.get("genre", "movie_recap")
        mood = context.get("mood", "suspense")

        # Step 2: Parse script for scene timestamps and clean narration (Dialogue-Anchored)
        dialogue_timeline = []
        transcript_source = "none"
        raw_transcript = (transcript_text or "").strip()
        if raw_transcript:
            parsed_trans = VideoEngine.parse_raw_transcript_text(raw_transcript)
            dialogue_timeline = parsed_trans.get("dialogue_timeline", [])
            transcript_source = "user_transcript"
        elif url and VideoEngine.is_valid_youtube_url(url):
            try:
                info = VideoEngine.extract_youtube_info(url, str(TEMP_DIR), job_id)
                subs_raw = info.get("subtitles_text", "")
                if subs_raw:
                    parsed_trans = VideoEngine.parse_raw_transcript_text(subs_raw)
                    dialogue_timeline = parsed_trans.get("dialogue_timeline", [])
                    transcript_source = "existing_subtitles"
            except Exception as e:
                log_event(f"⚠️ [Autopilot] Subtitle/dialogue extraction failed for job {job_id}, continuing without it: {e}", "WARNING")

        # Phase 6A: Ingest local video early for autopilot if ASR is needed
        if local_file and not dialogue_timeline:
            safe_name = os.path.basename(local_file.filename or "upload.mp4")
            raw_video_path = str(TEMP_DIR / f"autopilot_local_{job_id}_{safe_name}")
            save_upload_with_limit(local_file, raw_video_path, MAX_VIDEO_BYTES)
            from app.services.asr_engine import ASREngine
            try:
                asr_cues, asr_subs, asr_src = await asyncio.to_thread(
                    ASREngine.transcribe_media_to_dialogue,
                    media_path=raw_video_path,
                    temp_dir=str(TEMP_DIR),
                    job_id=job_id
                )
                if asr_cues:
                    dialogue_timeline = asr_cues
                    transcript_source = asr_src
                    log_event(f"⚡ [Autopilot] ASR extracted {len(dialogue_timeline)} dialogue cues (transcript_source=asr)", "SUCCESS")
            except Exception as e:
                log_event(f"⚠️ [Autopilot] ASR invocation failed: {e}", "WARNING")

        clean_narration, scene_ranges, scene_subs = ScriptEngine.parse_storyboard(final_script)
        embedding_prov = ScriptEngine.get_configured_embedding_provider()
        scene_blocks = ScriptEngine.parse_storyboard_blocks(
            final_script,
            dialogue_timeline=dialogue_timeline,
            embedding_provider=embedding_prov,
            transcript_source=transcript_source
        )
        if scene_blocks:
            scene_ranges = [(b.movie_start, b.movie_end) for b in scene_blocks]
        if not clean_narration:
            clean_narration = f"Here is the story recap of {movie_title}."

        # Step 3: Synthesize Voiceover
        log_event(f"🎙️ [Autopilot] Synthesizing voiceover with voice '{narrator_voice}'...", "INFO")
        speech_path = str(TEMP_DIR / f"{job_id}_speech.mp3")
        rate_val = "+18%" if speech_velocity == "ultra_fast" else ("+15%" if speech_velocity == "fast" else "+0%")
        pitch_val = "-12Hz"
        await VoiceEngine.synthesize_speech(
            text=clean_narration,
            voice=narrator_voice,
            output_path=speech_path,
            rate=rate_val,
            pitch=pitch_val
        )
        speech_dur = VoiceEngine.get_audio_duration(speech_path)
        if speech_dur <= 0.5:
            speech_dur = duration_mins * 60.0

        # Exact Narration-to-Scene Time-Lock using authoritative Edge-TTS sentence boundary cues
        speech_cues = VoiceEngine.get_speech_cues(speech_path)
        if scene_blocks:
            scene_blocks = ScriptEngine.assign_narration_timing(scene_blocks, speech_dur, speech_cues)
            log_event(f"🔒 [Autopilot] Locked exact narration timing across {len(scene_blocks)} scene blocks (Zero Drift)", "INFO")

        # Step 4: Ingest Video Source with Bulletproof Footage Integrity
        if local_file:
            if not raw_video_path or not os.path.exists(raw_video_path):
                safe_name = os.path.basename(local_file.filename or "upload.mp4")
                raw_video_path = str(TEMP_DIR / f"autopilot_local_{job_id}_{safe_name}")
                save_upload_with_limit(local_file, raw_video_path, MAX_VIDEO_BYTES)
        elif clean_url:
            log_event("🌐 [Autopilot] Ensuring footage integrity from YouTube...", "INFO")
            raw_video_path = await asyncio.to_thread(
                VideoEngine.ensure_footage_integrity,
                url=clean_url,
                job_id=job_id,
                speech_dur=speech_dur,
                temp_dir=str(TEMP_DIR),
                resolution=resolution,
                scene_ranges=scene_ranges
            )
        else:
            raise HTTPException(status_code=400, detail="Failed to retrieve or download source video.")

        raw_dur = VideoEngine.get_duration(raw_video_path) if (raw_video_path and os.path.exists(raw_video_path)) else 0.0

        # Step 5: Video Slicing & Assembly — Audio-Locked (deterministic narration-to-visual sync)
        video_slice_path = str(TEMP_DIR / f"{job_id}_sliced.mp4")
        log_event(f"🎬 [Autopilot] Building {len(scene_blocks)} audio-locked scene clips (narration-to-visual deterministic sync)...", "INFO")
        assembled_video = await asyncio.to_thread(
            VideoEngine.build_audio_locked_scene_clips,
            input_video=raw_video_path,
            scene_blocks=scene_blocks,
            temp_dir=str(TEMP_DIR),
            job_id=job_id,
            output_video=video_slice_path,
        )
        if not assembled_video or not os.path.exists(assembled_video):
            expected_cuts = max(8, int(round(speech_dur / 3.8)))
            log_event(f"⚠️ [Autopilot] Audio-locked sync fallback: slicing ~{expected_cuts} narrative cuts...", "WARNING")
            assembled_video = await asyncio.to_thread(
                VideoEngine.slice_and_assemble_scenes,
                input_video=raw_video_path,
                scene_ranges=scene_ranges,
                target_duration=speech_dur,
                output_video=video_slice_path,
                temp_dir=str(TEMP_DIR),
                job_id=job_id,
                scene_blocks=scene_blocks
            )

        # Step 6: Sound Design (BGM + Dynamic SFX)
        log_event("🔊 [Autopilot] Audio Mixer integrating dynamic SFX hits & ducked music...", "INFO")
        bgm_track = AudioMixer.get_mood_music_track(mood)
        mixed_audio_path = str(TEMP_DIR / f"{job_id}_master_audio.mp3")
        ai_sfx_cues = ScriptEngine.extract_sfx_cues(final_script, total_duration=speech_dur)

        await asyncio.to_thread(
            AudioMixer.mix_soundtrack,
            voice_path=speech_path,
            bgm_path=bgm_track,
            output_path=mixed_audio_path,
            voice_duration=speech_dur,
            audio_mode=audio_mode,
            scene_starts=[s for s, _ in scene_ranges],
            genre=genre,
            bgm_volume=0.14,
            explicit_sfx_cues=ai_sfx_cues
        )
        final_audio = mixed_audio_path if os.path.exists(mixed_audio_path) else speech_path

        # Step 7: Render Final Video with synchronized subtitles
        log_event("🎬 [Autopilot] Rendering final explainer video with anti-copyright armor...", "INFO")
        final_filename = f"explainer_{job_id}_{target_lang}.mp4"
        final_output_path = str(OUTPUTS_DIR / final_filename)
        speech_cues = VoiceEngine.get_speech_cues(speech_path)
        render_ok = await asyncio.to_thread(
            VideoEngine.render_final_explainer,
            video_source=assembled_video,
            audio_source=final_audio,
            output_path=final_output_path,
            duration=speech_dur,
            aspect_ratio=aspect_ratio,
            burn_subtitles=burn_subtitles,
            scene_subtitles=scene_subs,
            watermark=watermark or "",
            part_number=1,
            lang=target_lang,
            timed_cues=speech_cues
        )
        if not render_ok or not os.path.exists(final_output_path):
            raise HTTPException(status_code=500, detail="Video rendering assembly failed.")

        # Step 7: Generate 3 Viral Climax Thumbnails (AI Cinema Poster + Movie Climax + Split Screen)
        log_event("🖼️ [Autopilot] Generating 3 A/B test climax thumbnails...", "INFO")
        climax_ts = art_strat.get("climax_timestamp", 150.0)
        hook_opts = art_strat.get("hook_options", None)
        try:
            ai_image_path = None
            try:
                from app.services.nine_router_client import (
                    is_ninerouter_available,
                    craft_cinematic_thumbnail_prompt,
                    generate_ai_image_with_9router
                )
                if await asyncio.to_thread(is_ninerouter_available, 3.0):
                    prompt = craft_cinematic_thumbnail_prompt(
                        title=movie_title,
                        plot_summary=clean_narration[:400],
                        genre=genre
                    )
                    log_event("🎨 [Autopilot] Generating 9Router photorealistic cinema poster thumbnail...", "INFO")
                    ai_image_path = await asyncio.to_thread(
                        generate_ai_image_with_9router,
                        prompt=prompt,
                        size="1280x720",
                        output_dir=str(THUMBNAILS_DIR)
                    )
                    if ai_image_path and os.path.exists(ai_image_path):
                        log_event("✨ [Autopilot] 9Router AI Photorealistic Cinema Poster generated!", "SUCCESS")
            except Exception as e:
                print(f"[Autopilot 9Router AI Thumbnail Notice] {e}")

            thumbnails = await asyncio.to_thread(
                ThumbnailEngine.generate_3_thumbnail_options,
                video_path=assembled_video,
                job_id=job_id,
                movie_title=movie_title,
                lang=target_lang,
                custom_hooks=hook_opts,
                target_timestamps=[float(climax_ts)] if climax_ts else None,
                plot_summary=clean_narration[:400],
                ai_image_path=ai_image_path,
                youtube_url=url
            )
        except Exception as e:
            log_event(f"⚠️ [Autopilot] Thumbnail generation notice: {e}", "WARNING")
            thumbnails = []

        log_event(f"🎉 [Autopilot] Complete Explainer Ready: '{final_filename}'!", "SUCCESS")

        return {
            "success": True,
            "job_id": job_id,
            "video_filename": final_filename,
            "video_url": f"/outputs/{final_filename}",
            "duration": round(speech_dur, 1),
            "script": final_script,
            "hook_score": hook_critique,
            "context": context,
            "seo_pack": seo_pack,
            "thumbnails": thumbnails,
            "narrator_voice": narrator_voice,
            "speech_velocity": speech_velocity
        }
    except HTTPException:
        raise
    except Exception as exc:
        log_event(f"❌ [Autopilot Error] {exc}", "ERROR")
        return JSONResponse(status_code=500, content={"success": False, "detail": str(exc)})
    finally:
        for p in [speech_path, video_slice_path, mixed_audio_path]:
            if p and os.path.exists(p):
                try: os.remove(p)
                except Exception: pass
        # Catch-all: autopilot_local_* and other job leftovers
        cleanup_job_temp_files(job_id)


