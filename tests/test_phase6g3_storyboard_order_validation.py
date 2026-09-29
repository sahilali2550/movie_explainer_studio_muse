import os
import sys
import json
import pytest

sys.path.insert(0, os.path.abspath("backend"))
from app.services.script_engine import ScriptEngine, SceneBlock

REAL_ASR_PATH = r"C:\Users\bareera\.gemini\antigravity\brain\0cb6baf6-2175-4128-8118-405e14bb00b3\scratch\real_asr_results.json"


def load_real_cues():
    if os.path.exists(REAL_ASR_PATH):
        with open(REAL_ASR_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("cues", [])
    # Minimal fallback mock cues matching the real timestamps if file unavailable
    return [
        {"start": 306.71, "end": 308.71, "text": "So, what happened to the car?"},
        {"start": 320.29, "end": 324.40, "text": "I had to pay for his treatment. But now he's fine, right?"},
        {"start": 440.21, "end": 443.21, "text": "I'm obviously just taking someone else's place."},
    ]


class TestPhase6G3StoryboardOrderValidation:
    """
    Phase 6G.3: StoryPlan -> Final Storyboard Order Contract and Minimal Deterministic Validation.
    Verifies that the system detects source-grounded chronological inversion before visual anchoring/rendering.
    """

    def test_01_chronological_grounded_scenes_pass(self):
        """1. Chronological grounded scenes with valid source dialogue references pass validation."""
        timeline = [
            {"start": 10.0, "end": 14.0, "text": "The secret code was discovered in the library."},
            {"start": 50.0, "end": 55.0, "text": "We need to evacuate the civilians right now."},
            {"start": 120.0, "end": 125.0, "text": "The final battle will begin at dawn tomorrow."}
        ]
        blocks = [
            SceneBlock(movie_start=0.0, movie_end=15.0, narration_text="The detective enters the library.", word_count=5, dialogue_ref="The secret code was discovered in the library."),
            SceneBlock(movie_start=20.0, movie_end=35.0, narration_text="Sirens echo as the team prepares.", word_count=6, dialogue_ref="We need to evacuate the civilians right now."),
            SceneBlock(movie_start=40.0, movie_end=55.0, narration_text="Dawn breaks over the battlefield.", word_count=5, dialogue_ref="The final battle will begin at dawn tomorrow.")
        ]
        is_valid, msg, details = ScriptEngine.validate_storyboard_chronology(blocks, dialogue_timeline=timeline)
        assert is_valid is True
        assert details.get("is_valid") is True
        assert len(details.get("violations", [])) == 0

    def test_02_scene_source_timestamps_ascending_pass(self):
        """2. Scene source timestamps: 100 -> 200 -> 300 pass."""
        blocks = [
            SceneBlock(movie_start=10.0, movie_end=20.0, narration_text="Scene one.", word_count=2, source_timestamp=100.0),
            SceneBlock(movie_start=30.0, movie_end=40.0, narration_text="Scene two.", word_count=2, source_timestamp=200.0),
            SceneBlock(movie_start=50.0, movie_end=60.0, narration_text="Scene three.", word_count=2, source_timestamp=300.0),
        ]
        is_valid, msg, details = ScriptEngine.validate_storyboard_chronology(blocks)
        assert is_valid is True
        assert "validated successfully" in msg.lower()

    def test_03_equal_source_timestamps_pass(self):
        """3. Equal source timestamps: 100 -> 100 -> 200 pass."""
        blocks = [
            SceneBlock(movie_start=10.0, movie_end=20.0, narration_text="Scene one part A.", word_count=4, source_timestamp=100.0),
            SceneBlock(movie_start=20.0, movie_end=30.0, narration_text="Scene one part B.", word_count=4, source_timestamp=100.0),
            SceneBlock(movie_start=30.0, movie_end=40.0, narration_text="Scene two.", word_count=2, source_timestamp=200.0),
        ]
        is_valid, msg, details = ScriptEngine.validate_storyboard_chronology(blocks)
        assert is_valid is True

    def test_04_inversion_fails(self):
        """4. Inversion: 100 -> 300 -> 200 fail."""
        blocks = [
            SceneBlock(movie_start=10.0, movie_end=20.0, narration_text="Early event.", word_count=2, source_timestamp=100.0),
            SceneBlock(movie_start=30.0, movie_end=40.0, narration_text="Later climax event.", word_count=3, source_timestamp=300.0),
            SceneBlock(movie_start=50.0, movie_end=60.0, narration_text="Middle complication.", word_count=2, source_timestamp=200.0),
        ]
        is_valid, msg, details = ScriptEngine.validate_storyboard_chronology(blocks)
        assert is_valid is False
        assert details.get("is_valid") is False
        assert details.get("scene_index") == 3
        assert details.get("previous_source_timestamp") == 300.0
        assert details.get("current_source_timestamp") == 200.0
        assert "Chronology violation" in msg

    def test_05_unknown_source_timestamp_does_not_create_false_violation(self):
        """5. Unknown source timestamp: 100 -> None -> 200 does not create false violation."""
        blocks = [
            SceneBlock(movie_start=10.0, movie_end=20.0, narration_text="First scene with grounding.", word_count=4, source_timestamp=100.0),
            SceneBlock(movie_start=30.0, movie_end=40.0, narration_text="Silent visual transition.", word_count=3, source_timestamp=None),
            SceneBlock(movie_start=50.0, movie_end=60.0, narration_text="Second scene with grounding.", word_count=4, source_timestamp=200.0),
        ]
        is_valid, msg, details = ScriptEngine.validate_storyboard_chronology(blocks)
        assert is_valid is True

        # Test leading None: None -> 100 -> 200
        blocks_leading_none = [
            SceneBlock(movie_start=10.0, movie_end=20.0, narration_text="Opening montage.", word_count=2, source_timestamp=None),
            SceneBlock(movie_start=30.0, movie_end=40.0, narration_text="First event.", word_count=2, source_timestamp=100.0),
            SceneBlock(movie_start=50.0, movie_end=60.0, narration_text="Second event.", word_count=2, source_timestamp=200.0),
        ]
        is_valid2, _, _ = ScriptEngine.validate_storyboard_chronology(blocks_leading_none)
        assert is_valid2 is True

    def test_06_scene_with_no_dialogue_evidence_does_not_get_invented_source_timestamp(self):
        """6. Scene with no dialogue/evidence does not get an invented source timestamp."""
        script = """[SCENE: 05:00 - 05:30]
[VOICEOVER]
The silent sunset spreads across the horizon as characters walk without speaking.
"""
        blocks = ScriptEngine.parse_storyboard_blocks(script, dialogue_timeline=[], enforce_source_provenance=True)
        assert len(blocks) == 1
        assert blocks[0].dialogue_ref is None
        assert blocks[0].evidence_ref is None
        assert getattr(blocks[0], "source_timestamp", None) is None

    def test_07_historical_scene_10_11_12_pattern_fails_validation(self):
        """7. Historical Scene 10 -> 11 -> 12 pattern fails validation with diagnostic message."""
        cues = load_real_cues()
        # Scene 10: corporate office meeting taking someone's place (source 440.21s)
        # Scene 11: car explanation dialogue ref "So, what happened to the car?" (Cue 91 at 306.71s)
        # Scene 12: sick son treatment dialogue ref "I had to pay for his treatment. But now he's fine, right?" (Cue 94 at 320.29s)
        blocks = [
            SceneBlock(
                movie_start=360.0,
                movie_end=371.0,
                narration_text="A meeting takes place to review the urgent financial matters affecting the department.",
                word_count=13,
                source_timestamp=440.21,
                evidence_ref="EP-024"
            ),
            SceneBlock(
                movie_start=400.0,
                movie_end=412.0,
                narration_text="Later, questions arise regarding what really happened to the luxury car and why it was parked there.",
                word_count=16,
                dialogue_ref="So, what happened to the car?"
            ),
            SceneBlock(
                movie_start=440.0,
                movie_end=454.0,
                narration_text="She explains that she had to sell her possessions to pay for her sick son's essential medical treatment.",
                word_count=17,
                dialogue_ref="I had to pay for his treatment. But now he's fine, right?"
            )
        ]
        is_valid, msg, details = ScriptEngine.validate_storyboard_chronology(blocks, dialogue_timeline=cues)
        assert is_valid is False
        assert details.get("scene_index") == 2  # Scene 11 in this list is index 2 (1-based)
        assert details.get("previous_source_timestamp") == pytest.approx(440.21, abs=0.5)
        assert details.get("current_source_timestamp") == pytest.approx(306.71, abs=0.5)
        assert "440.21" in msg
        assert "306.71" in msg
        assert "So, what happened to the car?" in msg

    def test_08_validator_does_not_reorder_scene_blocks(self):
        """8. Validator does NOT reorder SceneBlocks."""
        b1 = SceneBlock(movie_start=10.0, movie_end=20.0, narration_text="B1 text", word_count=2, source_timestamp=400.0)
        b2 = SceneBlock(movie_start=20.0, movie_end=30.0, narration_text="B2 text", word_count=2, source_timestamp=100.0)
        b3 = SceneBlock(movie_start=30.0, movie_end=40.0, narration_text="B3 text", word_count=2, source_timestamp=200.0)
        blocks = [b1, b2, b3]

        # Call validator
        ScriptEngine.validate_storyboard_chronology(blocks)

        # Assert identity and sequence are completely preserved
        assert len(blocks) == 3
        assert blocks[0] is b1
        assert blocks[1] is b2
        assert blocks[2] is b3
        assert blocks[0].source_timestamp == 400.0
        assert blocks[1].source_timestamp == 100.0
        assert blocks[2].source_timestamp == 200.0

    def test_09_existing_forward_only_anchor_invariant_remains_unchanged(self):
        """9. Existing forward-only anchor invariant remains unchanged."""
        timeline = [
            {"start": 100.0, "end": 105.0, "text": "Opening scene dialogue."},
            {"start": 200.0, "end": 205.0, "text": "Middle scene dialogue."},
            {"start": 300.0, "end": 305.0, "text": "Climax scene dialogue."}
        ]
        blocks = [
            SceneBlock(movie_start=0.0, movie_end=10.0, narration_text="Opening", word_count=1, dialogue_ref="Opening scene dialogue."),
            SceneBlock(movie_start=50.0, movie_end=60.0, narration_text="Middle", word_count=1, dialogue_ref="Middle scene dialogue."),
            SceneBlock(movie_start=100.0, movie_end=110.0, narration_text="Climax", word_count=1, dialogue_ref="Climax scene dialogue.")
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, timeline)
        for i in range(len(anchored) - 1):
            assert anchored[i].movie_start <= anchored[i + 1].movie_start

    def test_10_existing_phase6f_provenance_behavior_remains_unchanged(self):
        """10. Existing Phase 6F provenance behavior remains unchanged."""
        cues = [{"start": 50.0, "end": 55.0, "text": "Real dialogue from the actual movie transcript."}]
        
        # Valid source quote -> SOURCE_BOUND
        prov_valid = ScriptEngine.validate_dialogue_ref_provenance(
            dialogue_ref="Real dialogue from the actual movie transcript.",
            dialogue_timeline=cues
        )
        assert prov_valid.is_source_bound is True
        assert prov_valid.source_timestamp == 50.0

        # Hallucinated quote -> NOT_SOURCE_BOUND
        prov_fake = ScriptEngine.validate_dialogue_ref_provenance(
            dialogue_ref="Invented dialogue that never appeared in the film.",
            dialogue_timeline=cues
        )
        assert prov_fake.is_source_bound is False
        assert prov_fake.dialogue_ref is None

    def test_11_parse_storyboard_blocks_blocks_anchoring_on_chronology_violation(self):
        """11. parse_storyboard_blocks halts visual anchoring when chronology is violated."""
        cues = load_real_cues()
        # Script with Scene 10 (taking someone's place at 440.21s) followed by Scene 11 (car question at 306.71s)
        inverted_script = """[SCENE: 06:00 - 06:40]
[DIALOGUE_REF: "I'm obviously just taking someone else's place."]
[VOICEOVER]
A meeting takes place to review the urgent financial matters affecting the department.

[SCENE: 06:40 - 07:20]
[DIALOGUE_REF: "So, what happened to the car?"]
[VOICEOVER]
Later, questions arise regarding what really happened to the luxury car and why it was parked there.
"""
        blocks = ScriptEngine.parse_storyboard_blocks(inverted_script, dialogue_timeline=cues)
        assert len(blocks) == 2
        # Verify chronology violation is recorded on blocks
        assert blocks[0].chronology_valid is False
        assert blocks[1].chronology_valid is False
        assert "Chronology violation" in blocks[0].chronology_error
        # Verify visual anchoring was blocked: blocks were NOT passed to anchor_scenes_to_dialogue
        # If anchored, Scene 11 would have been pushed to 535.96s. Here it stays at unanchored nominal start 400.0s
        assert blocks[1].movie_start == 400.0
        assert blocks[1].is_authoritative is False

    def test_12_validate_script_integrity_integrates_chronology_check(self):
        """12. validate_script_integrity flags source chronology violation when timeline provided."""
        cues = load_real_cues()
        inverted_script = """[SCENE: 01:00 - 02:00]
[DIALOGUE_REF: "I'm obviously just taking someone else's place."]
[VOICEOVER]
Corporate executive office meeting discussing someone's position and salary in great depth and detail to ensure sufficient spoken word count across the entire scene progression. The manager explains the contract terms clearly and notes that every single clause must be adhered to without any hesitation or deviation whatsoever.

[SCENE: 02:00 - 03:00]
[DIALOGUE_REF: "So, what happened to the car?"]
[VOICEOVER]
Earlier discussion about the damaged vehicle parked outside with comprehensive explanations and dramatic character reactions to satisfy the word count requirement. Everyone gathered around the parking lot attempting to reconstruct what transpired during the unexpected impact earlier that morning while inspecting the damage.
"""
        is_valid, report = ScriptEngine.validate_script_integrity(
            script_text=inverted_script,
            source_duration_sec=180.0,
            target_duration_mins=1,
            dialogue_timeline=cues
        )
        assert is_valid is False
        assert "failed chronology gate" in report.lower()
        assert "440.21" in report
        assert "306.71" in report

