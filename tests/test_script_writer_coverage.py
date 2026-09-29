"""
tests/test_script_writer_coverage.py

TDD Tests for:
1. Script Writer Full Movie Timeline Coverage & Word Budget Enforcement
2. Hook Critic Safe Splicing (never truncating the body of the script)
3. Gemini Auto-Expansion & expand_script Gemini Fallback
4. Source Video Duration propagation from transcript to Swarm and Screenwriter
5. Dialogue & Character Quote instruction in build_prompt_for_genre
"""

import re
import pytest
from unittest.mock import patch, MagicMock
from app.services.script_engine import ScriptEngine, SceneBlock
from app.services.agent_swarm import AgentSwarmEngine

SAMPLE_LONG_TRANSCRIPT = """
00:05 Hero enters the abandoned warehouse.
00:15 Hero says: "Nobody move, this ends right now!"
15:30 Heroine warns him: "The bomb is armed, we only have ten minutes."
45:00 Massive car chase through downtown streets with explosions.
75:00 The villain reveals the hidden codes: "You were too late, agent."
90:00 Final rooftop standoff, villain falls, hero and heroine secure the cipher.
"""

def test_hook_critic_never_truncates_long_script():
    """Hook critic must only optimize opening sentences, preserving the rest of a multi-scene script."""
    # Build a simulated 500-word multi-scene script
    scenes = []
    for i in range(5):
        s_min = i * 2
        e_min = s_min + 2
        scenes.append(
            f"[SCENE: {s_min:02d}:00 - {e_min:02d}:00]\n[VOICEOVER]\n"
            f"This is scene {i+1} describing detailed action with fifty words repeating over and over again "
            f"to create substantial length and verify that hook critic does not truncate later scenes. " * 3
        )
    full_script = "\n\n".join(scenes)
    orig_word_count = len(full_script.split())
    assert orig_word_count > 300

    critique = AgentSwarmEngine.hook_critic_agent(full_script, target_lang="en")
    optimized = critique.get("optimized_script", "")

    # Optimized script must NOT lose scenes
    assert "[SCENE: 08:00 - 10:00]" in optimized, "Final scene was truncated by hook critic!"
    assert len(optimized.split()) >= orig_word_count * 0.90, "Hook critic severely reduced script word count!"


def test_hook_critic_llm_response_only_replaces_opening():
    """Even if LLM returns only an opening hook, remaining scenes of the script must remain intact."""
    script = (
        "[SCENE: 00:00 - 02:00]\n[VOICEOVER]\n"
        "Weak opening sentence here. Another weak sentence here.\n\n"
        "[SCENE: 02:00 - 05:00]\n[VOICEOVER]\n"
        "Middle act with crucial action details that must never be erased.\n\n"
        "[SCENE: 05:00 - 10:00]\n[VOICEOVER]\n"
        "Final climax and ending scene."
    )
    with patch("app.services.agent_swarm.AgentSwarmEngine._call_9router", return_value="Sensational viral hook that grabs attention immediately."):
        critique = AgentSwarmEngine.hook_critic_agent(script, target_lang="en")
        opt = critique.get("optimized_script", "")
        assert "Sensational viral hook" in opt
        assert "[SCENE: 02:00 - 05:00]" in opt, "Middle scene was lost!"
        assert "[SCENE: 05:00 - 10:00]" in opt, "Final climax scene was lost!"


def test_validate_script_integrity_strict_word_budget():
    """validate_script_integrity must reject scripts that are severely under-budget for the requested duration."""
    # 10 minutes Urdu fast = 10 * 132 * 1.15 = 1518 words
    # A 600-word script (~4 minutes) must FAIL validation for a 10-minute video
    short_script = (
        "[SCENE: 00:00 - 05:00]\n[VOICEOVER]\n"
        + "یہ ایک مختصر کہانی ہے۔ " * 50
        + "\n\n[SCENE: 05:00 - 10:00]\n[VOICEOVER]\n"
        + "اور یہاں کہانی ختم ہو جاتی ہے۔ " * 25
    )
    is_valid, reason = ScriptEngine.validate_script_integrity(
        script_text=short_script,
        source_duration_sec=600.0,
        target_duration_mins=10,
        target_lang="ur",
        voice_speed="fast"
    )
    assert not is_valid, "Short script (600 words) should fail validation for 10-minute target!"
    assert "under-budget" in reason.lower() or "budget" in reason.lower()


