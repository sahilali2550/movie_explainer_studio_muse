"""
Phase 2 Source-Grounding Regression Suite.
Verifies robust candidate retrieval, fuzzy matching, normalization, and ranking hierarchy.
"""
import sys
import pytest

sys.path.insert(0, "backend")

from app.services.script_engine import ScriptEngine, SceneBlock


class TestPhase2SourceGrounding:
    """
    Focused verification suite for Phase 2 Source Grounding and Candidate Retrieval.
    """

    def test_paraphrase_recovery_beats_incidental_early_match(self):
        """
        CASE A — Paraphrase recovery:
        Source cue at 4500.0s: 'The detective discovers that the victim was poisoned.'
        Narration: 'The investigator realizes the victim died from poison.'
        Incidental early cue at 200.0s only shares 'victim' without morphological link to poison.
        With Phase 2 fuzzy matching ('poison' ~ 'poisoned'), the true late-film cue (4500.0s)
        must win over the incidental early match (200.0s).
        """
        blocks = [
            SceneBlock(
                movie_start=4000.0,
                movie_end=4030.0,
                narration_text="The investigator realizes the victim died from poison.",
                word_count=8
            )
        ]
        dialogue_timeline = [
            {"start": 200.0,  "end": 205.0,  "text": "The victim met the investigator yesterday."},
            {"start": 4500.0, "end": 4505.0, "text": "The detective discovers that the victim was poisoned."},
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        assert anchored[0].movie_start == 4500.0, (
            f"Expected late-film paraphrase cue at 4500.0s, got {anchored[0].movie_start}s"
        )

    def test_strong_exact_match_beats_weak_fuzzy_match_despite_proximity(self):
        """
        CASE B — Strong exact match vs weak fuzzy match:
        Candidate A (100.0s): shares 3 exact tokens ('detective', 'confronts', 'killer')
        Candidate B (3950.0s): shares 1 fuzzy match ('investigating' ~ 'investigator')
        SceneBlock movie_start = 4000.0s (closer to B).
        Principle: Strong source evidence must NOT be overridden by mere temporal proximity.
        Candidate A (exact match) MUST win despite Candidate B being closer to 4000.0s.
        """
        blocks = [
            SceneBlock(
                movie_start=4000.0,
                movie_end=4030.0,
                narration_text="The detective confronts the killer while an investigator watches.",
                word_count=9
            )
        ]
        dialogue_timeline = [
            {"start": 100.0,  "end": 105.0,  "text": "The detective confronts the killer."},       # 3 exact matches
            {"start": 3950.0, "end": 3955.0, "text": "Someone was investigating the room."},      # 1 fuzzy match
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        assert anchored[0].movie_start == 100.0, (
            f"Strong exact evidence at 100.0s should beat weak fuzzy match at 3950.0s. Got {anchored[0].movie_start}s"
        )

    def test_fuzzy_match_recovers_candidate_when_exact_overlap_is_insufficient(self):
        """
        Verifies that morphological variations ('murder' ~ 'murderer', 'escape' ~ 'escaping')
        produce positive match evidence even with zero exact token overlap.
        """
        blocks = [
            SceneBlock(
                movie_start=1500.0,
                movie_end=1530.0,
                narration_text="The murderer was escaping through the back window.",
                word_count=8
            )
        ]
        dialogue_timeline = [
            {"start": 500.0,  "end": 505.0,  "text": "Totally unrelated dialogue here."},
            {"start": 1520.0, "end": 1525.0, "text": "Did you see the murder and how he tried to escape?"},
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        assert anchored[0].movie_start == 1520.0, (
            f"Fuzzy matches ('murder'~'murderer', 'escape'~'escaping') should anchor to 1520.0s, got {anchored[0].movie_start}s"
        )

    def test_equal_evidence_uses_temporal_proximity(self):
        """
        CASE C — Equal evidence:
        When two candidates have identical semantic overlap scores,
        the candidate closer to block.movie_start must win (preserving Phase 1 fix).
        """
        blocks = [
            SceneBlock(
                movie_start=4800.0,
                movie_end=4830.0,
                narration_text="The detective showdown unfolds with dramatic intensity.",
                word_count=7
            )
        ]
        dialogue_timeline = [
            {"start": 200.0,  "end": 205.0,  "text": "detective showdown in the morning"},  # 2 exact tokens
            {"start": 4900.0, "end": 4905.0, "text": "detective showdown in the evening"},  # 2 exact tokens
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        assert anchored[0].movie_start == 4900.0, (
            f"Equal evidence must tie-break to 4900.0s (|4900-4800|=100 < |200-4800|=4600). Got {anchored[0].movie_start}s"
        )

    def test_zero_evidence_preserves_ai_timestamp_fallback(self):
        """
        CASE D — Zero evidence:
        When no candidate cue contains meaningful matching evidence,
        the SceneBlock retains its original AI timestamp.
        """
        blocks = [
            SceneBlock(
                movie_start=1234.0,
                movie_end=1264.0,
                narration_text="The spaceship accelerated into deep hyperspace warp.",
                word_count=7
            )
        ]
        dialogue_timeline = [
            {"start": 100.0, "end": 105.0, "text": "Coffee is ready on the table."},
            {"start": 500.0, "end": 505.0, "text": "Did you lock the front door?"},
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        assert anchored[0].movie_start == 1234.0, (
            f"Zero evidence should fallback to AI timestamp 1234.0s, got {anchored[0].movie_start}s"
        )

    def test_generic_stop_words_do_not_create_false_positives(self):
        """
        Cues sharing only generic stop words ('the', 'is', 'was', 'in', 'and')
        must yield score 0 and not hijack anchoring.
        """
        blocks = [
            SceneBlock(
                movie_start=3000.0,
                movie_end=3030.0,
                narration_text="The submarine was in the ocean and it was submerged.",
                word_count=9
            )
        ]
        dialogue_timeline = [
            {"start": 100.0, "end": 105.0, "text": "The cat was in the house and it was sleeping."},  # only stop words shared
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        # Should NOT match the early cue, should retain fallback 3000.0s
        assert anchored[0].movie_start == 3000.0

    def test_normalization_handles_smart_quotes_and_unicode_punctuation(self):
        """
        CASE E — Normalization:
        Smart quotes (“...”), single quotes (‘...’), em-dashes, and irregular spacing
        must normalize cleanly to match standard transcript tokens.
        """
        blocks = [
            SceneBlock(
                movie_start=800.0,
                movie_end=830.0,
                narration_text="“The   suspect,”   shouted the officer, ‘confessed everything!’",
                word_count=7
            )
        ]
        dialogue_timeline = [
            {"start": 820.0, "end": 825.0, "text": "The suspect shouted: I confessed everything!"},
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        assert anchored[0].movie_start == 820.0

    def test_urdu_hindi_compatibility_preserved(self):
        """
        Verifies that non-Latin Urdu and Hindi scripts continue to anchor accurately
        without regression under Phase 2 normalization.
        """
        blocks = [
            SceneBlock(
                movie_start=10.0,
                movie_end=20.0,
                narration_text="داؤد نے سخت لہجے میں ارباز کو للکارا کہ بکواس بند کرو اور دفع ہو جاؤ",
                word_count=14
            )
        ]
        dialogue_timeline = [
            {"start": 12.0,  "end": 18.0,  "text": "کچھ مہمان تقریب میں باتیں کر رہے ہیں"},
            {"start": 145.0, "end": 152.0, "text": "داؤد: بکواس بند کرو اور دفع ہو جاؤ"},
            {"start": 300.0, "end": 305.0, "text": "بریدہ اپنی نئی بائیک پر آ گئی"}
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        assert anchored[0].movie_start == 145.0

    def test_chronological_ordering_strictly_monotonic(self):
        """
        Multiple scene blocks anchored across the timeline must strictly satisfy
        b[i].movie_start <= b[i+1].movie_start.
        """
        blocks = [
            SceneBlock(movie_start=100.0, movie_end=130.0, narration_text="opening hero arrives in town", word_count=5),
            SceneBlock(movie_start=500.0, movie_end=530.0, narration_text="investigation clues discovered", word_count=4),
            SceneBlock(movie_start=900.0, movie_end=930.0, narration_text="final showdown confrontation climax", word_count=4),
        ]
        dialogue_timeline = [
            {"start": 80.0,   "end": 85.0,   "text": "hero arrives here in town today"},
            {"start": 450.0,  "end": 455.0,  "text": "we found these clues during investigation"},
            {"start": 1200.0, "end": 1205.0, "text": "this is the final showdown confrontation"},
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 3
        assert anchored[0].movie_start == 80.0
        assert anchored[1].movie_start == 450.0
        assert anchored[2].movie_start == 1200.0
        assert anchored[0].movie_start <= anchored[1].movie_start <= anchored[2].movie_start

    def test_repeated_ambiguous_cues_select_contextually_closer(self):
        """
        When identical dialogue lines recur in different parts of a film (e.g. repeated catchphrase),
        anchoring must use the scene block's contextual movie_start to choose the correct instance.
        """
        catchphrase = "I will be back for you."
        blocks = [
            SceneBlock(movie_start=4500.0, movie_end=4530.0, narration_text="He whispered: I will be back for you.", word_count=8)
        ]
        dialogue_timeline = [
            {"start": 300.0,  "end": 305.0,  "text": catchphrase},  # act 1 departure
            {"start": 4600.0, "end": 4605.0, "text": catchphrase},  # act 3 return
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        assert anchored[0].movie_start == 4600.0

    def test_no_candidate_wraps_timeline(self):
        """
        Verifies that anchoring near the end of a film never wraps backward to 0.0s.
        """
        blocks = [
            SceneBlock(movie_start=5200.0, movie_end=5230.0, narration_text="The finale resolution ends in peace.", word_count=6)
        ]
        dialogue_timeline = [
            {"start": 5190.0, "end": 5195.0, "text": "The finale resolution is finally achieved."},
        ]

        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

        assert len(anchored) == 1
        assert anchored[0].movie_start >= 5000.0

    def test_exact_plus_fuzzy_beats_unrelated_exact_match(self):
        """
        Matrix Case 2: 1 exact + 1 fuzzy correct candidate vs unrelated exact match.
        Target scene at 4000.0s. Correct candidate at 4050.0s has 'victim' + 'poisoned' (1 exact + 1 fuzzy = 1.70).
        Unrelated candidate at 1500.0s only shares 'victim' (1 exact = 1.00).
        Correct candidate must win.
        """
        blocks = [
            SceneBlock(
                movie_start=4000.0,
                movie_end=4030.0,
                narration_text="The investigator realizes the victim died from poison.",
                word_count=8
            )
        ]
        dialogue_timeline = [
            {"start": 1500.0, "end": 1505.0, "text": "The victim was seen yesterday."},
            {"start": 4050.0, "end": 4055.0, "text": "The victim was poisoned in the garden."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 4050.0

    def test_explicit_dialogue_ref_priority(self):
        """
        Matrix Case 5: Explicit dialogue_ref strictly overrides generic lexical overlap,
        regardless of where it appears on the timeline.
        """
        blocks = [
            SceneBlock(
                movie_start=3000.0,
                movie_end=3030.0,
                narration_text="General conversation about the missing files.",
                dialogue_ref="Look into my eyes and tell the truth",
                word_count=8
            )
        ]
        dialogue_timeline = [
            {"start": 100.0,  "end": 105.0,  "text": "Look into my eyes and tell the truth right now."},
            {"start": 2990.0, "end": 2995.0, "text": "The missing files conversation continues."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 100.0

    def test_multiple_plausible_candidates_ranking(self):
        """
        Matrix Case 8: Multiple plausible candidates ranked deterministically.
        Target at 2000.0s.
        Candidate A at 1950.0s (score 2.70: 2 exact + 1 fuzzy)
        Candidate B at 2050.0s (score 2.00: 2 exact)
        Candidate C at 2100.0s (score 1.00: 1 exact)
        Candidate A must win on higher corroboration.
        """
        blocks = [
            SceneBlock(
                movie_start=2000.0,
                movie_end=2030.0,
                narration_text="The murderer escaping from the locked facility.",
                word_count=7
            )
        ]
        dialogue_timeline = [
            {"start": 1950.0, "end": 1955.0, "text": "The murder suspect was escaping the locked building."},
            {"start": 2050.0, "end": 2055.0, "text": "The locked facility is secure."},
            {"start": 2100.0, "end": 2105.0, "text": "We entered the facility."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 1950.0

    def test_early_film_scene_anchoring(self):
        """
        Matrix Case 10: Early-film scene at 120.0s correctly anchors to opening cue.
        """
        blocks = [
            SceneBlock(
                movie_start=120.0,
                movie_end=150.0,
                narration_text="The captain prepares the ship for departure.",
                word_count=7
            )
        ]
        dialogue_timeline = [
            {"start": 110.0, "end": 115.0, "text": "Captain, the ship is ready for departure."},
            {"start": 3000.0, "end": 3005.0, "text": "The ship returned safely."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 110.0

    def test_middle_film_scene_anchoring(self):
        """
        Matrix Case 11: Middle-film scene at 2500.0s correctly anchors to mid-movie cue.
        """
        blocks = [
            SceneBlock(
                movie_start=2500.0,
                movie_end=2530.0,
                narration_text="A secret meeting takes place in the abandoned warehouse.",
                word_count=8
            )
        ]
        dialogue_timeline = [
            {"start": 200.0,  "end": 205.0,  "text": "The warehouse is empty."},
            {"start": 2520.0, "end": 2525.0, "text": "Secret meeting inside the abandoned warehouse."},
            {"start": 4800.0, "end": 4805.0, "text": "The warehouse was demolished."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 2520.0

    def test_late_film_climax_anchoring(self):
        """
        Matrix Case 9: Climax scene at 4800.0s anchors to late climax cue.
        """
        blocks = [
            SceneBlock(
                movie_start=4800.0,
                movie_end=4830.0,
                narration_text="The explosive finale destroys the fortress completely.",
                word_count=7
            )
        ]
        dialogue_timeline = [
            {"start": 500.0,  "end": 505.0,  "text": "The fortress stands strong."},
            {"start": 4790.0, "end": 4795.0, "text": "The explosive blast destroys the fortress!"},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 4790.0

    def test_morphology_positives_coverage(self):
        """
        Matrix Case 13: Verifies all mandatory morphological positive pairs:
        murder ↔ murderer, escape ↔ escaping, create ↔ creating, make ↔ making,
        investigate ↔ investigating, poison ↔ poisoned, discover ↔ discovering, victim ↔ victims.
        """
        positives = [
            ("The murder mystery began.", "He is a ruthless murderer."),
            ("He planned to escape.", "The prisoners were escaping fast."),
            ("We create new paths.", "They are creating dangerous weapons."),
            ("I make no promises.", "He was making a critical error."),
            ("Detectives investigate crime.", "Officers were investigating all night."),
            ("Died from deadly poison.", "The food was poisoned yesterday."),
            ("Scientists discover the truth.", "We are discovering new artifacts."),
            ("Help the poor victim.", "All the victims received justice."),
        ]
        for narration, cue in positives:
            res = ScriptEngine.explain_candidate_match(narration, cue)
            assert res["fuzzy_count"] >= 1 or res["exact_count"] >= 1, (
                f"Expected morphological match between '{narration}' and '{cue}', got {res}"
            )

    def test_morphology_false_positives_rejected(self):
        """
        Matrix Case 14: Verifies negative false-positive pairs are strictly rejected:
        plan ↔ planet, rain ↔ rainbow, port ↔ portion.
        """
        negatives = [
            ("We formulated a secret plan.", "Journey to an alien planet."),
            ("Heavy rain soaked the street.", "Look at the colorful rainbow."),
            ("The ship docked at the port.", "Eat a small portion of food."),
        ]
        for narration, cue in negatives:
            res = ScriptEngine.explain_candidate_match(narration, cue)
            # Should have zero fuzzy matches
            assert res["fuzzy_count"] == 0, (
                f"False positive detected between '{narration}' and '{cue}': {res['fuzzy_pairs']}"
            )

    def test_unicode_normalization_accents_and_fullwidth(self):
        """
        Matrix Case 16: Unicode NFKC handles full-width numbers, accents, and smart typography.
        """
        blocks = [
            SceneBlock(
                movie_start=600.0,
                movie_end=630.0,
                narration_text="The café résume confirmed the secret rendezvous.",
                word_count=7
            )
        ]
        dialogue_timeline = [
            {"start": 610.0, "end": 615.0, "text": "Meet at the cafe, confirmed rendezvous."},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 610.0

    def test_hindi_devanagari_grounding_preserved(self):
        """
        Matrix Case 18: Hindi Devanagari script tokenization and anchoring.
        """
        blocks = [
            SceneBlock(
                movie_start=300.0,
                movie_end=330.0,
                narration_text="जासूस ने गुप्त कमरे में हत्यारे को रंगे हाथों पकड़ा।",
                word_count=10
            )
        ]
        dialogue_timeline = [
            {"start": 50.0,  "end": 55.0,  "text": "मौसम बहुत सुहावना है।"},
            {"start": 320.0, "end": 325.0, "text": "जासूस ने हत्यारे को पकड़ा।"},
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 320.0

    def test_adversarial_candidate_outside_contextual_region(self):
        """
        Matrix Case 20: Adversarial candidate far outside contextual region with weak incidental
        tokens cannot hijack a contextually closer candidate.
        """
        blocks = [
            SceneBlock(
                movie_start=3500.0,
                movie_end=3530.0,
                narration_text="The commander surveyed the battlefield after the assault.",
                word_count=8
            )
        ]
        dialogue_timeline = [
            {"start": 200.0,  "end": 205.0,  "text": "The commander met the officer."},  # 1 exact far away
            {"start": 3480.0, "end": 3485.0, "text": "The commander surveyed the assault damage."}, # 3 exact in-window
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 3480.0

    def test_fallback_after_contextual_region_widening(self):
        """
        Matrix Case 21: Progressive widening gracefully finds distant candidate or falls back cleanly.
        """
        blocks = [
            SceneBlock(
                movie_start=4000.0,
                movie_end=4030.0,
                narration_text="The ancient prophecy was fulfilled.",
                word_count=5
            )
        ]
        dialogue_timeline = [
            {"start": 100.0, "end": 105.0, "text": "Breakfast is on the table."},
            {"start": 800.0, "end": 805.0, "text": "The prophecy is known to all."}, # moderate distance
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
        assert len(anchored) == 1
        # Widening reaches 800.0s because no cue in primary window matches
        assert anchored[0].movie_start == 800.0

    def test_score_transparency_introspection(self):
        """
        Step 9: Introspection transparency helper test.
        """
        res = ScriptEngine.explain_candidate_match(
            "The investigator realizes the victim died from poison.",
            "The detective discovers that the victim was poisoned."
        )
        assert res["exact_matches"] == ["victim"]
        assert res["exact_count"] == 1
        assert len(res["fuzzy_pairs"]) >= 1
        assert any(pair[0] == "poison" and pair[1] == "poisoned" for pair in res["fuzzy_pairs"])
        assert res["match_score"] == 1.70


class TestPhase21ShortDurationContextWindow:
    """
    Focused verification suite for Phase 2.1 Short-Duration Context Window Correction.
    Verifies that the contextual search radius scales dynamically without full-movie dilation on short videos.
    """

    def test_3_minute_window_behavior(self):
        """1. 3-minute video (180s): W <= 45s, prevents early incidental hijack."""
        block = SceneBlock(
            movie_start=135.0,
            movie_end=165.0,
            narration_text="The investigator realizes the victim died from poison.",
            word_count=8
        )
        cues = [
            {"start": 0.0,   "end": 5.0,   "text": "opening music intro"},
            {"start": 20.0,  "end": 25.0,  "text": "The victim met the investigator yesterday."},
            {"start": 130.0, "end": 135.0, "text": "The detective discovers that the victim was poisoned."},
            {"start": 180.0, "end": 185.0, "text": "closing credits"}
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue([block], cues)
        assert anchored[0].movie_start == 130.0

    def test_5_minute_window_behavior(self):
        """2. 5-minute video (300s): W <= 75s, prevents early incidental hijack."""
        block = SceneBlock(
            movie_start=240.0,
            movie_end=270.0,
            narration_text="The investigator realizes the victim died from poison.",
            word_count=8
        )
        cues = [
            {"start": 0.0,   "end": 5.0,   "text": "intro sequence"},
            {"start": 30.0,  "end": 35.0,  "text": "The victim met the investigator yesterday."},
            {"start": 235.0, "end": 240.0, "text": "The detective discovers that the victim was poisoned."},
            {"start": 300.0, "end": 305.0, "text": "outro sequence"}
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue([block], cues)
        assert anchored[0].movie_start == 235.0

    def test_8_minute_window_behavior(self):
        """3. 8-minute video (480s): W <= 90s, anchors late cue accurately."""
        block = SceneBlock(
            movie_start=380.0,
            movie_end=410.0,
            narration_text="The investigator realizes the victim died from poison.",
            word_count=8
        )
        cues = [
            {"start": 0.0,   "end": 5.0,   "text": "intro"},
            {"start": 40.0,  "end": 45.0,  "text": "The victim met the investigator yesterday."},
            {"start": 375.0, "end": 380.0, "text": "The detective discovers that the victim was poisoned."},
            {"start": 480.0, "end": 485.0, "text": "outro"}
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue([block], cues)
        assert anchored[0].movie_start == 375.0

    def test_12_minute_window_behavior(self):
        """4. 12-minute video (720s): W = 108s, anchors late cue accurately."""
        block = SceneBlock(
            movie_start=580.0,
            movie_end=610.0,
            narration_text="The investigator realizes the victim died from poison.",
            word_count=8
        )
        cues = [
            {"start": 0.0,   "end": 5.0,   "text": "intro"},
            {"start": 50.0,  "end": 55.0,  "text": "The victim met the investigator yesterday."},
            {"start": 575.0, "end": 580.0, "text": "The detective discovers that the victim was poisoned."},
            {"start": 720.0, "end": 725.0, "text": "outro"}
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue([block], cues)
        assert anchored[0].movie_start == 575.0

    def test_30_minute_regression(self):
        """5. 30-minute video (1800s): W = 270s, preserves Phase 2 baseline."""
        block = SceneBlock(
            movie_start=1500.0,
            movie_end=1530.0,
            narration_text="The detective confronts the murderer inside the hideout.",
            word_count=8
        )
        cues = [
            {"start": 100.0,  "end": 105.0,  "text": "The detective met the officer."},
            {"start": 1490.0, "end": 1495.0, "text": "The detective confronts the murderer right now."},
            {"start": 1800.0, "end": 1805.0, "text": "end"}
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue([block], cues)
        assert anchored[0].movie_start == 1490.0

    def test_90_minute_regression(self):
        """6. 90-minute video (5400s): W = 810s, preserves Phase 2 baseline."""
        block = SceneBlock(
            movie_start=4800.0,
            movie_end=4830.0,
            narration_text="The explosive finale destroys the fortress completely.",
            word_count=7
        )
        cues = [
            {"start": 200.0,  "end": 205.0,  "text": "The fortress stands strong."},
            {"start": 4790.0, "end": 4795.0, "text": "The explosive blast destroys the fortress!"},
            {"start": 5400.0, "end": 5405.0, "text": "credits"}
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue([block], cues)
        assert anchored[0].movie_start == 4790.0

    def test_180_minute_regression(self):
        """7. 180-minute video (10800s): W = 1620s, preserves Phase 2 baseline."""
        block = SceneBlock(
            movie_start=9500.0,
            movie_end=9530.0,
            narration_text="The final showdown resolves the ancient conflict.",
            word_count=7
        )
        cues = [
            {"start": 500.0,  "end": 505.0,  "text": "The ancient conflict began."},
            {"start": 9480.0, "end": 9485.0, "text": "The final showdown resolves everything."},
            {"start": 10800.0, "end": 10805.0, "text": "end"}
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue([block], cues)
        assert anchored[0].movie_start == 9480.0

    def test_boundary_inside_outside_primary_window(self):
        """8. On 180s video (W=45s), cue at dist=40s (inside) beats cue at dist=80s (outside)."""
        block = SceneBlock(
            movie_start=100.0,
            movie_end=130.0,
            narration_text="The investigator realizes the victim died from poison.",
            word_count=8
        )
        cues = [
            {"start": 0.0,   "end": 5.0,   "text": "intro"},
            {"start": 20.0,  "end": 25.0,  "text": "The victim met the investigator yesterday."}, # 2 exact (dist=80s > 45s)
            {"start": 140.0, "end": 145.0, "text": "The detective discovers that the victim was poisoned."}, # 1 exact + 1 fuzzy (dist=40s <= 45s)
            {"start": 180.0, "end": 185.0, "text": "outro"}
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue([block], cues)
        assert anchored[0].movie_start == 140.0

    def test_progressive_widening_short_movie(self):
        """9. When no candidate exists in primary window (W=45s), widening safely finds Tier 2 cue."""
        block = SceneBlock(
            movie_start=140.0,
            movie_end=170.0,
            narration_text="The prophecy was fulfilled.",
            word_count=4
        )
        cues = [
            {"start": 0.0,  "end": 5.0,  "text": "breakfast is ready"},
            {"start": 60.0, "end": 65.0, "text": "The ancient prophecy came true."}, # dist=80s (in Tier 2: <= 90s)
            {"start": 180.0, "end": 185.0, "text": "credits"}
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue([block], cues)
        assert anchored[0].movie_start == 60.0

    def test_strong_global_override_on_short_movie(self):
        """10. Rule A preserved on short movies: >= 3 exact tokens outside W beats weak fuzzy inside W."""
        block = SceneBlock(
            movie_start=135.0,
            movie_end=165.0,
            narration_text="The detective confronts the killer while an investigator watches.",
            word_count=9
        )
        cues = [
            {"start": 20.0,  "end": 25.0,  "text": "The detective confronts the killer."}, # 3 exact tokens (dist=115s > 45s)
            {"start": 140.0, "end": 145.0, "text": "Someone was investigating."}, # 1 fuzzy token (dist=5s <= 45s)
            {"start": 180.0, "end": 185.0, "text": "end"}
        ]
        anchored = ScriptEngine.anchor_scenes_to_dialogue([block], cues)
        assert anchored[0].movie_start == 20.0
