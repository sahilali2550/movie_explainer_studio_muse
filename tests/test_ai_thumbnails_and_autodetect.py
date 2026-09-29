import os
import pytest
from unittest.mock import patch, MagicMock
from app.services.script_engine import ScriptEngine
from app.services.nine_router_client import (
    craft_cinematic_thumbnail_prompt,
    generate_movie_specific_hooks,
    generate_ai_image_with_9router
)
from app.services.thumbnail_engine import ThumbnailEngine


def test_auto_detect_creative_context_genres():
    """Verifies that auto_detect_creative_context harmonizes genre, persona, and mood from title/plot."""
    # Horror / Mystery test
    horror_ctx = ScriptEngine.auto_detect_creative_context(
        title="The Conjuring House",
        description="A terrifying haunted mansion where a demon terrorizes a family.",
        transcript_sample="She heard footsteps in the attic... the door slammed shut and blood was on the mirror."
    )
    assert horror_ctx["mood"] in ["suspense", "tense"]
    assert horror_ctx["spoiler_mode"] == "full_recap"

    # Action / Crime test
    action_ctx = ScriptEngine.auto_detect_creative_context(
        title="John Wick Gangster Chase",
        description="Hitman takes down the entire Russian mafia after a deadly ambush with guns and explosions.",
        transcript_sample="He fired three rounds through the glass and eliminated the cartel guards."
    )
    assert action_ctx["mood"] in ["tense", "action"]
    assert action_ctx["persona"] in ["hollywood_trailer", "viral_fast"]

    # Romance / Emotional Drama test
    drama_ctx = ScriptEngine.auto_detect_creative_context(
        title="Ten Years of Loving You",
        description="A tragic story of heartbreak, tears, and a girl who waited ten years for her dying lover.",
        transcript_sample="She cried alone in the hospital corridor holding his last letter."
    )
    assert drama_ctx["mood"] == "emotional"
    assert drama_ctx["spoiler_mode"] == "full_recap"


def test_craft_cinematic_thumbnail_prompt():
    """Verifies that craft_cinematic_thumbnail_prompt generates an ultra-realistic 16:9 cinema visual prompt."""
    prompt = craft_cinematic_thumbnail_prompt(
        title="Midnight Express",
        plot_summary="A daring prison escape through dark underground tunnels.",
        climax_beat="The guard catches him right at the final steel door.",
        genre="movie_recap"
    )
    assert "cinematic" in prompt.lower()
    assert "16:9" in prompt or "youtube" in prompt.lower()
    assert "Midnight Express" in prompt or "prison" in prompt.lower() or "escape" in prompt.lower()


def test_generate_movie_specific_hooks():
    """Verifies that thumbnail hook generation provides 3 punchy, movie-specific clickbait hooks."""
    with patch("app.services.nine_router_client.call_ninerouter_llm") as mock_query:
        mock_query.return_value = "1. 10 سال کا سچ سامنے آگیا!\n2. کیا وہ اسے دھوکہ دے رہا تھا؟\n3. اس رات ہسپتال میں کیا ہوا؟"
        hooks = generate_movie_specific_hooks(
            title="Ten Years Of Loving You",
            plot_summary="A woman discovers her lover hid a terminal illness for 10 years.",
            lang="ur"
        )
        assert len(hooks) == 3
        assert any("10" in h or "سال" in h or "سچ" in h for h in hooks)


def test_generate_ai_image_with_9router_fallback_on_offline():
    """Verifies that generate_ai_image_with_9router returns None gracefully when 9router endpoint is offline."""
    with patch("requests.post") as mock_post:
        mock_post.side_effect = Exception("Connection refused to 9router")
        res = generate_ai_image_with_9router("A test prompt for thumbnail image", size="1280x720")
        assert res is None, "Should return None on connection error so fallback takes over"
