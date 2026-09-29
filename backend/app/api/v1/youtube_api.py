import os
import html
import logging
import secrets
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.core.config import STORAGE_DIR, OUTPUTS_DIR
from app.services.youtube_engine import (
    get_client_credentials,
    save_client_credentials,
    get_channel_profiles,
    save_channel_profile,
    delete_channel_profile,
    format_publish_at_iso,
    get_authorization_url,
    exchange_code_for_tokens,
    start_video_schedule_task,
    upload_tasks
)

logger = logging.getLogger("youtube_api")
router = APIRouter(prefix="/youtube", tags=["youtube"])

class ClientSetupRequest(BaseModel):
    client_id: str = Field(..., min_length=5, description="Google OAuth Client ID")
    client_secret: str = Field(..., min_length=5, description="Google OAuth Client Secret")
    project_id: Optional[str] = Field(default="", description="Google Cloud Project ID")

class ScheduleVideoRequest(BaseModel):
    channel_id: str = Field(..., description="Target YouTube Channel ID")
    video_path: str = Field(..., description="Path to MP4 video file")
    title: str = Field(..., max_length=100, description="Video Title")
    description: str = Field(..., max_length=5000, description="Video Description")
    tags: List[str] = Field(default_factory=list, description="YouTube Tags")
    publish_at: str = Field(..., description="Scheduled Datetime (ISO or YYYY-MM-DD HH:MM:SS)")
    tz_offset_hours: float = Field(default=0.0, description="Timezone offset hours from UTC")
    thumbnail_path: Optional[str] = Field(default=None, description="Path to custom thumbnail")
    srt_path: Optional[str] = Field(default=None, description="Path to timed SRT subtitles")
    language: str = Field(default="en", description="Target video language")

def _sanitize_channel(ch: Dict[str, Any]) -> Dict[str, Any]:
    """Strip secret tokens before returning to client."""
    sanitized = dict(ch)
    sanitized.pop("refresh_token", None)
    sanitized["has_token"] = bool(ch.get("refresh_token"))
    return sanitized


# ---------------------------------------------------------------------------
# OAuth CSRF protection: one-time `state` tokens bound to each authorization
# request. The callback rejects any redirect whose state is missing, unknown,
# expired, or already used.
# ---------------------------------------------------------------------------
_OAUTH_STATE_TTL_SEC = 600  # 10 minutes
_oauth_states: Dict[str, float] = {}


def _issue_oauth_state() -> str:
    now = time.time()
    # Prune expired entries opportunistically
    for token, issued in list(_oauth_states.items()):
        if now - issued > _OAUTH_STATE_TTL_SEC:
            _oauth_states.pop(token, None)
    token = secrets.token_urlsafe(32)
    _oauth_states[token] = now
    return token


def _consume_oauth_state(state: Optional[str]) -> bool:
    if not state:
        return False
    issued = _oauth_states.pop(state, None)
    if issued is None:
        return False
    return (time.time() - issued) <= _OAUTH_STATE_TTL_SEC

@router.get("/status")
def get_youtube_status():
    """Check configuration status and connected channels."""
    creds = get_client_credentials()
    channels = get_channel_profiles()
    is_configured = bool(creds.get("client_id") and creds.get("client_secret"))
    
    return {
        "configured": is_configured,
        "client_id": creds.get("client_id", "")[:12] + "..." if creds.get("client_id") else "",
        "channels_count": len(channels),
        "channels": [_sanitize_channel(c) for c in channels]
    }

@router.post("/setup-client")
def setup_client_credentials(req: ClientSetupRequest):
    """Save Google OAuth Client ID & Secret."""
    try:
        save_client_credentials(
            client_id=req.client_id,
            client_secret=req.client_secret,
            project_id=req.project_id or ""
        )
        return {
            "status": "success",
            "message": "Google Client credentials saved successfully."
        }
    except Exception as e:
        logger.error(f"Failed to save credentials: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save credentials: {str(e)}")

@router.get("/connect-url")
def get_connect_url(request: Request, redirect_uri: Optional[str] = None):
    """Generate the Google OAuth consent URL."""
    creds = get_client_credentials()
    if not creds.get("client_id") or not creds.get("client_secret"):
        raise HTTPException(
            status_code=400,
            detail="Google Client ID and Secret are not configured yet. Please configure them in setup-client."
        )

    if not redirect_uri:
        # Determine redirect URI dynamically from request base
        base_url = str(request.base_url).rstrip("/")
        redirect_uri = f"{base_url}/api/v1/youtube/oauth-callback"

    try:
        state = _issue_oauth_state()
        url = get_authorization_url(redirect_uri=redirect_uri, state=state)
        return {"auth_url": url, "redirect_uri": redirect_uri, "state": state}
    except Exception as e:
        logger.error(f"Failed to create auth url: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/oauth-callback", response_class=HTMLResponse)
