import os
import json
import subprocess
import pytest
from pathlib import Path
from PIL import Image

from app.core.config import get_ffmpeg_binary, TEMP_DIR
from app.services.video_engine import VideoEngine
from app.services.script_engine import ScriptEngine, SceneBlock
from app.services.voice_engine import VoiceEngine
from app.services.audio_mixer import AudioMixer
from app.services.thumbnail_engine import ThumbnailEngine
from app.services.metadata_engine import MetadataEngine

def generate_synthetic_mp4(output_path: str, duration: int = 6):
    """Generates a real minimal synthetic MP4 with video and audio using FFmpeg."""
    ffmpeg = get_ffmpeg_binary()
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=640x360:rate=24",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg synthetic video generation failed: {res.stderr}")


def generate_synthetic_mp3(output_path: str, duration: int = 4):
    """Generates a real minimal synthetic MP3 using FFmpeg."""
    ffmpeg = get_ffmpeg_binary()
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"sine=frequency=880:duration={duration}",
        "-c:a", "libmp3lame",
        output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg synthetic audio generation failed: {res.stderr}")


def test_end_to_end_synthetic_pipeline(tmp_path):
    """
    Synthetic End-to-End Live Integration Smoke Test.
    Tests the complete pipeline:
    1. Video Ingestion & Probe (VideoEngine)
    2. Dynamic Pacing & Storyboard (ScriptEngine)
    3. Voice Cues & Boundary Timing (VoiceEngine)
    4. Dynamic Sidechain Ducking & Audio Mixing (AudioMixer)
    5. Audio-Locked Scene Cutting & Final Explainer Assembly (VideoEngine)
    6. Viral Thumbnail Generation (ThumbnailEngine)
    7. Multi-Genre Viral Social Metadata Suite (MetadataEngine)
    """
    job_id = "smoke_e2e_test"

    # Step 1: Ingest & Probe Media
    source_video = str(tmp_path / "source_input.mp4")
    generate_synthetic_mp4(source_video, duration=6)
    assert os.path.exists(source_video)

    probe = VideoEngine.probe_media(source_video)
    assert probe["duration"] >= 5.5
    assert probe["width"] == 640
    assert probe["height"] == 360
    assert probe["has_audio"] is True

    dur = VideoEngine.get_duration(source_video)
    assert dur >= 5.5

    # Step 2: Dynamic Pacing & Storyboard Segmentation
    pacing = ScriptEngine.calculate_dynamic_pacing(source_duration_sec=7200.0) # 2-hour movie
    assert pacing["category"] == "feature_film"
    assert pacing["target_duration_mins"] == 8
    assert pacing["target_scenes"] == 11

    # Mock script with storyboard timestamps
    sample_script = (
        "[SCENE: 00:00 - 00:02]\n"
        "[VOICEOVER] He entered the dark warehouse unaware of the danger.\n"
        "[SCENE: 00:02 - 00:05]\n"
        "[VOICEOVER] Suddenly, the alarm blared through the halls."
    )
    blocks = ScriptEngine.parse_storyboard_blocks(sample_script)
    assert len(blocks) == 2
    assert blocks[0].movie_start == 0.0
    assert blocks[0].movie_end == 2.0

    # Step 3: Voice Timing & Audio-Visual Lock Sync
    speech_audio = str(tmp_path / f"{job_id}_voice.mp3")
    generate_synthetic_mp3(speech_audio, duration=4)

    # Generate companion cues file
    cues_data = [
        {"text": "He entered the dark warehouse unaware of the danger.", "start": 0.0, "end": 2.0},
        {"text": "Suddenly, the alarm blared through the halls.", "start": 2.0, "end": 4.0}
    ]
    with open(str(tmp_path / f"{job_id}_voice_cues.json"), "w", encoding="utf-8") as f:
        json.dump(cues_data, f)

    speech_dur = VoiceEngine.get_audio_duration(speech_audio)
    assert speech_dur >= 3.8

    extracted_cues = VoiceEngine.get_speech_cues(speech_audio)
    assert len(extracted_cues) == 2
    assert extracted_cues[0]["end"] == 2.0

    timed_blocks = ScriptEngine.assign_narration_timing(blocks, speech_dur, extracted_cues)
    assert len(timed_blocks) == 2
    assert timed_blocks[0].speech_dur == 2.0
    assert timed_blocks[1].speech_dur == 2.0

    # Step 4: Dynamic Sidechain Ducking & Audio Mixing
    mixed_audio = str(tmp_path / f"{job_id}_soundtrack.mp3")
    mix_success = AudioMixer.mix_soundtrack(
        voice_path=speech_audio,
        bgm_path=None,  # Generates mood synth automatically
        output_path=mixed_audio,
        voice_duration=speech_dur,
        audio_mode="hybrid",
        scene_starts=[0.0, 2.0],
        genre="movie_recap"
    )
    assert mix_success is True
    assert os.path.exists(mixed_audio)

    # Step 5: Audio-Locked Scene Cutting & Final Assembly
    alc_video = str(tmp_path / f"{job_id}_alc.mp4")
    alc_res = VideoEngine.build_audio_locked_scene_clips(
        input_video=source_video,
        scene_blocks=timed_blocks,
        temp_dir=str(tmp_path),
        job_id=job_id,
        output_video=alc_video
    )
    assert os.path.exists(alc_res)
    alc_probe = VideoEngine.probe_media(alc_res)
    assert alc_probe["duration"] >= 3.8

    final_render = str(tmp_path / f"{job_id}_final.mp4")
    render_ok = VideoEngine.render_final_explainer(
        video_source=alc_res,
        audio_source=mixed_audio,
        output_path=final_render,
        duration=speech_dur,
        aspect_ratio="vertical",
        burn_subtitles=True,
        scene_subtitles=[b.narration_text for b in timed_blocks],
        watermark="AutoExplainer AI",
        anti_copyright_drift=True
    )
    assert render_ok is True
    assert os.path.exists(final_render)
    final_probe = VideoEngine.probe_media(final_render)
    assert final_probe["duration"] > 0
    assert final_probe["has_audio"] is True

    # Step 6: Viral Thumbnail Generation (ThumbnailEngine)
    thumbs = ThumbnailEngine.generate_3_thumbnail_options(
        video_path=source_video,
        job_id=job_id,
        movie_title="The Warehouse Heist",
        lang="en",
        custom_hooks=["DON'T LOOK BACK!", "THE BIGGEST TRAP!", "NO ESCAPE!"]
    )
    assert len(thumbs) == 3
    for opt in thumbs:
        assert "url" in opt
        assert opt["width"] == 1920
        assert opt["height"] == 1080
        assert "badge" in opt

    # Step 7: Viral Social Metadata Suite (MetadataEngine)
    meta = MetadataEngine.generate_viral_metadata(
        movie_title="The Warehouse Heist",
        script_snippet=sample_script,
        lang="en",
        genre="movie_recap"
    )
    assert meta["movie_title"] == "The Warehouse Heist"
    assert len(meta["titles"]) == 3
    assert "The Warehouse Heist" in meta["description"]
    assert "COPYRIGHT & FAIR USE DISCLAIMER" in meta["description"]
    assert len(meta["tags"]) > 0
    assert len(meta["hashtags"]) > 0
    assert len(meta["pinned_comment"]) > 0
