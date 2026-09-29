import pytest
from unittest.mock import patch
from app.services.audio_mixer import AudioMixer

def test_mix_voiceover_and_bgm_uses_sidechain_and_normalize_zero(monkeypatch, tmp_path):
    """Verifies that mix_voiceover_and_bgm uses sidechaincompress and amix normalize=0."""
    captured_cmds = []

    class MockResult:
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        out_p = cmd[-1]
        with open(out_p, "wb") as f:
            f.write(b"dummy audio content")
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    v_path = str(tmp_path / "voice.wav")
    b_path = str(tmp_path / "bgm.mp3")
    o_path = str(tmp_path / "mixed.mp4")
    with open(v_path, "wb") as f: f.write(b"voice")
    with open(b_path, "wb") as f: f.write(b"bgm")

    ok = AudioMixer.mix_voiceover_and_bgm(v_path, b_path, o_path, 15.0, bgm_volume=0.15)
    assert ok is True
    assert len(captured_cmds) == 1

    full_cmd = " ".join(captured_cmds[0])
    assert "sidechaincompress" in full_cmd, "Must use sidechaincompress for dynamic ducking"
    assert ("threshold=0.08" in full_cmd or "threshold=0.125" in full_cmd)
    assert "ratio=4" in full_cmd
    assert "normalize=0" in full_cmd, "amix must have normalize=0 to preserve voiceover level"

def test_mix_soundtrack_hybrid_uses_sidechain_and_normalize_zero(monkeypatch, tmp_path):
    """Verifies mix_soundtrack in hybrid mode sidechains BGM and sets amix normalize=0."""
    captured_cmds = []

    class MockResult:
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        out_p = cmd[-1]
        with open(out_p, "wb") as f:
            f.write(b"dummy audio content")
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    v_path = str(tmp_path / "voice.wav")
    b_path = str(tmp_path / "bgm.mp3")
    o_path = str(tmp_path / "master.mp3")
    with open(v_path, "wb") as f: f.write(b"voice")
    with open(b_path, "wb") as f: f.write(b"bgm")

    ok = AudioMixer.mix_soundtrack(
        voice_path=v_path,
        bgm_path=b_path,
        output_path=o_path,
        voice_duration=20.0,
        audio_mode="hybrid"
    )
    assert ok is True
    assert len(captured_cmds) == 1

    full_cmd = " ".join(captured_cmds[0])
    assert "sidechaincompress" in full_cmd, "Hybrid mix must dynamically sidechain BGM"
    assert "normalize=0" in full_cmd, "amix must specify normalize=0"
    assert "apad=whole_dur=20.0" in full_cmd, "Voiceover must be padded to full duration"

def test_create_isolated_dub_track_standard_loudnorm_and_normalize_zero(monkeypatch, tmp_path):
    """Verifies create_isolated_dub_track standardizes loudnorm to I=-14:TP=-1.5:LRA=11."""
    captured_cmds = []

    class MockResult:
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        out_p = cmd[-1]
        with open(out_p, "wb") as f:
            f.write(b"dummy audio content")
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    v_path = str(tmp_path / "voice.wav")
    b_path = str(tmp_path / "bgm.mp3")
    o_path = str(tmp_path / "dub.mp3")
    with open(v_path, "wb") as f: f.write(b"voice")
    with open(b_path, "wb") as f: f.write(b"bgm")

    # With BGM
    ok_with_bgm = AudioMixer.create_isolated_dub_track(v_path, b_path, o_path, 30.0)
    assert ok_with_bgm is True
    cmd_bgm = " ".join(captured_cmds[-1])
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in cmd_bgm
    assert "normalize=0" in cmd_bgm
    assert "sidechaincompress" in cmd_bgm

    # Without BGM
    o_path_nobgm = str(tmp_path / "dub_nobgm.mp3")
    ok_no_bgm = AudioMixer.create_isolated_dub_track(v_path, None, o_path_nobgm, 30.0)
    assert ok_no_bgm is True
    cmd_nobgm = " ".join(captured_cmds[-1])
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in cmd_nobgm
    assert "apad=whole_dur=30.0" in cmd_nobgm
