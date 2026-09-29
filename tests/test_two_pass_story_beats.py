import pytest
from unittest.mock import patch
from app.services.nine_router_client import (
    extract_story_beats_with_9router,
    generate_ai_thumbnail_strategy_with_9router
)
from app.services.script_engine import ScriptEngine


def test_extract_story_beats_with_9router():
    """
    Verifies that extract_story_beats_with_9router parses 9Router's LLM response
    into structured story beats with valid timestamps.
    """
    mock_llm_reply = """[
        {"beat": 1, "timestamp": "01:15 - 01:45", "title": "Hero Arrives", "action": "Detective enters the abandoned warehouse"},
        {"beat": 2, "timestamp": "14:20 - 14:40", "title": "First Clue", "action": "Discovers a hidden safe behind the painting"},
        {"beat": 3, "timestamp": "45:10 - 45:35", "title": "Climax Battle", "action": "Confronts the mastermind on the rooftop"}
    ]"""

    with patch("app.services.nine_router_client.is_ninerouter_available", return_value=True), \
         patch("app.services.nine_router_client.call_ninerouter_llm", return_value=mock_llm_reply):

        beats = extract_story_beats_with_9router(
            title="Mystery of the Warehouse",
            dialogues_text="[01:15] Detective: Let's see what's inside...",
            genre="movie_recap",
            duration_sec=3600.0
        )

        assert len(beats) == 3
        assert beats[0]["beat"] == 1
        assert beats[0]["timestamp"] == "01:15 - 01:45"
        assert "Hero Arrives" in beats[0]["title"]
        assert beats[2]["timestamp"] == "45:10 - 45:35"


def test_generate_ai_thumbnail_strategy_with_9router():
    """
    Verifies that 9Router analyzes story beats and selects the optimal
    climax keyframe timestamp and psychological hook text.
    """
    mock_strategy = """{
        "best_timestamp_sec": 2710.0,
        "best_timestamp_formatted": "45:10",
        "hook_phrases": ["THE FINAL SECRET!", "HE WAS LIED TO!", "DON'T LOOK DOWN!"],
        "badge": "HIGH SUSPENSE"
    }"""

    beats = [
        {"beat": 1, "timestamp": "01:15 - 01:45", "title": "Hero Arrives"},
        {"beat": 2, "timestamp": "45:10 - 45:35", "title": "Climax Battle"}
    ]

    with patch("app.services.nine_router_client.is_ninerouter_available", return_value=True), \
         patch("app.services.nine_router_client.call_ninerouter_llm", return_value=mock_strategy):

        strategy = generate_ai_thumbnail_strategy_with_9router(
            title="Mystery Movie",
            story_beats=beats,
            target_lang="en"
        )

        assert strategy is not None
        assert strategy["best_timestamp_sec"] == 2710.0
        assert len(strategy["hook_phrases"]) >= 3
        assert strategy["badge"] == "HIGH SUSPENSE"


def test_script_engine_build_prompt_incorporates_story_beats():
    """
    Verifies that ScriptEngine incorporates story beats into the prompt
    when provided.
    """
    beats = [
        {"beat": 1, "timestamp": "02:10 - 02:35", "title": "Meeting", "action": "Characters meet"},
        {"beat": 2, "timestamp": "20:40 - 21:05", "title": "Betrayal", "action": "Betrayal revealed"}
    ]
    prompt = ScriptEngine.build_prompt_for_genre(
        genre="movie_recap",
        title="Test Movie",
        description="A suspense thriller",
        subs_text="Dialogues here",
        target_lang="ur",
        duration_mins=5,
        story_beats=beats
    )

    assert "STORY BEATS" in prompt or "CHRONOLOGICAL STORY BEATS" in prompt
    assert "02:10 - 02:35" in prompt
    assert "20:40 - 21:05" in prompt
