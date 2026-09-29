import pytest
import os
import json
import time
from typing import List, Dict, Any
from app.services.script_engine import (
    ScriptEngine,
    SceneBlock,
    EvidencePacket,
    StoryPlanItem,
    DialogueRefProvenance
)


class TestPhase6FSourceBoundDialogueRef:
    """
    Phase 6F: Comprehensive Verification of Source-Bound Dialogue Reference Integrity.
    Enforces that dialogue_ref must be traceable to authoritative source evidence.
    Invented, paraphrased, or hallucinated quotes safely become None (null).
    """

    # =========================================================================
    # SECTION 14: REQUIRED TESTS 1 - 12
    # =========================================================================

    def test_01_exact_source_quote_accepted(self):
        """TEST 1: Exact source quote -> accepted."""
        cues = [{"start": 10.0, "end": 15.0, "text": "Halt! Who goes there?"}]
        res = ScriptEngine.validate_dialogue_ref_provenance("Halt! Who goes there?", dialogue_timeline=cues)
        assert res.status == "SOURCE_BOUND"
        assert res.is_source_bound is True
        assert res.dialogue_ref == "Halt! Who goes there?"
        assert res.source_timestamp == 10.0
        assert res.match_type == "exact"

    def test_02_case_punctuation_variation_accepted(self):
        """TEST 2: Case/punctuation variation -> accepted."""
        cues = [{"start": 20.0, "end": 25.0, "text": "Get out of here, it's not your car!"}]
        # Reference has lowercase, missing punctuation, contraction variation
        res = ScriptEngine.validate_dialogue_ref_provenance("get out of here its not your car", dialogue_timeline=cues)
        assert res.status == "SOURCE_BOUND"
        assert res.is_source_bound is True
        assert res.dialogue_ref == "get out of here its not your car"
        assert res.source_timestamp == 20.0

    def test_03_short_valid_source_excerpt_accepted(self):
        """TEST 3: Short valid source excerpt -> accepted."""
        cues = [{"start": 30.0, "end": 40.0, "text": "And you can spend the rest of the time with your son. This money will help him get back on his feet."}]
        res = ScriptEngine.validate_dialogue_ref_provenance("spend the rest of the time with your son", dialogue_timeline=cues)
        assert res.status == "SOURCE_BOUND"
        assert res.is_source_bound is True
        assert res.match_type == "source_contained_excerpt"

    def test_04_invented_quote_same_topic_rejected(self):
        """TEST 4: Invented quote with same topic -> rejected."""
        cues = [{"start": 40.0, "end": 45.0, "text": "This is my luxury car. I love driving it."}]
        res = ScriptEngine.validate_dialogue_ref_provenance("Who scratched my car?", dialogue_timeline=cues)
        assert res.status == "NOT_SOURCE_BOUND"
        assert res.is_source_bound is False
        assert res.dialogue_ref is None

    def test_05_invented_quote_generic_words_overlap_rejected(self):
        """TEST 5: Invented quote sharing many generic words -> rejected."""
        cues = [{"start": 50.0, "end": 55.0, "text": "I don't have this kind of experience."}]
        res = ScriptEngine.validate_dialogue_ref_provenance("I don't have this kind of money.", dialogue_timeline=cues)
        assert res.status == "NOT_SOURCE_BOUND"
        assert res.is_source_bound is False
        assert res.dialogue_ref is None

    def test_06_scene_with_no_dialogue_evidence_becomes_null(self):
        """TEST 6: Scene with no dialogue evidence -> dialogue_ref becomes null."""
        script = """
[SCENE: 01:00 - 01:30]
[DIALOGUE_REF: "A quiet moment in the silent room"]
[VOICEOVER]
The detective silently walks through the empty library examining dusty books.
"""
        # Empty dialogue timeline (silent film or non-dialogue segment)
        blocks = ScriptEngine.parse_storyboard_blocks(script, dialogue_timeline=[])
        assert len(blocks) == 1
        assert blocks[0].dialogue_ref is None
        assert "detective silently walks" in blocks[0].narration_text

    def test_07_valid_narration_paraphrase_with_null_dialogue_ref(self):
        """TEST 7: Valid narration paraphrase + null dialogue_ref -> narration remains valid."""
        script = """
[SCENE: 02:00 - 02:30]
[DIALOGUE_REF: "Invented dramatic character line"]
[VOICEOVER]
The furious owner immediately confronts the trembling mother on the street.
"""
        cues = [{"start": 120.0, "end": 125.0, "text": "Unrelated dialogue about lunch."}]
        blocks = ScriptEngine.parse_storyboard_blocks(script, dialogue_timeline=cues)
        assert len(blocks) == 1
        # Invented quote is safely stripped to None
        assert blocks[0].dialogue_ref is None
        # Narration is completely preserved
        assert blocks[0].narration_text == "The furious owner immediately confronts the trembling mother on the street."
        assert blocks[0].word_count == len("The furious owner immediately confronts the trembling mother on the street.".split())

    def test_08_evidence_packet_backed_source_quote_accepted_and_traceable(self):
        """TEST 8: EvidencePacket-backed source quote -> accepted and traceable."""
        packets = [
            EvidencePacket(
                packet_id="EP-003",
                movie_start=180.0,
                movie_end=190.0,
                source_text="Never surrender the fortress to the invaders!",
                act="Act 2B",
                sequence_index=3,
                cue_index=12
            )
        ]
        script = """
[SCENE: 03:00 - 03:15]
[DIALOGUE_REF: "Never surrender the fortress to the invaders!"]
[VOICEOVER]
The general rallies his exhausted soldiers for a desperate last stand.
"""
        blocks = ScriptEngine.parse_storyboard_blocks(script, evidence_packets=packets)
        assert len(blocks) == 1
        assert blocks[0].dialogue_ref == "Never surrender the fortress to the invaders!"
        assert blocks[0].evidence_ref == "EP-003"

    def test_09_reference_from_unrelated_source_cue_rejected(self):
        """TEST 9: Reference from unrelated source cue -> rejected."""
        cues = [{"start": 10.0, "end": 15.0, "text": "Welcome to our store."}]
        res = ScriptEngine.validate_dialogue_ref_provenance("He was murdered in cold blood!", dialogue_timeline=cues)
        assert res.status == "NOT_SOURCE_BOUND"
        assert res.is_source_bound is False
        assert res.dialogue_ref is None

    def test_10_repeated_identical_phrase_chronology(self):
        """TEST 10: Repeated identical phrase at multiple timestamps retains chronology."""
        cues = [
            {"start": 50.0, "end": 55.0, "text": "Never give up!"},
            {"start": 500.0, "end": 505.0, "text": "Never give up!"}
        ]
        res1 = ScriptEngine.validate_dialogue_ref_provenance("Never give up!", dialogue_timeline=cues)
        assert res1.is_source_bound is True

        # Existing anchor_scenes_to_dialogue chronology is fully preserved
        blocks = [
            SceneBlock(movie_start=40.0, movie_end=50.0, narration_text="Opening encouragement.", dialogue_ref="Never give up!", word_count=2),
            SceneBlock(movie_start=450.0, movie_end=460.0, narration_text="Final push.", dialogue_ref="Never give up!", word_count=2),
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, cues)
        assert anchored[0].movie_start == 50.0
        assert anchored[1].movie_start == 500.0
        assert anchored[0].movie_start < anchored[1].movie_start

    def test_11_urdu_source_reference(self):
        """TEST 11: Urdu source reference accepted when source-bound, rejected when invented."""
        urdu_cues = [{"start": 100.0, "end": 105.0, "text": "بکواس بند کرو اور دفع ہو جاؤ۔"}]
        # Source-bound with slight punctuation variation
        res_valid = ScriptEngine.validate_dialogue_ref_provenance("بکواس بند کرو اور دفع ہو جاؤ", dialogue_timeline=urdu_cues)
        assert res_valid.status == "SOURCE_BOUND"
        assert res_valid.is_source_bound is True

        # Invented Urdu quote
        res_invalid = ScriptEngine.validate_dialogue_ref_provenance("یہ سچ نہیں ہے", dialogue_timeline=urdu_cues)
        assert res_invalid.status == "NOT_SOURCE_BOUND"
        assert res_invalid.is_source_bound is False
        assert res_invalid.dialogue_ref is None

    def test_12_hindi_source_reference(self):
        """TEST 12: Hindi source reference accepted when source-bound, rejected when invented."""
        hindi_cues = [{"start": 100.0, "end": 105.0, "text": "यह मेरी गाड़ी है!"}]
        # Source-bound
        res_valid = ScriptEngine.validate_dialogue_ref_provenance("यह मेरी गाड़ी है", dialogue_timeline=hindi_cues)
        assert res_valid.status == "SOURCE_BOUND"
        assert res_valid.is_source_bound is True

        # Invented Hindi quote
        res_invalid = ScriptEngine.validate_dialogue_ref_provenance("वह चला गया", dialogue_timeline=hindi_cues)
        assert res_invalid.status == "NOT_SOURCE_BOUND"
        assert res_invalid.is_source_bound is False
        assert res_invalid.dialogue_ref is None


    # =========================================================================
    # SECTION 15: ADVERSARIAL CASES (1 - 14)
    # =========================================================================

    @pytest.mark.parametrize("ref,cue_text,should_bind,pattern_id", [
        # 1. same topic, different sentence
        ("We need to purchase a new car", "We need to purchase a new house today.", False, "P1"),
        # 2. same five generic words, different final noun
        ("I was going to tell you about the robbery", "I was going to tell you about the wedding.", False, "P2"),
        # 3. same subject, different action
        ("The suspect confessed to the detective", "The suspect escaped from the detective last night.", False, "P3"),
        # 4. partial phrase from unrelated cue
        ("there is no time to lose", "there is no reason to believe this story.", False, "P4"),
        # 5. one common word
        ("Where is the diamond necklace?", "The necklace was inexpensive and fake.", False, "P5"),
        # 6. two common words
        ("The car was very fast", "The car was parked outside.", False, "P6"),
        # 7. three common words
        ("It is time to go", "It is time for lunch.", False, "P7"),
        # 8. exact phrase
        ("Halt! Who goes there?", "Halt! Who goes there?", True, "P8"),
        # 9. exact phrase with punctuation variation
        ("Halt! Who goes there?", "Halt, who goes there.", True, "P9"),
        # 10. short valid phrase
        ("Congratulations.", "Congratulations.", True, "P10"),
        # 11. repeated phrase
        ("Never surrender the fortress", "Never surrender the fortress!", True, "P11"),
        # 12. Urdu valid / invalid
        ("بکواس بند کرو اور دفع ہو جاؤ", "بکواس بند کرو اور دفع ہو جاؤ", True, "P12_valid"),
        ("یہ سچ نہیں ہے", "بکواس بند کرو اور دفع ہو جاؤ", False, "P12_invalid"),
        # 13. Hindi valid / invalid
        ("यह मेरी गाड़ी है", "यह मेरी गाड़ी है", True, "P13_valid"),
        ("वह चला गया", "यह मेरी गाड़ी है", False, "P13_invalid"),
    ])
    def test_adversarial_patterns(self, ref, cue_text, should_bind, pattern_id):
        cues = [{"start": 100.0, "end": 105.0, "text": cue_text}]
        res = ScriptEngine.validate_dialogue_ref_provenance(ref, dialogue_timeline=cues)
        assert res.is_source_bound == should_bind, f"Failed {pattern_id}: ref='{ref}', cue='{cue_text}'"
        if not should_bind:
            assert res.dialogue_ref is None
            assert res.status == "NOT_SOURCE_BOUND"
        else:
            assert res.dialogue_ref is not None
            assert res.status == "SOURCE_BOUND"

    def test_adversarial_case_14_no_source_evidence(self):
        """Pattern 14: No source evidence available -> returns null."""
        res_empty = ScriptEngine.validate_dialogue_ref_provenance("Halt! Who goes there?", dialogue_timeline=[])
        assert res_empty.is_source_bound is False
        assert res_empty.dialogue_ref is None

        res_none = ScriptEngine.validate_dialogue_ref_provenance("Halt! Who goes there?", dialogue_timeline=None, evidence_packets=None)
        assert res_none.is_source_bound is False
        assert res_none.dialogue_ref is None


    # =========================================================================
    # SECTION 13: REAL MEDIA REGRESSION
    # =========================================================================

    def test_real_media_asr_problematic_and_valid_references(self):
        """
        Specifically reproduces the two real-media problematic references observed in Phase 6D/6E:
        A: "Who scratched my car?" -> MUST BE REJECTED (None)
        B: "I don't have this kind of money." -> MUST BE REJECTED (None)
        Along with genuine source quotes that MUST BE ACCEPTED.
        """
        scratch_dir = r"C:\Users\bareera\.gemini\antigravity\brain\0cb6baf6-2175-4128-8118-405e14bb00b3\scratch"
        real_asr_path = os.path.join(scratch_dir, "real_asr_results.json")
        if not os.path.exists(real_asr_path):
            pytest.skip("Real ASR sample dataset not found in scratch directory.")

        with open(real_asr_path, "r", encoding="utf-8") as f:
            cues = json.load(f)["cues"]

        # Problematic invented reference A
        res_a = ScriptEngine.validate_dialogue_ref_provenance("Who scratched my car?", dialogue_timeline=cues)
        assert res_a.is_source_bound is False
        assert res_a.dialogue_ref is None
        assert res_a.status == "NOT_SOURCE_BOUND"

        # Problematic invented reference B
        res_b = ScriptEngine.validate_dialogue_ref_provenance("I don't have this kind of money.", dialogue_timeline=cues)
        assert res_b.is_source_bound is False
        assert res_b.dialogue_ref is None
        assert res_b.status == "NOT_SOURCE_BOUND"

        # Known valid real-media references
        valid_refs = [
            ("Get out of here.", 6.0),
            ("Get out of here, it's not your car! What's this? Who did this?", 6.0),
            ("Okay, smile, and one more time. Great!", 0.0),
            ("So we were just taking the photo.", 10.0),
            ("Thank you, sir. Have a nice day, Peter. She cannot work.", 153.03),
            ("She's some poor girl.", 163.97),
            ("Thank you so much.", 671.97),
        ]

        for ref_text, expected_ts in valid_refs:
            res = ScriptEngine.validate_dialogue_ref_provenance(ref_text, dialogue_timeline=cues)
            assert res.is_source_bound is True, f"Expected '{ref_text}' to be source-bound in real media cues!"
            assert res.dialogue_ref is not None
            assert res.status == "SOURCE_BOUND"
            assert res.source_timestamp == pytest.approx(expected_ts, abs=2.0)


    # =========================================================================
    # SECTION 17: FULL STORY-PLAN / EVIDENCE-PACKET RUNTIME PIPELINE
    # =========================================================================

    def test_story_plan_to_scene_blocks_guarantees_source_bound_or_null(self):
        """
        Tests the full production path:
        EvidencePackets -> StoryPlan -> prompt instruction -> LLM output parsing -> SceneBlock.
        Verifies that every generated SceneBlock has either a verified source-bound dialogue_ref OR None.
        """
        packets = [
            EvidencePacket(packet_id="EP-001", movie_start=10.0, movie_end=20.0, source_text="Smile for the camera!", act="Act 1", sequence_index=0),
            EvidencePacket(packet_id="EP-002", movie_start=60.0, movie_end=70.0, source_text="Hey, get away from my vehicle!", act="Act 1", sequence_index=1),
            EvidencePacket(packet_id="EP-003", movie_start=150.0, movie_end=160.0, source_text="Thank you, sir. Have a nice day.", act="Act 2A", sequence_index=2),
        ]

        story_plan = [
            StoryPlanItem(step=1, source_timestamp=10.0, act="Act 1", evidence_ref="EP-001", core_event="Photographing car", entities=["mother", "son"], narration_purpose="hook", budget_words=20),
            StoryPlanItem(step=2, source_timestamp=60.0, act="Act 1", evidence_ref="EP-002", core_event="Owner yells", entities=["owner", "car"], narration_purpose="conflict", budget_words=20),
            StoryPlanItem(step=3, source_timestamp=150.0, act="Act 2A", evidence_ref="EP-003", core_event="Office arrival", entities=["Peter"], narration_purpose="transition", budget_words=20),
        ]

        raw_llm_script = """
[SCENE: 00:10 - 00:25]
[DIALOGUE_REF: "Smile for the camera!"]
[VOICEOVER]
A joyful mother snaps a portrait of her son standing proudly on the boulevard.

[SCENE: 01:00 - 01:20]
[DIALOGUE_REF: "Who scratched my paint?"]
[VOICEOVER]
The furious owner storms out and screams about imaginary damage to his vehicle.

[SCENE: 02:30 - 02:50]
[DIALOGUE_REF: "Thank you, sir."]
[VOICEOVER]
Peter arrives at the corporate skyscraper and greets his colleague at reception.
"""
        blocks = ScriptEngine.parse_storyboard_blocks(
            raw_script=raw_llm_script,
            evidence_packets=packets,
            story_plan=story_plan
        )

        assert len(blocks) == 3

        # Block 1: Verbatim quote from EP-001 -> accepted and linked
        assert blocks[0].dialogue_ref == "Smile for the camera!"
        assert blocks[0].evidence_ref == "EP-001"
        assert blocks[0].story_step == 1

        # Block 2: Invented quote ("Who scratched my paint?") not in EP-002 -> safely nullified to None
        assert blocks[1].dialogue_ref is None
        assert "furious owner storms out" in blocks[1].narration_text
        assert blocks[1].evidence_ref == "EP-002"  # linked via chronological plan fallback
        assert blocks[1].story_step == 2

        # Block 3: Excerpt quote ("Thank you, sir.") from EP-003 -> accepted and linked
        assert blocks[2].dialogue_ref == "Thank you, sir."
        assert blocks[2].evidence_ref == "EP-003"
        assert blocks[2].story_step == 3

        # All 3 blocks satisfy: dialogue_ref is either source-bound OR None!
        for b in blocks:
            assert (b.dialogue_ref is None) or isinstance(b.dialogue_ref, str)


    # =========================================================================
    # SECTION 19: PERFORMANCE OVERHEAD BENCHMARK
    # =========================================================================

    def test_provenance_validation_performance_overhead(self):
        """
        Measures performance overhead on small and medium workloads.
        """
        # Small workload: 5 scenes against 50 cues
        small_cues = [{"start": float(i * 10), "end": float(i * 10 + 5), "text": f"This is test cue number {i} with some dialogue content."} for i in range(50)]
        refs_small = [f"This is test cue number {i}" for i in range(5)]

        t0 = time.perf_counter()
        for _ in range(20):  # 20 iterations
            for r in refs_small:
                ScriptEngine.validate_dialogue_ref_provenance(r, dialogue_timeline=small_cues)
        t_small = (time.perf_counter() - t0) / 20.0

        # Medium workload: 25 scenes against 500 cues
        med_cues = [{"start": float(i * 5), "end": float(i * 5 + 3), "text": f"This is movie cue {i} containing substantive line {i % 10}."} for i in range(500)]
        refs_med = [f"This is movie cue {i * 10}" for i in range(25)]

        t0 = time.perf_counter()
        for _ in range(5):  # 5 iterations
            for r in refs_med:
                ScriptEngine.validate_dialogue_ref_provenance(r, dialogue_timeline=med_cues)
        t_med = (time.perf_counter() - t0) / 5.0

        print(f"\n[PERFORMANCE] Small workload (5 scenes / 50 cues): {t_small * 1000:.3f} ms")
        print(f"[PERFORMANCE] Medium workload (25 scenes / 500 cues): {t_med * 1000:.3f} ms")

        # Must execute comfortably under 50ms for small and under 1000ms for 25 scenes x 500 cues
        assert t_small < 0.050, f"Small workload too slow: {t_small}s"
        assert t_med < 1.000, f"Medium workload too slow: {t_med}s"
