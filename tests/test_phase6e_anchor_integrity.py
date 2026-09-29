"""
Phase 6E — Anchor Integrity Hardening Regression Suite.
Verifies:
1. Weak / incidental lexical false match outlier rejection.
2. Forward starvation prevention (weak late anchor must not permanently starve earlier legitimate evidence).
3. Preservation of explicit dialogue_ref priority.
4. Preservation of strong multi-token exact matches.
5. Preservation of strong semantic retrieval.
6. Real Phase 6D regression cases.
"""
import sys
import pytest

sys.path.insert(0, "backend")

from app.services.script_engine import (
    ScriptEngine,
    SceneBlock,
    DictEmbeddingProvider
)


class TestPhase6EAnchorIntegrity:

    def test_1_incidental_common_word_false_match(self):
        """
        TEST 1 — INCIDENTAL COMMON-WORD FALSE MATCH
        Narration: 'the mother takes a photo next to the luxury car'
        Source has:
          A. early cue (10.0s) with 'taking' + 'photo' (2 matching tokens)
          B. later cue (440.0s) with single common word 'taking'
        Expected:
          The correct early cue at 10.0s must be selected, NOT the later 440.0s cue.
        """
        blocks = [
            SceneBlock(
                movie_start=15.0,
                movie_end=25.0,
                narration_text="The mother takes a photo next to the luxury car.",
                word_count=9
            )
        ]
        dialogue_timeline = [
            {"start": 10.0,  "end": 15.0,  "text": "So we were just taking the photo here."},
            {"start": 440.0, "end": 445.0, "text": "I am obviously taking someone else place."},
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        assert anchored[0].movie_start == 10.0, (
            f"Expected early photo cue at 10.0s, got {anchored[0].movie_start}s"
        )

    def test_2_single_word_incidental_match_rejected(self):
        """
        TEST 2 — SINGLE-WORD INCIDENTAL MATCH REJECTION
        A narration block with weak lexical overlap (single common word, e.g. 'work' or 'taking')
        against a far-away cue (e.g. 500s away) must NOT jump hundreds of seconds merely because
        one common token matches.
        Expected: weak distant candidate is rejected and safe AI/proportional timestamp is preserved.
        """
        blocks = [
            SceneBlock(
                movie_start=20.0,
                movie_end=35.0,
                narration_text="The woman desperately tries to find work to support her child.",
                word_count=10
            )
        ]
        # Cue at 550.0s only shares the single common 4-letter word 'work'
        dialogue_timeline = [
            {"start": 15.0,  "end": 20.0,  "text": "Hello, how are you today?"},
            {"start": 550.0, "end": 555.0, "text": "I have to work late tonight."},
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        # The distant single-word cue at 550.0s must NOT hijack this early scene!
        # Should stay near its original movie_start (20.0s) rather than leaping to 550.0s.
        assert anchored[0].movie_start < 100.0, (
            f"Distant weak match at 550.0s should be rejected; got movie_start={anchored[0].movie_start}s"
        )

    def test_3_forward_starvation_prevention(self):
        """
        TEST 3 — FORWARD STARVATION
        Scene A -> correct early anchor (100.0s)
        Scene B -> weak late candidate (800.0s, single common token)
        Scene C -> legitimate earlier source evidence (200.0s, 3 exact matching tokens)

        Expected:
        Weak late Scene B candidate must NOT permanently starve Scene C.
        Scene C must anchor to its legitimate evidence at 200.0s,
        and Scene B must not remain at 800.0s (which would violate chronology).
        """
        blocks = [
            SceneBlock(movie_start=90.0,  movie_end=120.0, narration_text="The detective enters the building.", word_count=5),
            SceneBlock(movie_start=130.0, movie_end=160.0, narration_text="He continues to search for clues.", word_count=6),
            SceneBlock(movie_start=170.0, movie_end=200.0, narration_text="The suspect confronts the officer inside.", word_count=6),
        ]
        dialogue_timeline = [
            {"start": 100.0, "end": 105.0, "text": "The detective enters the building right now."},  # Scene A match (3 exact tokens)
            {"start": 200.0, "end": 205.0, "text": "The suspect confronts the officer inside."},     # Scene C match (4 exact tokens)
            {"start": 800.0, "end": 805.0, "text": "We need to search somewhere else."},             # Scene B weak match (1 token 'search')
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 3
        assert anchored[0].movie_start == 100.0, f"Scene A expected 100.0s, got {anchored[0].movie_start}"
        # Scene C must anchor to 200.0s despite Scene B having a distant match
        assert anchored[2].movie_start == 200.0, f"Scene C expected 200.0s, got {anchored[2].movie_start}"
        # Chronology must be preserved: A <= B <= C
        assert anchored[0].movie_start <= anchored[1].movie_start <= anchored[2].movie_start, (
            f"Chronology violated: {[b.movie_start for b in anchored]}"
        )
        assert anchored[1].movie_start <= 200.0, (
            f"Scene B must not remain at 800.0s when Scene C is at 200.0s; got {anchored[1].movie_start}"
        )

    def test_4_strong_late_anchor_remains_valid(self):
        """
        TEST 4 — STRONG LATE ANCHOR MUST REMAIN VALID
        A genuinely strong late anchor (e.g. 3 exact tokens) must still be preserved
        and must maintain forward ordering for subsequent scenes.
        """
        blocks = [
            SceneBlock(movie_start=100.0, movie_end=130.0, narration_text="Hero arrives in the town.", word_count=5),
            SceneBlock(movie_start=800.0, movie_end=830.0, narration_text="The grand finale explosive showdown climax.", word_count=6),
            SceneBlock(movie_start=840.0, movie_end=870.0, narration_text="Peace is finally restored everywhere.", word_count=5),
        ]
        dialogue_timeline = [
            {"start": 100.0, "end": 105.0, "text": "Hero arrives in the town today."},
            {"start": 800.0, "end": 805.0, "text": "The grand finale explosive showdown climax is here!"},
            {"start": 850.0, "end": 855.0, "text": "Peace is finally restored everywhere now."},
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 3
        assert anchored[0].movie_start == 100.0
        assert anchored[1].movie_start == 800.0
        assert anchored[2].movie_start == 850.0
        assert anchored[0].movie_start <= anchored[1].movie_start <= anchored[2].movie_start

    def test_5_explicit_dialogue_ref_priority_preserved(self):
        """
        TEST 5 — EXPLICIT DIALOGUE_REF PRIORITY
        A valid explicit dialogue_ref must continue to receive top priority,
        even when distant from target movie_start.
        """
        blocks = [
            SceneBlock(
                movie_start=2000.0,
                movie_end=2030.0,
                narration_text="Discussion about recent events.",
                dialogue_ref="You can spend the rest of the time with your son",
                word_count=4
            )
        ]
        dialogue_timeline = [
            {"start": 100.0,  "end": 105.0,  "text": "And you can spend the rest of the time with your son."},
            {"start": 1990.0, "end": 1995.0, "text": "Recent events discussion continues."},
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        assert anchored[0].movie_start == 100.0

    def test_6_semantic_retrieval_guard_interaction(self):
        """
        TEST 6 — SEMANTIC RETRIEVAL
        When semantic provider produces strong evidence (similarity >= 0.40),
        the new guard must NOT incorrectly reject a genuinely strong semantic match.
        """
        embeddings = {
            "The investigator realizes the victim died from poison.": [1.0, 0.0, 0.0],
            "The forensic specialist confirms toxic chemicals in blood.": [0.95, 0.05, 0.0],
            "Unrelated conversation about coffee.": [0.0, 1.0, 0.0],
        }
        provider = DictEmbeddingProvider(embeddings)

        blocks = [
            SceneBlock(
                movie_start=2500.0,
                movie_end=2530.0,
                narration_text="The investigator realizes the victim died from poison.",
                word_count=8
            )
        ]
        dialogue_timeline = [
            {"start": 100.0,  "end": 105.0,  "text": "Unrelated conversation about coffee."},
            {"start": 2600.0, "end": 2605.0, "text": "The forensic specialist confirms toxic chemicals in blood."},
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(
            blocks, dialogue_timeline, embedding_provider=provider
        )

        assert len(anchored) == 1
        # Semantic match at 2600.0s must win and be accepted
        assert anchored[0].movie_start == 2600.0

    def test_7_real_phase6d_substring_false_ref_reproduction(self):
        """
        TEST 7 — REAL PHASE 6D SUBSTRING FALSE REF REPRODUCTION
        In Phase 6D:
        Scene 2 had dialogue_ref: "Get out of here, it's not your car! What's this? Who did this?"
        Cue at 94.41s was: "You."
        The old code did `(len(norm_ref) > 8 and norm_cue in norm_ref)`, treating "you" as an
        exact 1000-point match and leaping to 94.41s.
        Correct behavior:
        "You." must NOT match as an exact dialogue_ref quote.
        The real cue at 6.0s ("Hey! Hey! Get out of here, it's not your car!") must win!
        """
        blocks = [
            SceneBlock(
                movie_start=40.0,
                movie_end=52.0,
                narration_text="Suddenly the furious car owner storms over and screams at them to get away from his vehicle immediately.",
                dialogue_ref="Get out of here, it's not your car! What's this? Who did this?",
                word_count=18
            )
        ]
        dialogue_timeline = [
            {"start": 0.0,   "end": 6.0,   "text": "Okay, smile, and one more time. Great!"},
            {"start": 6.0,   "end": 10.0,  "text": "Hey! Hey! Get out of here, it's not your car!"},
            {"start": 10.0,  "end": 11.0,  "text": "So we were just taking the photo."},
            {"start": 94.41, "end": 96.41, "text": "You."},  # 1-word cue that used to hijack Scene 2
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        assert anchored[0].movie_start == 6.0, (
            f"Scene 2 must anchor to 6.0s (the actual car owner shouting line), NOT 94.41s ('You.'). Got {anchored[0].movie_start}"
        )

    def test_8_adversarial_one_common_token_unrelated(self):
        """
        Adversarial 1: Single common token in unrelated text far away must be rejected.
        """
        blocks = [
            SceneBlock(
                movie_start=50.0,
                movie_end=80.0,
                narration_text="The detective inspects the broken window in the dark hallway.",
                word_count=10
            )
        ]
        # Distant cue shares only the word 'broken' (len 6)
        dialogue_timeline = [
            {"start": 10.0,  "end": 15.0,  "text": "Good morning everybody."},
            {"start": 900.0, "end": 905.0, "text": "I dropped the plate and it is broken."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start < 100.0

    def test_9_adversarial_two_weak_common_tokens(self):
        """
        Adversarial 2: Two weak common tokens across the film.
        """
        blocks = [
            SceneBlock(
                movie_start=50.0,
                movie_end=80.0,
                narration_text="The man saw the car speeding away.",
                word_count=7
            )
        ]
        # Distant cue at 800s has 'saw' and 'car'
        dialogue_timeline = [
            {"start": 10.0,  "end": 15.0,  "text": "Quiet evening in the neighborhood."},
            {"start": 800.0, "end": 805.0, "text": "I saw a red car parked outside."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        # Multi-token overlap ('saw', 'car') provides valid corroboration (exact_count=2)
        assert anchored[0].movie_start == 800.0

    def test_10_adversarial_strong_three_token_match(self):
        """
        Adversarial 3: Strong three-token match far away must be preserved (Rule A).
        """
        blocks = [
            SceneBlock(
                movie_start=50.0,
                movie_end=80.0,
                narration_text="The detective interrogates the prime suspect thoroughly.",
                word_count=7
            )
        ]
        dialogue_timeline = [
            {"start": 10.0,   "end": 15.0,   "text": "Just another quiet morning."},
            {"start": 1200.0, "end": 1205.0, "text": "The detective interrogates the prime suspect right now."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 1200.0

    def test_11_adversarial_correct_late_cue_weak_early_cue(self):
        """
        Adversarial 7: Correct late cue must not be captured by a weak early cue.
        """
        blocks = [
            SceneBlock(
                movie_start=1500.0,
                movie_end=1530.0,
                narration_text="The hero finally confronts the mastermind villain in the secret laboratory.",
                word_count=10
            )
        ]
        dialogue_timeline = [
            {"start": 30.0,   "end": 35.0,   "text": "We need to clean the room."},  # 0 or weak match
            {"start": 1520.0, "end": 1525.0, "text": "The hero confronts the mastermind villain!"}, # 4 exact tokens
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 1520.0

    def test_12_adversarial_multiple_legitimate_repeated_phrases(self):
        """
        Adversarial 8: Multiple legitimate repeated phrases anchor in forward chronological order.
        """
        blocks = [
            SceneBlock(movie_start=100.0, movie_end=130.0, narration_text="We must survive the harsh winter.", word_count=6),
            SceneBlock(movie_start=900.0, movie_end=930.0, narration_text="We must survive the harsh winter.", word_count=6),
        ]
        dialogue_timeline = [
            {"start": 105.0, "end": 110.0, "text": "We must survive the harsh winter together."},
            {"start": 910.0, "end": 915.0, "text": "We must survive the harsh winter together once more."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 2
        assert anchored[0].movie_start == 105.0
        assert anchored[1].movie_start == 910.0
        assert anchored[0].movie_start <= anchored[1].movie_start

    def test_13_adversarial_scene_with_no_valid_cue(self):
        """
        Adversarial 9: Scene with no valid cue falls back cleanly to movie_start without error.
        """
        blocks = [
            SceneBlock(movie_start=300.0, movie_end=330.0, narration_text="Complete silence across the deserted valley.", word_count=6)
        ]
        dialogue_timeline = [
            {"start": 10.0, "end": 15.0, "text": "Hello there."},
            {"start": 20.0, "end": 25.0, "text": "Good afternoon."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 300.0

    def test_14_adversarial_empty_dialogue_timeline(self):
        """
        Adversarial 10: Empty dialogue timeline handles gracefully without crash.
        """
        blocks = [
            SceneBlock(movie_start=50.0, movie_end=80.0, narration_text="The journey begins.", word_count=3),
            SceneBlock(movie_start=150.0, movie_end=180.0, narration_text="The journey ends.", word_count=3),
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, [])
        assert len(anchored) == 2
        assert anchored[0].movie_start == 50.0
        assert anchored[1].movie_start == 150.0

    def test_15_adversarial_asr_generated_cues(self):
        """
        Adversarial 11: Real-world ASR-generated cues with float timestamps.
        """
        blocks = [
            SceneBlock(movie_start=2.0, movie_end=14.0, narration_text="The photographer tells everyone to smile.", word_count=6)
        ]
        dialogue_timeline = [
            {"start": 0.124, "end": 5.981, "text": "Okay smile and one more time great"},
            {"start": 6.012, "end": 9.876, "text": "Hey hey get out of here"},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 0.12

    def test_16_adversarial_multilingual_text(self):
        """
        Adversarial 12: Multilingual Urdu & Hindi text grounding preserved.
        """
        blocks = [
            SceneBlock(movie_start=20.0, movie_end=35.0, narration_text="پولیس افسر نے مجرم کو پکڑ لیا", word_count=6)
        ]
        dialogue_timeline = [
            {"start": 10.0, "end": 15.0, "text": "موسم اچھا ہے"},
            {"start": 25.0, "end": 30.0, "text": "پولیس افسر نے مجرم کو پکڑ لیا ہے"},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 25.0

    # =========================================================================
    # PHASE 6E.2 — TARGETED REGRESSION TESTS (TESTS A THROUGH F)
    # =========================================================================

    def test_17_test_a_nonexistent_dialogue_ref_rejected(self):
        """
        TEST A: Reference has 'money', Cue has 'experience'.
        Ref: "I don't have this kind of money."
        Cue: "I don't have this kind of experience." (at 500.0s)
        Expected: NOT a strong direct reference. Distant cue at 500.0s must be rejected.
        """
        blocks = [
            SceneBlock(
                movie_start=50.0,
                movie_end=65.0,
                narration_text="The distressed woman worries about vehicle damages.",
                dialogue_ref="I don't have this kind of money.",
                word_count=7
            )
        ]
        dialogue_timeline = [
            {"start": 10.0,  "end": 15.0,  "text": "Quiet morning outside."},
            {"start": 500.0, "end": 505.0, "text": "I don't have this kind of experience."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        # Must NOT jump to 500.0s based on false partial dialogue_ref match
        assert anchored[0].movie_start < 100.0, (
            f"Distant false cue at 500.0s must be rejected, got {anchored[0].movie_start}s"
        )

    def test_18_test_b_exact_dialogue_ref_strong_match(self):
        """
        TEST B: Genuine dialogue reference match with substantive words.
        Ref: "I need the car repaired."
        Cue: "I need the car repaired." (at 350.0s)
        Expected: Strong match (anchors to 350.0s).
        """
        blocks = [
            SceneBlock(
                movie_start=50.0,
                movie_end=65.0,
                narration_text="Discussion about automotive repairs.",
                dialogue_ref="I need the car repaired.",
                word_count=4
            )
        ]
        dialogue_timeline = [
            {"start": 10.0,  "end": 15.0,  "text": "Good morning."},
            {"start": 350.0, "end": 355.0, "text": "I need the car repaired right away."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 350.0, (
            f"Expected strong anchor at 350.0s, got {anchored[0].movie_start}s"
        )

    def test_19_test_c_partial_legitimate_extension(self):
        """
        TEST C: Partial legitimate subquote extension.
        Ref: "Get out of here."
        Cue: "Hey, get out of here, it's not your car." (at 6.0s)
        Expected: Valid substantive match (anchors to 6.0s).
        """
        blocks = [
            SceneBlock(
                movie_start=30.0,
                movie_end=45.0,
                narration_text="The car owner screams at them.",
                dialogue_ref="Get out of here.",
                word_count=6
            )
        ]
        dialogue_timeline = [
            {"start": 6.0,   "end": 10.0,  "text": "Hey, get out of here, it's not your car."},
            {"start": 400.0, "end": 405.0, "text": "Unrelated conversation."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 6.0, (
            f"Expected valid match at 6.0s, got {anchored[0].movie_start}s"
        )

    def test_20_test_d_trivial_short_ref_does_not_hijack(self):
        """
        TEST D: Trivial short dialogue reference.
        Ref: "You"
        Cue: "You." (at 94.41s)
        Expected: Must NOT hijack the scene from safe movie_start.
        """
        blocks = [
            SceneBlock(
                movie_start=20.0,
                movie_end=35.0,
                narration_text="The person stands quietly looking at the scenery.",
                dialogue_ref="You",
                word_count=8
            )
        ]
        dialogue_timeline = [
            {"start": 94.41, "end": 96.0, "text": "You."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        # "You" must be rejected as an explicit quote hijack
        assert anchored[0].movie_start < 50.0, (
            f"Trivial 1-word ref 'You' must not hijack; got {anchored[0].movie_start}s"
        )

    def test_21_test_e_one_word_distinctive_ref(self):
        """
        TEST E: One-word legitimate distinctive reference.
        Ref: "Congratulations"
        Cue: "Congratulations to everyone." (at 700.0s)
        Expected: Valid match (anchors to 700.0s).
        """
        blocks = [
            SceneBlock(
                movie_start=50.0,
                movie_end=65.0,
                narration_text="The celebration concludes.",
                dialogue_ref="Congratulations",
                word_count=3
            )
        ]
        dialogue_timeline = [
            {"start": 10.0,  "end": 15.0,  "text": "Starting the event."},
            {"start": 700.0, "end": 705.0, "text": "Congratulations to everyone here."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 700.0, (
            f"Expected distinctive 1-word match at 700.0s, got {anchored[0].movie_start}s"
        )

    def test_22_test_f_real_phase6d_scene05_reproduction(self):
        """
        TEST F: Real Phase 6D Scene 05 reproduction.
        Scene 05 narration: 'The distressed woman worries about how she will ever afford to pay for the expensive vehicle damages.'
        dialogue_ref: 'I don't have this kind of money.'
        Timeline contains:
          - Cue at 18.0s: 'So you're not sure. Okay, you're gonna pay for it. Give me the money for the car wash.'
          - False office cue at 436.21s: 'I don't have this kind of experience.'
        Expected: False office cue at 436.21s is REJECTED.
        Scene 05 anchors near the street confrontation (< 200s), NOT at 436.21s!
        """
        blocks = [
            SceneBlock(
                movie_start=140.0,
                movie_end=152.0,
                narration_text="The distressed woman worries about how she will ever afford to pay for the expensive vehicle damages.",
                dialogue_ref="I don't have this kind of money.",
                word_count=15
            )
        ]
        dialogue_timeline = [
            {"start": 18.0,   "end": 23.0,   "text": "So you're not sure. Okay, you're gonna pay for it. Give me the money for the car wash."},
            {"start": 436.21, "end": 438.21, "text": "I don't have this kind of experience."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start < 200.0, (
            f"Scene 05 must not match false office cue at 436.21s; got {anchored[0].movie_start}s"
        )

    # =========================================================================
    # PHASE 6E.2 — ADVERSARIAL PHRASE PATTERN SUITE
    # =========================================================================

    def test_23_adversarial_same_prefix_different_final_noun(self):
        """
        Pattern 1: Same prefix, different final noun.
        Ref: 'We need to purchase a new car'
        Cue: 'We need to purchase a new house'
        Expected: Rejected from strong reference.
        """
        blocks = [
            SceneBlock(movie_start=50.0, movie_end=65.0, narration_text="Shopping trip.", dialogue_ref="We need to purchase a new car", word_count=2)
        ]
        dialogue_timeline = [
            {"start": 600.0, "end": 605.0, "text": "We need to purchase a new house today."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert anchored[0].movie_start < 100.0

    def test_24_adversarial_same_subject_different_action(self):
        """
        Pattern 2: Same subject, different action.
        Ref: 'The suspect confessed to the detective'
        Cue: 'The suspect escaped from the detective'
        Expected: Rejected from strong reference.
        """
        blocks = [
            SceneBlock(movie_start=50.0, movie_end=65.0, narration_text="Courtroom drama.", dialogue_ref="The suspect confessed to the detective", word_count=2)
        ]
        dialogue_timeline = [
            {"start": 800.0, "end": 805.0, "text": "The suspect escaped from the detective last night."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert anchored[0].movie_start < 100.0

    def test_25_adversarial_same_generic_words_different_event(self):
        """
        Pattern 3: Same five generic words, different event.
        Ref: 'I was going to tell you about the robbery'
        Cue: 'I was going to tell you about the wedding'
        Expected: Rejected.
        """
        blocks = [
            SceneBlock(movie_start=50.0, movie_end=65.0, narration_text="Crime report.", dialogue_ref="I was going to tell you about the robbery", word_count=2)
        ]
        dialogue_timeline = [
            {"start": 750.0, "end": 755.0, "text": "I was going to tell you about the wedding."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert anchored[0].movie_start < 100.0

    def test_26_adversarial_identical_three_common_words_unrelated(self):
        """
        Pattern 4: Identical three common words plus unrelated context.
        Ref: 'there is no time to lose'
        Cue: 'there is no reason to believe'
        Expected: Rejected.
        """
        blocks = [
            SceneBlock(movie_start=50.0, movie_end=65.0, narration_text="Urgent mission.", dialogue_ref="there is no time to lose", word_count=2)
        ]
        dialogue_timeline = [
            {"start": 900.0, "end": 905.0, "text": "there is no reason to believe this story."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert anchored[0].movie_start < 100.0

    def test_27_adversarial_one_distinctive_noun_match(self):
        """
        Pattern 5: One distinctive noun match in a multi-noun phrase.
        Ref: 'Where is the diamond necklace?'
        Cue: 'The necklace was inexpensive.'
        Expected: 'diamond' missing -> rejected from strong ref override.
        """
        blocks = [
            SceneBlock(movie_start=50.0, movie_end=65.0, narration_text="Jewelry theft.", dialogue_ref="Where is the diamond necklace?", word_count=2)
        ]
        dialogue_timeline = [
            {"start": 850.0, "end": 855.0, "text": "The necklace was inexpensive and fake."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert anchored[0].movie_start < 100.0

    def test_28_adversarial_two_distinctive_nouns_match(self):
        """
        Pattern 6: Two distinctive nouns match in phrase.
        Ref: 'The forensic specialist analyzed the poison'
        Cue: 'The forensic specialist verified the poison was lethal'
        Expected: Valid match (anchors to cue).
        """
        blocks = [
            SceneBlock(movie_start=50.0, movie_end=65.0, narration_text="Autopsy report.", dialogue_ref="The forensic specialist analyzed the poison", word_count=2)
        ]
        dialogue_timeline = [
            {"start": 620.0, "end": 625.0, "text": "The forensic specialist verified the poison was lethal."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert anchored[0].movie_start == 620.0

    def test_29_adversarial_exact_phrase_punctuation_diff(self):
        """
        Pattern 7: Exact phrase with punctuation difference.
        Ref: 'Halt! Who goes there?'
        Cue: 'Halt, who goes there.'
        Expected: Strong match (anchors to cue).
        """
        blocks = [
            SceneBlock(movie_start=50.0, movie_end=65.0, narration_text="Guard challenge.", dialogue_ref="Halt! Who goes there?", word_count=2)
        ]
        dialogue_timeline = [
            {"start": 300.0, "end": 305.0, "text": "Halt, who goes there."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert anchored[0].movie_start == 300.0

    def test_30_adversarial_exact_phrase_minor_filler(self):
        """
        Pattern 8: Exact phrase with minor filler words.
        Ref: 'We have to leave right now'
        Cue: 'Okay we have to leave right now please'
        Expected: Strong match (anchors to cue).
        """
        blocks = [
            SceneBlock(movie_start=50.0, movie_end=65.0, narration_text="Emergency exit.", dialogue_ref="We have to leave right now", word_count=2)
        ]
        dialogue_timeline = [
            {"start": 450.0, "end": 455.0, "text": "Okay we have to leave right now please."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert anchored[0].movie_start == 450.0

    def test_31_adversarial_repeated_phrase_chronology(self):
        """
        Pattern 9: Repeated phrase anchors in chronological order without inversion.
        """
        blocks = [
            SceneBlock(movie_start=50.0,  movie_end=65.0,  narration_text="First battle.", dialogue_ref="Never surrender the fortress", word_count=2),
            SceneBlock(movie_start=700.0, movie_end=715.0, narration_text="Last stand.",    dialogue_ref="Never surrender the fortress", word_count=2),
        ]
        dialogue_timeline = [
            {"start": 80.0,  "end": 85.0,  "text": "Never surrender the fortress!"},
            {"start": 750.0, "end": 755.0, "text": "Never surrender the fortress once again!"},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert anchored[0].movie_start == 80.0
        assert anchored[1].movie_start == 750.0
        assert anchored[0].movie_start <= anchored[1].movie_start

    def test_32_adversarial_multilingual_dialogue_ref(self):
        """
        Pattern 11: Multilingual Urdu dialogue_ref grounding preserved.
        """
        blocks = [
            SceneBlock(
                movie_start=20.0,
                movie_end=35.0,
                narration_text="داؤد نے چیخ کر کہا",
                dialogue_ref="بکواس بند کرو اور دفع ہو جاؤ",
                word_count=5
            )
        ]
        dialogue_timeline = [
            {"start": 10.0,  "end": 15.0,  "text": "تقریب میں باتیں ہو رہی ہیں"},
            {"start": 145.0, "end": 152.0, "text": "داؤد: بکواس بند کرو اور دفع ہو جاؤ"},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 145.0