def test_validate_script_integrity_timeline_coverage_inferred():
    """validate_script_integrity must enforce timeline coverage when source duration is provided."""
    # Source movie is 90 mins (5400s), but script scenes only go up to 10 mins (600s)
    script_stops_early = (
        "[SCENE: 00:00 - 05:00]\n[VOICEOVER]\nOpening act.\n\n"
        "[SCENE: 05:00 - 10:00]\n[VOICEOVER]\nAct stops at 10 mins."
    )
    is_valid, reason = ScriptEngine.validate_script_integrity(
        script_text=script_stops_early,
        source_duration_sec=5400.0,
        target_duration_mins=10,
        target_lang="en",
        voice_speed="fast"
    )
    assert not is_valid, "Script stopping at 10m should fail coverage for 90m movie!"
    assert "coverage" in reason.lower()


def test_build_prompt_includes_dialogue_quoting_instruction():
    """Prompt must explicitly instruct quoting character dialogues and describing turning-point actions."""
    prompt = ScriptEngine.build_prompt_for_genre(
        genre="movie_recap",
        title="Agent On The Run",
        description="Action spy thriller",
        subs_text=SAMPLE_LONG_TRANSCRIPT,
        target_lang="ur",
        duration_mins=10,
        source_video_duration_sec=5400.0
    )
    assert "dialogue" in prompt.lower()
    # Must instruct character quotes / speaking references
    assert ("hero" in prompt.lower() or "character" in prompt.lower())
    # Must include full 5-act milestones
    assert "Act 1" in prompt
    assert "Act 2" in prompt
    assert "Act 3" in prompt
    assert "Epilogue" in prompt


def test_screenwriter_agent_accepts_source_duration():
    """screenwriter_agent must accept and pass source_video_duration_sec to ScriptEngine.generate_script."""
    with patch("app.services.script_engine.ScriptEngine.generate_script") as mock_gen:
        mock_gen.return_value = {"success": True, "script": "Test script"}
        AgentSwarmEngine.screenwriter_agent(
            title="Agent On The Run",
            genre="movie_recap",
            persona="hollywood_trailer",
            target_lang="ur",
            duration_minutes=10,
            speech_velocity="fast",
            story_beats=[],
            notes="",
            subs_text=SAMPLE_LONG_TRANSCRIPT,
            source_video_duration_sec=5400.0
        )
        assert mock_gen.called
        kwargs = mock_gen.call_args.kwargs
        assert kwargs.get("source_video_duration_sec") == 5400.0


def test_expand_script_has_gemini_fallback():
    """expand_script must attempt Gemini if 9Router is unavailable or returns empty."""
    current_short = "[SCENE: 00:00 - 05:00]\n[VOICEOVER]\nShort script."
    with patch("app.services.nine_router_client.is_ninerouter_available", return_value=False), \
         patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"candidates": [{"content": {"parts": [{"text": "[SCENE: 00:00 - 10:00]\\n[VOICEOVER]\\nExpanded story narrative with full length."}]}}]}'
        mock_resp.__enter__.return_value = mock_resp
        mock_url.return_value = mock_resp

        res = ScriptEngine.expand_script(
            current_script=current_short,
            target_lang="en",
            duration_mins=10,
            voice_speed="fast",
            genre="movie_recap",
            gemini_api_key="fake-test-key"
        )
        assert res.get("success") is True
        assert "Expanded story narrative" in res.get("script", "")
