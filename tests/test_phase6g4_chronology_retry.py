# Movie Explainer Studio / AutoExplainer AI
# Phase 6G.4 — Controlled Chronology Failure Handling Unit Tests

import pytest
from unittest.mock import MagicMock, patch
from typing import List, Dict, Any

from app.services.script_engine import (
    ScriptEngine,
    SceneBlock,
    MAX_CHRONOLOGY_RETRIES
)


def load_real_cues() -> List[Dict[str, Any]]:
    """Loads realistic dialogue cues matching the historical Phase 6G audit evidence."""
    return [
        {"start": 306.71, "end": 309.50, "text": "So, what happened to the car?"},
        {"start": 320.29, "end": 323.00, "text": "Can you fix it?"},
        {"start": 440.21, "end": 443.50, "text": "I'm obviously just taking someone else's place."},
    ]


VALID_SCRIPT = """[SCENE: 01:00 - 02:00]
[DIALOGUE_REF: "So, what happened to the car?"]
[VOICEOVER]
The investigation begins immediately as detectives inspect the vehicle in the parking lot. Every scratch on the bumper suggests an intentional collision occurred earlier that morning before anyone had arrived at the facility to witness the confrontation.

[SCENE: 02:00 - 03:00]
[DIALOGUE_REF: "Can you fix it?"]
[VOICEOVER]
The distressed driver turns toward the mechanic desperately pleading for answers about repair costs. The damage is far worse than anticipated and the mechanical components require immediate specialized attention that cannot be delayed.

[SCENE: 03:00 - 04:00]
[DIALOGUE_REF: "I'm obviously just taking someone else's place."]
[VOICEOVER]
Later that evening in the corporate headquarters office, a replacement executive realizes the dangerous reality behind the sudden job offer. Every employee around the boardroom seems to understand the hidden conspiracy unfolding behind closed doors.
"""

INVERTED_SCRIPT = """[SCENE: 01:00 - 02:00]
[DIALOGUE_REF: "I'm obviously just taking someone else's place."]
[VOICEOVER]
Corporate executive office meeting discussing someone's position and salary in great depth and detail across the entire scene progression. The manager explains the contract terms clearly and notes that every single clause must be adhered to without any hesitation or deviation whatsoever.

[SCENE: 02:00 - 03:00]
[DIALOGUE_REF: "So, what happened to the car?"]
[VOICEOVER]
Earlier discussion about the damaged vehicle parked outside with comprehensive explanations and dramatic character reactions to satisfy the word count requirement. Everyone gathered around the parking lot attempting to reconstruct what transpired during the unexpected impact earlier that morning while inspecting the damage.

[SCENE: 03:00 - 04:00]
[DIALOGUE_REF: "Can you fix it?"]
[VOICEOVER]
The mechanic provides a thorough estimate while explaining the complex structural issues affecting the engine block and frame alignment throughout the remainder of the afternoon confrontation.
"""

UNGROUNDED_GAP_SCRIPT = """[SCENE: 01:00 - 02:00]
[DIALOGUE_REF: "So, what happened to the car?"]
[VOICEOVER]
The investigation begins immediately as detectives inspect the vehicle in the parking lot. Every scratch on the bumper suggests an intentional collision occurred earlier that morning before anyone had arrived at the facility to witness the confrontation.

[SCENE: 02:00 - 03:00]
[VOICEOVER]
A tense silence settles across the empty hallway as footsteps echo softly in the distance. The atmosphere grows increasingly foreboding with each passing second while characters contemplate their immediate next moves carefully.

[SCENE: 03:00 - 04:00]
[DIALOGUE_REF: "I'm obviously just taking someone else's place."]
[VOICEOVER]
Later that evening in the corporate headquarters office, a replacement executive realizes the dangerous reality behind the sudden job offer. Every employee around the boardroom seems to understand the hidden conspiracy unfolding behind closed doors.
"""

