import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.core import config

logger = logging.getLogger("youtube_engine")

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# In-memory status for background upload tasks
upload_tasks: Dict[str, Dict[str, Any]] = {}

def get_client_credentials() -> Dict[str, str]:
    """Retrieve saved Google OAuth client credentials."""
    if not config.YOUTUBE_CREDS_FILE.exists():
        return {}
    try:
        with open(config.YOUTUBE_CREDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading {config.YOUTUBE_CREDS_FILE}: {e}")
        return {}

def save_client_credentials(client_id: str, client_secret: str, project_id: str = "") -> None:
    """Save Google OAuth client credentials."""
    data = {
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
        "project_id": project_id.strip(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    config.YOUTUBE_CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.YOUTUBE_CREDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_channel_profiles() -> List[Dict[str, Any]]:
    """Retrieve all saved channel profiles."""
    if not config.YOUTUBE_CHANNELS_FILE.exists():
        return []
    try:
        with open(config.YOUTUBE_CHANNELS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading {config.YOUTUBE_CHANNELS_FILE}: {e}")
        return []

def save_channel_profile(channel_data: Dict[str, Any]) -> None:
    """Save or update a channel profile in youtube_channels.json."""
    channels = get_channel_profiles()
    channel_id = channel_data.get("channel_id")
    if not channel_id:
        raise ValueError("channel_id is required")

    updated = False
    for i, ch in enumerate(channels):
        if ch.get("channel_id") == channel_id:
            channels[i] = {**ch, **channel_data}
            updated = True
            break
    if not updated:
        channels.append(channel_data)

    config.YOUTUBE_CHANNELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.YOUTUBE_CHANNELS_FILE, "w", encoding="utf-8") as f:
        json.dump(channels, f, indent=2)

def delete_channel_profile(channel_id: str) -> bool:
    """Remove a channel profile by channel_id."""
    channels = get_channel_profiles()
    initial_len = len(channels)
    channels = [ch for ch in channels if ch.get("channel_id") != channel_id]
    if len(channels) == initial_len:
        return False
    config.YOUTUBE_CHANNELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.YOUTUBE_CHANNELS_FILE, "w", encoding="utf-8") as f:
        json.dump(channels, f, indent=2)
    return True

def format_publish_at_iso(datetime_input: str, tz_offset_hours: float = 0.0) -> str:
    """
    Parses a local datetime string (or ISO format) and returns an ISO 8601 UTC string (ending with 'Z').
    Validates that the scheduled time is strictly in the future.
    """
    clean_str = datetime_input.strip()
    dt = None
    
    # Check if string ends with 'Z'
    if clean_str.endswith("Z"):
        clean_str_no_z = clean_str[:-1]
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
            try:
                dt_naive = datetime.strptime(clean_str_no_z, fmt)
                dt = dt_naive.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
    elif "+" in clean_str or "-" in clean_str[10:]:
        # Has timezone offset in string
        try:
            dt = datetime.fromisoformat(clean_str)
            dt = dt.astimezone(timezone.utc)
        except Exception:
            pass

    if dt is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
            try:
                dt_naive = datetime.strptime(clean_str, fmt)
                offset = timedelta(hours=tz_offset_hours)
                tz = timezone(offset)
                dt = dt_naive.replace(tzinfo=tz).astimezone(timezone.utc)
                break
            except ValueError:
                continue

    if dt is None:
        raise ValueError(f"Invalid datetime format: '{datetime_input}'. Use 'YYYY-MM-DD HH:MM:SS' or ISO format.")

    now_utc = datetime.now(timezone.utc)
    if dt <= now_utc:
        raise ValueError(f"Scheduled publishAt datetime ({dt.isoformat()}) must be in the future (Current UTC: {now_utc.isoformat()}).")

    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def build_video_insert_body(
    title: str,
    description: str,
    tags: List[str],
    category_id: str = "1",
    publish_at_iso: Optional[str] = None,
    made_for_kids: bool = False
) -> Dict[str, Any]:
    """Constructs YouTube Data API v3 video insert payload."""
    status: Dict[str, Any] = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": made_for_kids
    }
    if publish_at_iso:
        status["publishAt"] = publish_at_iso

    return {
        "snippet": {
            "title": title[:100],  # YouTube title limit
            "description": description[:5000],  # YouTube description limit
            "tags": tags[:500],
            "categoryId": category_id
        },
        "status": status
    }

def get_authorization_url(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: str = "http://localhost:8000/api/v1/youtube/oauth-callback",
    state: Optional[str] = None,
) -> str:
    """Generate Google OAuth 2.0 authorization URL."""
    from google_auth_oauthlib.flow import Flow
    
    creds = get_client_credentials()
    c_id = client_id or creds.get("client_id")
    c_secret = client_secret or creds.get("client_secret")
    
    if not c_id or not c_secret:
        raise ValueError("Google Client ID and Client Secret must be configured first.")

    client_config = {
        "web": {
            "client_id": c_id,
            "client_secret": c_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri]
        }
    }
    flow = Flow.from_client_config(client_config, scopes=YOUTUBE_SCOPES)
    flow.redirect_uri = redirect_uri
    
    auth_kwargs = dict(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    if state:
        auth_kwargs["state"] = state
    auth_url, _ = flow.authorization_url(**auth_kwargs)
    return auth_url

def exchange_code_for_tokens(
    code: str,
    redirect_uri: str = "http://localhost:8000/api/v1/youtube/oauth-callback"
) -> Dict[str, Any]:
    """Exchange authorization code for refresh tokens and save channel profile."""
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build

    creds_conf = get_client_credentials()
    c_id = creds_conf.get("client_id")
    c_secret = creds_conf.get("client_secret")
    if not c_id or not c_secret:
        raise ValueError("Google Client Credentials missing.")

    client_config = {
        "web": {
            "client_id": c_id,
            "client_secret": c_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri]
        }
    }
    flow = Flow.from_client_config(client_config, scopes=YOUTUBE_SCOPES)
    flow.redirect_uri = redirect_uri
    flow.fetch_token(code=code)
    credentials = flow.credentials

    # Build service to query channel details
    youtube = build("youtube", "v3", credentials=credentials)
    resp = youtube.channels().list(mine=True, part="snippet,contentDetails,statistics").execute()
    items = resp.get("items", [])
    if not items:
        raise ValueError("No YouTube channel found associated with this Google account.")

    item = items[0]
    channel_id = item.get("id")
    snippet = item.get("snippet", {})
    thumbnails = snippet.get("thumbnails", {})
    avatar = thumbnails.get("default", {}).get("url") or thumbnails.get("medium", {}).get("url", "")
    
    channel_data = {
        "channel_id": channel_id,
        "title": snippet.get("title", "Untitled Channel"),
        "custom_url": snippet.get("customUrl", ""),
        "thumbnail_url": avatar,
        "language": snippet.get("defaultLanguage", "ur"),
        "refresh_token": credentials.refresh_token,
        "connected_at": datetime.now(timezone.utc).isoformat()
    }
    save_channel_profile(channel_data)
    return channel_data

