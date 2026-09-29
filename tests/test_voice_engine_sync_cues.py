import os
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.services.voice_engine import VoiceEngine

def test_get_audio_duration_ffprobe_success(monkeypatch, tmp_path):
    """When ffprobe succeeds, get_audio_duration returns parsed duration."""
    fake_audio = tmp_path / "speech.mp3"
    fake_audio.write_bytes(b"dummy audio bytes")

    class MockProcess:
        returncode = 0
        stdout = "14.250000\n"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockProcess())

    dur = VoiceEngine.get_audio_duration(str(fake_audio))
    assert dur == 14.25

def test_get_audio_duration_ffprobe_fails_falls_back_to_cues(monkeypatch, tmp_path):
    """When ffprobe fails, get_audio_duration falls back to companion cues.json last end."""
    fake_audio = tmp_path / "narration.mp3"
    fake_audio.write_bytes(b"dummy audio bytes")

    cues_file = tmp_path / "narration_cues.json"
    cues_data = [
        {"start": 0.0, "end": 3.2, "text": "First sentence."},
        {"start": 3.2, "end": 8.75, "text": "Second sentence."}
    ]
    cues_file.write_text(json.dumps(cues_data))

    class MockProcess:
        returncode = 1
        stdout = ""
        stderr = "ffprobe failed"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockProcess())

    dur = VoiceEngine.get_audio_duration(str(fake_audio))
    assert dur == 8.75

def test_get_audio_duration_raises_runtime_error_when_unavailable(monkeypatch, tmp_path):
    """When ffprobe fails and no companion cues.json exists, RuntimeError must be raised."""
    fake_audio = tmp_path / "corrupt.mp3"
    fake_audio.write_bytes(b"corrupt")

    class MockProcess:
        returncode = 1
        stdout = ""
        stderr = "ffprobe failed"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockProcess())

    with pytest.raises(RuntimeError, match="Unable to determine audio duration"):
        VoiceEngine.get_audio_duration(str(fake_audio))

@pytest.mark.anyio
async def test_synthesize_cloned_story_propagates_cues_to_output(tmp_path, monkeypatch):
    """synthesize_cloned_story must copy companion cues from temp_raw to output_path cues location."""
    out_audio = tmp_path / "cloned_out.mp3"

    async def mock_synth_speech(text, voice, out_p, rate="+0%", pitch="-8Hz"):
        # Create fake temp_raw audio file
        with open(out_p, "wb") as f:
            f.write(b"x" * 2000)
        # Create fake companion cues file for temp_raw
        raw_cues = os.path.splitext(out_p)[0] + "_cues.json"
        with open(raw_cues, "w", encoding="utf-8") as f:
            json.dump([{"start": 0.0, "end": 5.0, "text": "Cloned voice test"}], f)
        return True

    monkeypatch.setattr(VoiceEngine, "synthesize_speech", mock_synth_speech)

    class MockSubprocess:
        returncode = 0
        def __init__(self, *args, **kwargs):
            # simulate ffmpeg writing out_audio
            with open(str(out_audio), "wb") as f:
                f.write(b"x" * 2500)

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockSubprocess())

    ok = await VoiceEngine.synthesize_cloned_story("Sample text", "en", str(out_audio))
    assert ok is True

    expected_cues_file = tmp_path / "cloned_out_cues.json"
    assert expected_cues_file.exists(), "Companion cues file must be copied to output_path_cues.json"

    with open(expected_cues_file, "r", encoding="utf-8") as jf:
        cues = json.load(jf)
    assert len(cues) == 1
    assert cues[0]["text"] == "Cloned voice test"
