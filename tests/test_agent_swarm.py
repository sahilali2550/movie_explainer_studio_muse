import pytest
import asyncio
from unittest.mock import patch, MagicMock
from app.services.agent_swarm import AgentSwarmEngine

SAMPLE_TRANSCRIPT = """
00:00 In the darkest corner of the city, detective Marcus found the golden cipher.
00:15 The cipher revealed a deadly conspiracy that nobody saw coming.
01:10 Marcus confronted Elena at the high-stakes skyscraper gala.
01:45 Shots were fired as Elena escaped with the master key.
02:30 The final showdown on the suspension bridge ended with an explosive betrayal.
"""

def test_detective_agent_offline_fallback():
    """Verify detective agent extracts story context and beats from transcript with robust fallback."""
    result = AgentSwarmEngine.detective_agent(
        transcript_text=SAMPLE_TRANSCRIPT,
        video_title_hint="The Golden Cipher Mystery"
    )
    assert result is not None
    assert "title" in result
    assert "genre" in result
    assert "persona" in result
    assert "mood" in result
    assert "story_beats" in result
    assert len(result["story_beats"]) >= 2
    assert result["title"] != ""

def test_hook_critic_agent_auto_upgrade():
    """Verify hook critic detects weak hooks and upgrades them to 90+ retention score."""
    weak_hook = "This video is about Marcus who went to a city and met Elena."
    critique = AgentSwarmEngine.hook_critic_agent(
        script_text=weak_hook,
        target_lang="en"
    )
    assert critique is not None
    assert "original_score" in critique
    assert "optimized_script" in critique
    assert "final_score" in critique
    # Final score must reach high-retention virality threshold
    assert critique["final_score"] >= 85

def test_art_director_agent_climax_extraction():
    """Verify art director identifies climax moment and generates 3 curiosity hook phrases."""
    story_beats = [
        {"beat": 1, "time_range": "00:00 - 00:30", "summary": "Marcus finds the cipher"},
        {"beat": 2, "time_range": "01:10 - 01:45", "summary": "Elena pulls gun at skyscraper"},
        {"beat": 3, "time_range": "02:30 - 03:00", "summary": "Massive explosion on bridge, shocking climax betrayal"}
    ]
    result = AgentSwarmEngine.art_director_agent(
        story_beats=story_beats,
        title="The Golden Cipher Mystery",
        target_lang="ur"
    )
    assert result is not None
    assert "climax_timestamp" in result
    assert "hook_options" in result
    assert len(result["hook_options"]) == 3
    assert result["climax_timestamp"] > 0

def test_seo_agent_generates_complete_pack():
    """Verify SEO agent generates titles, description, 25 tags, and pinned comment."""
    result = AgentSwarmEngine.seo_agent(
        title="The Golden Cipher Mystery",
        story_summary="Marcus uncovers a deadly plot on the suspension bridge.",
        target_lang="en"
    )
    assert result is not None
    assert "viral_titles" in result
    assert len(result["viral_titles"]) >= 3
    assert "description" in result
    assert "tags" in result
    assert len(result["tags"]) >= 10
    assert "pinned_comment" in result

def test_run_parallel_swarm_orchestration():
    """Verify parallel swarm executes Detective, Screenwriter, Art Director, and SEO concurrently."""
    swarm_result = asyncio.run(AgentSwarmEngine.run_parallel_swarm(
        transcript_text=SAMPLE_TRANSCRIPT,
        video_title_hint="The Golden Cipher Mystery",
        target_lang="ur",
        duration_minutes=3,
        speech_velocity="fast",
        narrator_voice="ur-PK-AsadNeural"
    ))
    assert swarm_result is not None
    assert swarm_result.get("success") is True
    assert "context" in swarm_result
    assert "script" in swarm_result
    assert "hook_score" in swarm_result
    assert "thumbnail_strategy" in swarm_result
    assert "seo_pack" in swarm_result
