from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class ScriptGenerateRequest(BaseModel):
    url: Optional[str] = Field(None, description="YouTube Movie or Drama URL")
    title: Optional[str] = Field("Movie Story Recap", description="Movie or Video Title")
    plot_summary: Optional[str] = Field("", description="Optional custom plot synopsis")
    language: str = Field("en", description="Target story language code (e.g. en, es, id, ur, hi, ar)")
    persona: str = Field("hollywood_trailer", description="Storytelling persona / narrator style")
    mood: str = Field("suspense", description="Mood theme (suspense, action, emotional, upbeat)")
    duration_mins: int = Field(3, ge=1, le=15, description="Target explainer duration in minutes")
    spoiler_mode: str = Field("full_recap", description="full_recap or cliffhanger_teaser")
    format_mode: str = Field("reels_parts", description="reels_parts or full_video")
    num_parts: int = Field(3, ge=1, le=5, description="Number of series parts")

class ScriptGenerateResponse(BaseModel):
    success: bool
    title: str
    language: str
    script: str
    target_words: int
    hook_score: Dict[str, Any]
    error: Optional[str] = None

class VoicePreviewRequest(BaseModel):
    voice: str = Field(..., description="Edge-TTS voice identifier")
    language: str = Field("en", description="Language code")

class RenderExplainerRequest(BaseModel):
    url: Optional[str] = None
    script_text: str
    language: str = "en"
    voice: Optional[str] = None
    voice_speed: str = "fast"
    pitch_boost: bool = True
    aspect_ratio: str = "vertical"  # vertical, horizontal, square
    mood_theme: str = "suspense"
    burn_subtitles: bool = True
    watermark: Optional[str] = ""
    generate_thumbnails: bool = True
    generate_metadata: bool = True

class RenderExplainerResponse(BaseModel):
    success: bool
    job_id: str
    video_url: str
    duration: float
    aspect_ratio: str
    thumbnails: List[Dict[str, Any]] = []
    metadata_pack: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