def oauth_callback(code: Optional[str] = Query(None), error: Optional[str] = Query(None), state: Optional[str] = Query(None), request: Request = None):
    """Handles OAuth redirect from Google, exchanges token, and notifies frontend."""
    if not _consume_oauth_state(state):
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head><title>Authorization Failed</title></head>
            <body style="font-family:sans-serif; text-align:center; padding:50px; background:#111; color:#fff;">
                <h2 style="color:#ef4444;">Invalid or expired authorization request</h2>
                <p>This YouTube connection link is invalid, expired, or was already used. Please start a new connection from the Studio dashboard.</p>
                <button onclick="window.close()" style="padding:10px 20px; background:#333; color:#fff; border:none; border-radius:6px; cursor:pointer;">Close Window</button>
            </body>
            </html>
            """,
            status_code=400
        )
    if error:
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Authorization Failed</title></head>
            <body style="font-family:sans-serif; text-align:center; padding:50px; background:#111; color:#fff;">
                <h2 style="color:#ef4444;">Authorization Cancelled or Failed</h2>
                <p>{html.escape(error, quote=True)}</p>
                <button onclick="window.close()" style="padding:10px 20px; background:#333; color:#fff; border:none; border-radius:6px; cursor:pointer;">Close Window</button>
            </body>
            </html>
            """,
            status_code=400
        )

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")

    try:
        base_url = str(request.base_url).rstrip("/")
        redirect_uri = f"{base_url}/api/v1/youtube/oauth-callback"
        channel_data = exchange_code_for_tokens(code, redirect_uri=redirect_uri)
        channel_title = channel_data.get("title", "YouTube Channel")

        # Return auto-closing popup script that informs parent window
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>YouTube Connected</title>
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        background: #0f172a;
                        color: #f8fafc;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        height: 100vh;
                        margin: 0;
                    }}
                    .card {{
                        background: #1e293b;
                        padding: 40px;
                        border-radius: 16px;
                        box-shadow: 0 10px 25px rgba(0,0,0,0.5);
                        text-align: center;
                        max-width: 400px;
                    }}
                    .btn {{
                        background: #3b82f6;
                        color: white;
                        padding: 10px 24px;
                        border-radius: 8px;
                        border: none;
                        font-weight: 600;
                        cursor: pointer;
                        margin-top: 20px;
                    }}
                </style>
            </head>
            <body>
                <div class="card">
                    <h2 style="color:#22c55e; margin-top:0;">Connected Successfully!</h2>
                    <p>Channel <strong>{channel_title}</strong> is now securely linked to AutoExplainer AI.</p>
                    <p style="font-size:13px; color:#94a3b8;">This window will close automatically...</p>
                    <button class="btn" onclick="window.close()">Close</button>
                </div>
                <script>
                    if (window.opener) {{
                        window.opener.postMessage({{ type: 'YOUTUBE_AUTH_SUCCESS', channel: {channel_data.get('channel_id')} }}, '*');
                    }}
                    setTimeout(() => {{
                        window.close();
                    }}, 1500);
                </script>
            </body>
            </html>
            """
        )
    except Exception as e:
        logger.error(f"OAuth exchange failed: {e}", exc_info=True)
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Connection Error</title></head>
            <body style="font-family:sans-serif; text-align:center; padding:50px; background:#111; color:#fff;">
                <h2 style="color:#ef4444;">OAuth Exchange Failed</h2>
                <p>{str(e)}</p>
                <button onclick="window.close()" style="padding:10px 20px; background:#333; color:#fff; border:none; border-radius:6px; cursor:pointer;">Close</button>
            </body>
            </html>
            """,
            status_code=500
        )

@router.get("/channels")
def list_channels():
    """List all connected YouTube channels (with tokens sanitized)."""
    channels = get_channel_profiles()
    return {"channels": [_sanitize_channel(c) for c in channels]}

@router.delete("/channels/{channel_id}")
def delete_channel(channel_id: str):
    """Disconnect and remove a channel."""
    deleted = delete_channel_profile(channel_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found.")
    return {"deleted": True, "message": f"Channel {channel_id} disconnected."}

@router.post("/schedule")
def schedule_video(req: ScheduleVideoRequest):
    """Queue video for background resumable upload and YouTube auto-scheduling."""
    # Validate channel exists
    channels = get_channel_profiles()
    channel = next((c for c in channels if c.get("channel_id") == req.channel_id), None)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel {req.channel_id} not found in connected channels.")

    # Validate video path
    video_path = Path(req.video_path)
    if not video_path.is_absolute():
        video_path = (STORAGE_DIR / req.video_path).resolve()
    else:
        video_path = video_path.resolve()

    if not video_path.exists() or not video_path.is_file():
        raise HTTPException(status_code=400, detail=f"Video file not found at: {req.video_path}")

    # Validate thumbnail path if provided
    thumb_path = None
    if req.thumbnail_path:
        tp = Path(req.thumbnail_path)
        if not tp.is_absolute():
            tp = (STORAGE_DIR / req.thumbnail_path).resolve()
        else:
            tp = tp.resolve()
        if tp.exists():
            thumb_path = str(tp)

    # Validate srt path if provided
    srt_path = None
    if req.srt_path:
        sp = Path(req.srt_path)
        if not sp.is_absolute():
            sp = (STORAGE_DIR / req.srt_path).resolve()
        else:
            sp = sp.resolve()
        if sp.exists():
            srt_path = str(sp)

    # Format and validate publishAt
    try:
        publish_at_iso = format_publish_at_iso(req.publish_at, tz_offset_hours=req.tz_offset_hours)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Queue upload
    task_id = start_video_schedule_task(
        channel_id=req.channel_id,
        video_path=str(video_path),
        title=req.title,
        description=req.description,
        tags=req.tags,
        publish_at_iso=publish_at_iso,
        thumbnail_path=thumb_path,
        srt_path=srt_path,
        language=req.language
    )

    return {
        "status": "queued",
        "task_id": task_id,
        "channel_title": channel.get("title"),
        "publish_at_iso": publish_at_iso,
        "message": f"Video queued for scheduling on {publish_at_iso}."
    }

@router.get("/tasks/{task_id}")
def get_task_status(task_id: str):
    """Poll progress of a video scheduling task."""
    task = upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task