def get_authenticated_service(channel_id: str):
    """Build and return an authorized googleapiclient YouTube service."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    channels = get_channel_profiles()
    channel = next((c for c in channels if c.get("channel_id") == channel_id), None)
    if not channel:
        raise ValueError(f"Channel with ID {channel_id} not found.")

    refresh_token = channel.get("refresh_token")
    if not refresh_token:
        raise ValueError(f"No refresh_token found for channel {channel_id}.")

    creds_conf = get_client_credentials()
    c_id = creds_conf.get("client_id")
    c_secret = creds_conf.get("client_secret")

    credentials = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=c_id,
        client_secret=c_secret,
        scopes=YOUTUBE_SCOPES
    )
    return build("youtube", "v3", credentials=credentials)

def _background_upload_worker(
    task_id: str,
    channel_id: str,
    video_path: str,
    title: str,
    description: str,
    tags: List[str],
    publish_at_iso: str,
    thumbnail_path: Optional[str] = None,
    srt_path: Optional[str] = None,
    language: str = "en"
):
    """Worker function executed in background thread."""
    from googleapiclient.http import MediaFileUpload

    try:
        upload_tasks[task_id]["status"] = "connecting"
        upload_tasks[task_id]["message"] = "Authenticating with YouTube API..."

        youtube = get_authenticated_service(channel_id)
        
        insert_body = build_video_insert_body(
            title=title,
            description=description,
            tags=tags,
            publish_at_iso=publish_at_iso
        )

        upload_tasks[task_id]["status"] = "uploading"
        upload_tasks[task_id]["message"] = "Uploading video in 5MB resumable chunks..."

        media = MediaFileUpload(
            video_path,
            chunksize=5 * 1024 * 1024,
            resumable=True,
            mimetype="video/mp4"
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=insert_body,
            media_body=media
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                upload_tasks[task_id]["progress"] = pct
                upload_tasks[task_id]["message"] = f"Uploading video: {pct}%"

        video_id = response.get("id")
        upload_tasks[task_id]["video_id"] = video_id
        upload_tasks[task_id]["video_url"] = f"https://youtu.be/{video_id}"

        # Custom Thumbnail
        if thumbnail_path and os.path.exists(thumbnail_path):
            try:
                upload_tasks[task_id]["message"] = "Attaching high-CTR thumbnail..."
                thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=thumb_media
                ).execute()
            except Exception as e:
                logger.warning(f"Thumbnail upload failed: {e}")

        # Subtitles (SRT)
        if srt_path and os.path.exists(srt_path):
            try:
                upload_tasks[task_id]["message"] = "Attaching timed subtitles (.srt)..."
                caption_media = MediaFileUpload(srt_path, mimetype="application/x-subrip")
                youtube.captions().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "videoId": video_id,
                            "language": language,
                            "name": f"AutoExplainer Captions ({language})",
                            "isDraft": False
                        }
                    },
                    media_body=caption_media
                ).execute()
            except Exception as e:
                logger.warning(f"Captions upload failed: {e}")

        upload_tasks[task_id]["status"] = "completed"
        upload_tasks[task_id]["progress"] = 100
        upload_tasks[task_id]["message"] = f"Video successfully scheduled! Public on: {publish_at_iso}"
    except Exception as e:
        logger.error(f"Upload task {task_id} failed: {e}", exc_info=True)
        upload_tasks[task_id]["status"] = "failed"
        upload_tasks[task_id]["error"] = str(e)
        upload_tasks[task_id]["message"] = f"Upload failed: {e}"

def start_video_schedule_task(
    channel_id: str,
    video_path: str,
    title: str,
    description: str,
    tags: List[str],
    publish_at_iso: str,
    thumbnail_path: Optional[str] = None,
    srt_path: Optional[str] = None,
    language: str = "en"
) -> str:
    """Start background video upload & schedule task."""
    task_id = str(uuid.uuid4())
    upload_tasks[task_id] = {
        "task_id": task_id,
        "channel_id": channel_id,
        "status": "queued",
        "progress": 0,
        "message": "Upload queued in background worker...",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "video_id": None,
        "video_url": None,
        "error": None
    }

    thread = threading.Thread(
        target=_background_upload_worker,
        args=(
            task_id,
            channel_id,
            video_path,
            title,
            description,
            tags,
            publish_at_iso,
            thumbnail_path,
            srt_path,
            language
        ),
        daemon=True
    )
    thread.start()
    return task_id