UNDERBUDGET_REPAIR_SCRIPT = """[SCENE: 01:00 - 02:00]
[DIALOGUE_REF: "So, what happened to the car?"]
[VOICEOVER]
Brief parking lot discussion about car damage.

[SCENE: 02:00 - 03:00]
[DIALOGUE_REF: "Can you fix it?"]
[VOICEOVER]
Asking mechanic for cost.

[SCENE: 03:00 - 04:00]
[DIALOGUE_REF: "I'm obviously just taking someone else's place."]
[VOICEOVER]
Short meeting in corporate office.
"""


class TestPhase6G4ChronologyRetry:
    """Targeted validation suite for Phase 6G.4 Controlled Chronology Failure Handling."""

    def test_01_valid_first_attempt_no_retry(self):
        """1. Valid first attempt: normal generation returns without triggering retry (attempts=1)."""
        cues = load_real_cues()
        mock_gen = MagicMock(return_value=VALID_SCRIPT)

        text, is_valid, report, attempts, details = ScriptEngine.generate_script_with_chronology_guard(
            generate_fn=mock_gen,
            initial_prompt="Generate storyboard",
            duration_mins=1,
            voice_speed="fast",
            target_lang="en",
            source_video_duration_sec=240.0,
            dialogue_timeline=cues
        )

        assert is_valid is True
        assert attempts == 1
        assert mock_gen.call_count == 1
        assert "passed all universal integrity gates" in report

    def test_02_chronology_inversion_triggers_exactly_one_retry(self):
        """2. Chronology inversion on attempt 1 triggers exactly one targeted regeneration (attempts=2)."""
        cues = load_real_cues()
        # Mock responses: Call 1 = inverted, Call 2 = valid corrected
        mock_gen = MagicMock(side_effect=[INVERTED_SCRIPT, VALID_SCRIPT])

        text, is_valid, report, attempts, details = ScriptEngine.generate_script_with_chronology_guard(
            generate_fn=mock_gen,
            initial_prompt="Generate storyboard",
            duration_mins=1,
            voice_speed="fast",
            target_lang="en",
            source_video_duration_sec=240.0,
            dialogue_timeline=cues
        )

        assert mock_gen.call_count == 2
        assert attempts == 2
        assert is_valid is True

        # Verify the repair prompt passed to Call 2 is diagnostic and targeted
        repair_call_args = mock_gen.call_args_list[1][0][0]
        assert "CHRONOLOGICAL ORDER REPAIR REQUIRED" in repair_call_args
        assert "440.21" in repair_call_args
        assert "306.71" in repair_call_args
        assert "Preserve the supplied StoryPlan sequence" in repair_call_args

    def test_03_retry_produces_valid_storyboard_final_result_is_valid(self):
        """3. When retry produces a valid storyboard, the final result is valid."""
        cues = load_real_cues()
        mock_gen = MagicMock(side_effect=[INVERTED_SCRIPT, VALID_SCRIPT])

        text, is_valid, report, attempts, details = ScriptEngine.generate_script_with_chronology_guard(
            generate_fn=mock_gen,
            initial_prompt="Generate storyboard",
            duration_mins=1,
            voice_speed="fast",
            target_lang="en",
            source_video_duration_sec=240.0,
            dialogue_timeline=cues
        )

        assert is_valid is True
        assert attempts == 2
        assert "So, what happened to the car?" in text
        assert "passed all universal integrity gates" in report

    def test_04_retry_also_invalid_returns_is_valid_false(self):
        """4. When retry also fails chronology, returns is_valid=False with structured diagnostic failure."""
        cues = load_real_cues()
        # Mock responses: Call 1 = inverted, Call 2 = also inverted
        mock_gen = MagicMock(side_effect=[INVERTED_SCRIPT, INVERTED_SCRIPT])

        text, is_valid, report, attempts, details = ScriptEngine.generate_script_with_chronology_guard(
            generate_fn=mock_gen,
            initial_prompt="Generate storyboard",
            duration_mins=1,
            voice_speed="fast",
            target_lang="en",
            source_video_duration_sec=240.0,
            dialogue_timeline=cues
        )

        assert is_valid is False
        assert attempts == 2
        assert mock_gen.call_count == 2
        assert "violates source chronology after one controlled repair attempt" in report
        assert "440.21" in report
        assert "306.71" in report

    def test_05_retry_does_not_exceed_one_additional_attempt(self):
        """5. Retry count does not exceed MAX_CHRONOLOGY_RETRIES = 1 under any circumstances."""
        assert MAX_CHRONOLOGY_RETRIES == 1
        assert ScriptEngine.MAX_CHRONOLOGY_RETRIES == 1
        cues = load_real_cues()
        mock_gen = MagicMock(side_effect=[INVERTED_SCRIPT, INVERTED_SCRIPT, VALID_SCRIPT])

        text, is_valid, report, attempts, details = ScriptEngine.generate_script_with_chronology_guard(
            generate_fn=mock_gen,
            initial_prompt="Generate storyboard",
            duration_mins=1,
            voice_speed="fast",
            target_lang="en",
            source_video_duration_sec=240.0,
            dialogue_timeline=cues
        )

        # Strictly 2 calls, never 3
        assert mock_gen.call_count == 2
        assert attempts == 2
        assert is_valid is False

    def test_06_ungrounded_timestamp_gap_does_not_trigger_chronology_retry(self):
        """6. Ungrounded timestamp gaps (None) are skipped without false error or retry."""
        cues = load_real_cues()
        mock_gen = MagicMock(return_value=UNGROUNDED_GAP_SCRIPT)

        text, is_valid, report, attempts, details = ScriptEngine.generate_script_with_chronology_guard(
            generate_fn=mock_gen,
            initial_prompt="Generate storyboard",
            duration_mins=1,
            voice_speed="fast",
            target_lang="en",
            source_video_duration_sec=240.0,
            dialogue_timeline=cues
        )

        assert is_valid is True
        assert attempts == 1
        assert mock_gen.call_count == 1

    def test_07_phase6f_invalid_dialogue_ref_remains_none(self):
        """7. Phase 6F source-bound dialogue_ref validation remains strict; ungrounded ref -> None."""
        cues = load_real_cues()
        prov = ScriptEngine.validate_dialogue_ref_provenance(
            dialogue_ref="Completely fabricated quote not in film.",
            dialogue_timeline=cues
        )
        assert prov.is_source_bound is False
        assert prov.source_timestamp is None

    def test_08_validator_continues_to_reject_historical_440_306_320_ordering(self):
        """8. Validator continues to strictly reject the historical 440 -> 306 -> 320 ordering."""
        cues = load_real_cues()
        blocks = ScriptEngine.parse_storyboard_blocks(
            raw_script=INVERTED_SCRIPT,
            dialogue_timeline=cues,
            enforce_source_provenance=True
        )
        is_valid, msg, details = ScriptEngine.validate_storyboard_chronology(
            blocks=blocks,
            dialogue_timeline=cues
        )
        assert is_valid is False
        assert details.get("failure_type") == "source_grounded_chronology_inversion"
        assert details.get("current_source_timestamp") == 306.71
        assert details.get("previous_source_timestamp") == 440.21

    def test_09_retry_does_not_reorder_scene_blocks_programmatically(self):
        """9. Neither validator nor retry ever sorts SceneBlocks mechanically."""
        cues = load_real_cues()
        blocks = ScriptEngine.parse_storyboard_blocks(
            raw_script=INVERTED_SCRIPT,
            dialogue_timeline=cues
        )
        original_texts = [b.narration_text for b in blocks]
        # Run validator
        ScriptEngine.validate_storyboard_chronology(blocks=blocks, dialogue_timeline=cues)
        after_texts = [b.narration_text for b in blocks]
        assert original_texts == after_texts

    def test_10_retry_does_not_weaken_nominal_word_timeline_integrity(self):
        """10. If retry fixes chronology but drops content below word budget, integrity gate rejects it."""
        cues = load_real_cues()
        # Mock responses: Call 1 = inverted, Call 2 = under-budget (only 14 words)
        mock_gen = MagicMock(side_effect=[INVERTED_SCRIPT, UNDERBUDGET_REPAIR_SCRIPT])

        text, is_valid, report, attempts, details = ScriptEngine.generate_script_with_chronology_guard(
            generate_fn=mock_gen,
            initial_prompt="Generate storyboard",
            duration_mins=1,
            voice_speed="fast",
            target_lang="en",
            source_video_duration_sec=240.0,
            dialogue_timeline=cues
        )

        assert is_valid is False
        assert attempts == 2
        assert "severely under-budget" in report

    def test_11_existing_forward_only_anchor_invariant_remains_unchanged(self):
        """11. Existing forward-only anchor invariant in anchor_scenes_to_dialogue remains unchanged."""
        cues = load_real_cues()
        b1 = SceneBlock(movie_start=0.0, movie_end=10.0, narration_text="Block 1", word_count=2, dialogue_ref="I'm obviously just taking someone else's place.")
        b2 = SceneBlock(movie_start=0.0, movie_end=10.0, narration_text="Block 2", word_count=2, dialogue_ref="So, what happened to the car?")
        anchored = ScriptEngine.anchor_scenes_to_dialogue([b1, b2], cues)
        # Block 1 anchors to 440.21s
        assert anchored[0].movie_start == 440.21
        # Block 2 cannot go backward to 306.71s; clamped by forward barrier to at least 440.21 + min_dur
        assert anchored[1].movie_start >= anchored[0].movie_start

    def test_12_render_safety_verification_blocks_visual_anchoring(self):
        """12. Render Safety: invalid script after failed retry completely bypasses anchor_scenes_to_dialogue."""
        cues = load_real_cues()
        with patch.object(ScriptEngine, "anchor_scenes_to_dialogue", wraps=ScriptEngine.anchor_scenes_to_dialogue) as mock_anchor:
            blocks = ScriptEngine.parse_storyboard_blocks(
                raw_script=INVERTED_SCRIPT,
                dialogue_timeline=cues,
                enforce_source_provenance=True
            )
            # Confirms anchor_scenes_to_dialogue was NEVER called on chronology-invalid script
            mock_anchor.assert_not_called()
            for b in blocks:
                assert b.chronology_valid is False
                assert "Chronology violation" in (b.chronology_error or "")

    def test_13_generate_script_provider_integration_triggers_retry(self):
        """13. generate_script end-to-end: provider with initial inverted script retries and succeeds."""
        cues = load_real_cues()
        with patch("app.services.openai_client.call_chatgpt_llm", side_effect=[INVERTED_SCRIPT, VALID_SCRIPT]) as mock_call, \
             patch("app.services.openai_client.is_openai_available", return_value=True), \
             patch("app.services.openai_client.load_openai_settings", return_value={"api_key": "sk-test", "model": "gpt-4o"}):
            res = ScriptEngine.generate_script(
                title="Test Title",
                description="Test Description",
                subs_text="So, what happened to the car?\nCan you fix it?\nI'm obviously just taking someone else's place.",
                duration_mins=1,
                source_video_duration_sec=240.0,
                openai_api_key="sk-test",
                ai_provider="openai",
                story_beats=[],
                dialogue_timeline=cues
            )
            assert res.get("is_valid") is True
            assert res.get("attempts") == 2
            assert mock_call.call_count == 2

    def test_14_generate_script_provider_integration_fails_structured_diagnostic(self):
        """14. generate_script end-to-end: provider failing retry returns structured failure diagnostic."""
        cues = load_real_cues()
        with patch("app.services.openai_client.call_chatgpt_llm", side_effect=[INVERTED_SCRIPT, INVERTED_SCRIPT]) as mock_call, \
             patch("app.services.openai_client.is_openai_available", return_value=True), \
             patch("app.services.openai_client.load_openai_settings", return_value={"api_key": "sk-test", "model": "gpt-4o"}):
            res = ScriptEngine.generate_script(
                title="Test Title",
                description="Test Description",
                subs_text="So, what happened to the car?\nCan you fix it?\nI'm obviously just taking someone else's place.",
                duration_mins=1,
                source_video_duration_sec=240.0,
                openai_api_key="sk-test",
                ai_provider="openai",
                story_beats=[],
                dialogue_timeline=cues
            )
            assert res.get("is_valid") is False
            assert res.get("attempts") == 2
            assert res.get("failure_type") == "chronology_violation"
            assert "violates source chronology after one controlled repair attempt" in res.get("error", "")
            assert mock_call.call_count == 2

