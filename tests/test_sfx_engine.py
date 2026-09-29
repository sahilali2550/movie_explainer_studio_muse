import os
import pytest
from app.core.config import SFX_DIR, AUDIO_MODES
from app.services.audio_mixer import AudioMixer

def test_sfx_assets_exist():
    assert SFX_DIR.exists()
    expected_sfx = ["whoosh", "sub_boom", "heartbeat", "clock_tick", "cash_chime"]
    for sfx in expected_sfx:
        wav_path = SFX_DIR / f"{sfx}.wav"
        assert wav_path.exists()
        assert wav_path.stat().st_size > 1000

def test_audio_modes_config():
    assert "hybrid" in AUDIO_MODES
    assert "sfx_only" in AUDIO_MODES
    assert "music_only" in AUDIO_MODES

def test_get_sfx_path():
    path = AudioMixer.get_sfx_path("whoosh")
    assert path is not None
    assert os.path.exists(path)

def test_build_sfx_cue_points():
    # Video duration 60 seconds
    scene_starts = [10.0, 25.0, 42.0]
    cues = AudioMixer.build_sfx_cue_points(
        total_duration=60.0,
        scene_starts=scene_starts,
        genre="movie_recap"
    )
    assert len(cues) >= 3
    # Check that cues contain timestamp and sound effect name
    sfx_names = [c["sfx"] for c in cues]
    assert "whoosh" in sfx_names
    assert "sub_boom" in sfx_names

def test_mix_soundtrack_sfx_only(tmp_path):
    import subprocess
    from app.core.config import get_ffmpeg_binary

    ffmpeg = get_ffmpeg_binary()
    dummy_voice = str(tmp_path / "dummy_voice.wav")
    output_mix = str(tmp_path / "sfx_mixed.mp3")

    # Generate 5s dummy voice
    subprocess.run([
        ffmpeg, "-y", "-f", "lavfi", "-i", "sine=f=300:d=5",
        "-c:a", "pcm_s16le", dummy_voice
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    success = AudioMixer.mix_soundtrack(
        voice_path=dummy_voice,
        bgm_path=None,
        output_path=output_mix,
        voice_duration=5.0,
        audio_mode="sfx_only",
        scene_starts=[1.5, 3.0],
        genre="movie_recap"
    )

    assert success is True
    assert os.path.exists(output_mix)
    assert os.path.getsize(output_mix) > 5000

