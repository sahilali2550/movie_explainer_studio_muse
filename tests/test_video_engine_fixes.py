import pytest
from app.services.video_engine import VideoEngine

def test_render_final_explainer_omits_part_badge_for_single_video(monkeypatch):
    """Verifies that PART 1 badge is NOT rendered when num_parts <= 1."""
    captured_cmds = []

    def mock_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        class MockResult:
            returncode = 0
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("os.path.exists", lambda p: True)
    monkeypatch.setattr("os.path.getsize", lambda p: 5000)

    VideoEngine.render_final_explainer(
        video_source="dummy_in.mp4",
        audio_source="dummy_in.mp3",
        output_path="dummy_out.mp4",
        duration=10.0,
        aspect_ratio="horizontal",
        burn_subtitles=False,
        watermark="@sahilcreations",
        part_number=1,
        num_parts=1,
        lang="ur"
    )

    assert len(captured_cmds) == 1
    full_cmd_str = " ".join(captured_cmds[0])
    assert "PART 1" not in full_cmd_str, "PART 1 badge must NOT be present when num_parts <= 1"
    assert "@sahilcreations" in full_cmd_str or "sahilcreations" in full_cmd_str

def test_render_final_explainer_includes_part_badge_when_num_parts_greater_than_one(monkeypatch):
    """Verifies that PART badge IS rendered when num_parts > 1."""
    captured_cmds = []

    def mock_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        class MockResult:
            returncode = 0
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("os.path.exists", lambda p: True)
    monkeypatch.setattr("os.path.getsize", lambda p: 5000)

    VideoEngine.render_final_explainer(
        video_source="dummy_in.mp4",
        audio_source="dummy_in.mp3",
        output_path="dummy_out.mp4",
        duration=10.0,
        aspect_ratio="horizontal",
        burn_subtitles=False,
        watermark="@sahilcreations",
        part_number=2,
        num_parts=3,
        lang="ur"
    )

    assert len(captured_cmds) == 1
    full_cmd_str = " ".join(captured_cmds[0])
    assert "PART 2" in full_cmd_str, "PART 2 badge must be present when num_parts=3 and part_number=2"
