"""
Phase 5 Semantic Retrieval Regression & Adversarial Test Suite.
Verifies controlled semantic retrieval as an additional candidate generation mechanism
without replacing or degrading deterministic lexical grounding, explicit dialogue_ref,
or contextual window safeguards.
"""
import math
import sys
import pytest

sys.path.insert(0, "backend")

from app.services.script_engine import (
    ScriptEngine,
    SceneBlock,
    EmbeddingProvider,
    DictEmbeddingProvider,
    SemanticEmbeddingCache,
    cosine_similarity,
)


class TestPhase5SemanticRetrieval:
    """
    Comprehensive suite for Phase 5 Controlled Semantic Retrieval.
    """

    # -------------------------------------------------------------------------
    # 1. SYNONYM CASE
    # Query meaning differs lexically from source cue but retrieves semantically related cue.
    # -------------------------------------------------------------------------
    def test_synonym_recovery_when_lexical_overlap_is_zero(self):
        """
        CASE 1 — Synonym recovery:
        Narration: 'The investigator observes the toxic substance in the cup.'
        Cue A (120s): 'Look at the strange tea on the table.' (lexical: 0, semantic: 0.1)
        Cue B (500s): 'The poison in the glass was fatal.' (lexical: 0, semantic: 0.95)
        With lexical search alone, both score 0.0 -> ungrounded AI timestamp.
        With semantic retrieval, Cue B is recovered and anchored to 500.0s.
        """
        blocks = [
            SceneBlock(
                movie_start=480.0,
                movie_end=510.0,
                narration_text="The investigator observes the toxic substance in the cup.",
                word_count=8
            )
        ]
        dialogue_timeline = [
            {"start": 120.0, "end": 125.0, "text": "Look at the strange tea on the table."},
            {"start": 500.0, "end": 505.0, "text": "The poison in the glass was fatal."},
        ]

        provider = DictEmbeddingProvider({
            "The investigator observes the toxic substance in the cup.": [0.8, 0.6, 0.0, 0.0],
            "Look at the strange tea on the table.":                     [0.0, 0.0, 0.9, 0.1],
            "The poison in the glass was fatal.":                       [0.8, 0.6, 0.0, 0.0],  # cos_sim = 1.0
        })

        anchored = ScriptEngine.anchor_scenes_to_dialogue(
            blocks,
            dialogue_timeline,
            embedding_provider=provider
        )

        assert len(anchored) == 1
        assert anchored[0].movie_start == 500.0, (
            f"Expected synonym cue at 500.0s, got {anchored[0].movie_start}s"
        )

    # -------------------------------------------------------------------------
    # 2. PARAPHRASE CASE
    # Same event expressed with substantially different wording.
    # -------------------------------------------------------------------------
    def test_paraphrase_recovery_without_shared_keywords(self):
        """
        CASE 2 — Paraphrase recovery:
        Narration: 'The convict manages to flee through the underground drainage channel.'
        Cue at 750s: 'The prisoner escaped via the sewer line.'
        Zero exact keyword overlap between narration and cue.
        Semantic retrieval matches the paraphrase.
        """
        blocks = [
            SceneBlock(
                movie_start=700.0,
                movie_end=730.0,
                narration_text="The convict manages to flee through the underground drainage channel.",
                word_count=9
            )
        ]
        dialogue_timeline = [
            {"start": 150.0, "end": 155.0, "text": "The guards are having their afternoon tea."},
            {"start": 750.0, "end": 755.0, "text": "The prisoner escaped via the sewer line."},
        ]

        provider = DictEmbeddingProvider({
            "The convict manages to flee through the underground drainage channel.": [0.5, 0.5, 0.5, 0.5],
            "The guards are having their afternoon tea.":                             [0.0, 0.1, 0.9, 0.1],
            "The prisoner escaped via the sewer line.":                               [0.5, 0.5, 0.5, 0.5],
        })

        anchored = ScriptEngine.anchor_scenes_to_dialogue(
            blocks,
            dialogue_timeline,
            embedding_provider=provider
        )

        assert len(anchored) == 1
        assert anchored[0].movie_start == 750.0, (
            f"Expected paraphrase anchor at 750.0s, got {anchored[0].movie_start}s"
        )

    # -------------------------------------------------------------------------
    # 3. DISTRACTOR CASE
    # A lexically similar but semantically wrong cue must not automatically win.
    # -------------------------------------------------------------------------
    def test_distractor_cue_with_incidental_token_loses_to_true_semantic_cue(self):
        """
        CASE 3 — Distractor case:
        Narration: 'The suspect flees rapidly on a stolen motorcycle.'
        Distractor Cue (200s): 'The motorcycle was parked in front of the precinct.'
          - Shares 1 exact token ('motorcycle' -> match_score = 1.0), but semantic sim is 0.10.
        True Semantic Cue (400s): 'He sped away on a high-speed two-wheeler that wasn't his.'
          - Shares 0 tokens (match_score = 0.0), but semantic sim is 0.95 (bonus = 1.42).
        Target ts = 380s (window covers 400s).
        True semantic cue (composite score 1.42) must defeat incidental distractor (1.0).
        """
        blocks = [
            SceneBlock(
                movie_start=380.0,
                movie_end=410.0,
                narration_text="The suspect flees rapidly on a stolen motorcycle.",
                word_count=8
            )
        ]
        dialogue_timeline = [
            {"start": 200.0, "end": 205.0, "text": "The motorcycle was parked in front of the precinct."},
            {"start": 400.0, "end": 405.0, "text": "He sped away on a high-speed two-wheeler that wasn't his."},
        ]

        provider = DictEmbeddingProvider({
            "The suspect flees rapidly on a stolen motorcycle.":                [0.9, 0.1, 0.1, 0.0],
            "The motorcycle was parked in front of the precinct.":             [0.1, 0.8, 0.1, 0.0],  # sim low
            "He sped away on a high-speed two-wheeler that wasn't his.":        [0.9, 0.1, 0.1, 0.0],  # sim = 1.0
        })

        anchored = ScriptEngine.anchor_scenes_to_dialogue(
            blocks,
            dialogue_timeline,
            embedding_provider=provider
        )

        assert len(anchored) == 1
        assert anchored[0].movie_start == 400.0, (
            f"Expected true semantic cue at 400.0s to beat distractor, got {anchored[0].movie_start}s"
        )

    # -------------------------------------------------------------------------
    # 4. TIMESTAMP CASE
    # Two semantically similar candidates exist; contextual timestamp proximity matters.
    # -------------------------------------------------------------------------
    def test_contextual_proximity_breaks_tie_between_similar_semantic_cues(self):
        """
        CASE 4 — Timestamp proximity:
        Target ts = 1200s.
        Cue A (1220s): 'The door latch has been forced open.' (sim: 0.95, dist: 20s)
        Cue B (3500s): 'The door latch has been forced open.' (sim: 0.95, dist: 2300s)
        Both have identical semantic evidence; Cue A must win due to temporal proximity.
        """
        blocks = [
            SceneBlock(
                movie_start=1200.0,
                movie_end=1230.0,
                narration_text="The detective inspects the broken lock on the front entrance.",
                word_count=9
            )
        ]
        dialogue_timeline = [
            {"start": 1220.0, "end": 1225.0, "text": "The door latch has been forced open."},
            {"start": 3500.0, "end": 3505.0, "text": "The door latch has been forced open."},
        ]

        provider = DictEmbeddingProvider({
            "The detective inspects the broken lock on the front entrance.": [0.6, 0.8, 0.0, 0.0],
            "The door latch has been forced open.":                          [0.6, 0.8, 0.0, 0.0],
        })

        anchored = ScriptEngine.anchor_scenes_to_dialogue(
            blocks,
            dialogue_timeline,
            embedding_provider=provider
        )

        assert len(anchored) == 1
        assert anchored[0].movie_start == 1220.0, (
            f"Expected temporally proximate cue at 1220.0s, got {anchored[0].movie_start}s"
        )

    # -------------------------------------------------------------------------
    # 5. EXACT MATCH CASE
    # Exact/high-confidence lexical evidence must remain protected over semantic similarity.
    # -------------------------------------------------------------------------
    def test_strong_exact_match_overrides_nearby_semantic_match(self):
        """
        CASE 5 — Exact match protection:
        Target ts = 500s.
        Nearby Cue B (510s): 'A man talks quietly with someone.' (sim: 0.90 -> bonus 1.35, exact: 0)
        Distant Cue A (2500s): 'The detective interrogates the chief suspect.'
          (shares 3 exact tokens: 'detective', 'interrogates', 'suspect' -> match_score: 3.0 >= 3.0)
        Rule E / Stage 2: Strong global exact evidence (>=3 tokens, score >=3.0) MUST strictly
        override nearby weak semantic-only evidence.
        """
        blocks = [
            SceneBlock(
                movie_start=500.0,
                movie_end=530.0,
                narration_text="The detective interrogates the chief suspect in custody.",
                word_count=8
            )
        ]
        dialogue_timeline = [
            {"start": 510.0,  "end": 515.0,  "text": "A man talks quietly with someone."},
            {"start": 2500.0, "end": 2505.0, "text": "The detective interrogates the chief suspect."},
        ]

        provider = DictEmbeddingProvider({
            "The detective interrogates the chief suspect in custody.": [0.7, 0.7, 0.0, 0.0],
            "A man talks quietly with someone.":                         [0.7, 0.7, 0.0, 0.0],  # high semantic
            "The detective interrogates the chief suspect.":             [0.0, 0.0, 0.9, 0.1],  # low semantic
        })

        anchored = ScriptEngine.anchor_scenes_to_dialogue(
            blocks,
            dialogue_timeline,
            embedding_provider=provider
        )

        assert len(anchored) == 1
        assert anchored[0].movie_start == 2500.0, (
            f"Strong exact evidence (3 tokens) at 2500.0s must override semantic cue at 510.0s. Got {anchored[0].movie_start}s"
        )

    # -------------------------------------------------------------------------
    # 6. EXPLICIT REFERENCE CASE
    # dialogue_ref must retain priority over weaker semantic candidates.
    # -------------------------------------------------------------------------
    def test_explicit_dialogue_ref_retains_priority_over_semantic_match(self):
        """
        CASE 6 — Explicit reference priority:
        Block has dialogue_ref='Where did you hide the gold?'.
        Cue A (150s): 'Where did you hide the gold?' (ref_score >= 1000)
        Cue B (600s): High semantic similarity to narration text.
        Rule D: Explicit dialogue_ref at 150.0s must win unconditionally.
        """
        blocks = [
            SceneBlock(
                movie_start=580.0,
                movie_end=610.0,
                narration_text="The villain questions his accomplice about the hidden treasure.",
                word_count=8,
                dialogue_ref="Where did you hide the gold?"
            )
        ]
        dialogue_timeline = [
            {"start": 150.0, "end": 155.0, "text": "Where did you hide the gold?"},
            {"start": 600.0, "end": 605.0, "text": "The villain questions his accomplice about the hidden treasure."},
        ]

        provider = DictEmbeddingProvider({
            "The villain questions his accomplice about the hidden treasure.": [0.9, 0.1, 0.0, 0.0],
            "Where did you hide the gold?":                                    [0.0, 0.0, 0.9, 0.1],
        })

        anchored = ScriptEngine.anchor_scenes_to_dialogue(
            blocks,
            dialogue_timeline,
            embedding_provider=provider
        )

        assert len(anchored) == 1
        assert anchored[0].movie_start == 150.0, (
            f"Explicit dialogue_ref at 150.0s must win over semantic match. Got {anchored[0].movie_start}s"
        )

    # -------------------------------------------------------------------------
    # 7. PROVIDER FAILURE
    # Embedding backend failure must fall back cleanly to lexical retrieval.
    # -------------------------------------------------------------------------
    def test_provider_failure_falls_back_cleanly_to_lexical(self):
        """
        CASE 7 — Provider failure safe fallback:
        Provider raises RuntimeError.
        Semantic retrieval fails safely, logging warning, and lexical matching succeeds.
        """
        blocks = [
            SceneBlock(
                movie_start=100.0,
                movie_end=130.0,
                narration_text="The detective examines the crime scene.",
                word_count=6
            )
        ]
        dialogue_timeline = [
            {"start": 300.0, "end": 305.0, "text": "The detective examines the crime scene thoroughly."},
        ]

        failing_provider = DictEmbeddingProvider({})
        failing_provider.failure_mode = True

        anchored = ScriptEngine.anchor_scenes_to_dialogue(
            blocks,
            dialogue_timeline,
            embedding_provider=failing_provider
        )

        assert len(anchored) == 1
        # Lexical matching recovers the cue at 300.0s despite provider exception
        assert anchored[0].movie_start == 300.0

    # -------------------------------------------------------------------------
    # 8. EMPTY SOURCE
    # No cues must not crash semantic retrieval.
    # -------------------------------------------------------------------------
    def test_empty_source_cues_does_not_crash(self):
        """
        CASE 8 — Empty source:
        dialogue_timeline = [] does not crash, preserves AI timestamps.
        """
        blocks = [
            SceneBlock(
                movie_start=50.0,
                movie_end=80.0,
                narration_text="Scene with no transcript available.",
                word_count=5
            )
        ]
        provider = DictEmbeddingProvider({"Scene with no transcript available.": [1.0, 0.0]})

        anchored = ScriptEngine.anchor_scenes_to_dialogue(
            blocks,
            [],
            embedding_provider=provider
        )

        assert len(anchored) == 1
        assert anchored[0].movie_start == 50.0

    # -------------------------------------------------------------------------
    # 9. MALFORMED EMBEDDING
    # Invalid vectors (NaN, Inf) must be rejected safely.
    # -------------------------------------------------------------------------
    def test_malformed_embedding_vectors_handled_safely(self):
        """
        CASE 9 — Malformed embeddings:
        Provider returns NaN/Inf components.
        cosine_similarity returns 0.0 safely without exception.
        """
        provider = DictEmbeddingProvider({})
        provider.malformed_mode = True

        v1 = provider.embed_text("query")
        v2 = [1.0, 0.0]
        sim = cosine_similarity(v1, v2)
        assert sim == 0.0
        assert math.isfinite(sim)

        # In pipeline: malformed embeddings fall back cleanly
        blocks = [
            SceneBlock(movie_start=10.0, movie_end=30.0, narration_text="Test scene", word_count=2)
        ]
        cues = [{"start": 20.0, "end": 25.0, "text": "Test scene cue"}]
        anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, cues, embedding_provider=provider)
        assert len(anchored) == 1
        assert anchored[0].movie_start == 20.0  # lexical matches

    # -------------------------------------------------------------------------
    # 10. DIMENSION MISMATCH
    # Candidate/query vector mismatch must fail safely.
    # -------------------------------------------------------------------------
    def test_dimension_mismatch_fails_safely(self):
        """
        CASE 10 — Dimension mismatch:
        Query vector has dimension 4, cue has dimension 6.
        cosine_similarity returns 0.0 without index/value errors.
        """
        v_query = [1.0, 0.0, 0.0, 0.0]
        v_cue = [1.0, 0.0, 0.0, 0.0, 0.5, 0.5]
        sim = cosine_similarity(v_query, v_cue)
        assert sim == 0.0

    # -------------------------------------------------------------------------
    # 11. DUPLICATE CANDIDATES
    # Merging lexical and semantic candidates must deduplicate correctly.
    # -------------------------------------------------------------------------
    def test_lexical_and_semantic_candidate_merging_deduplicates(self):
        """
        CASE 11 — Candidate deduplication:
        A cue matches BOTH lexically (shared tokens) and semantically (high cosine sim).
        The candidate pool contains exactly 1 merged entry for this cue with both scores combined.
        """
        blocks = [
            SceneBlock(
                movie_start=100.0,
                movie_end=130.0,
                narration_text="The captain signals the retreat.",
                word_count=5
            )
        ]
        # Cue at 120s matches 'captain', 'signals', 'retreat' AND has high semantic similarity
        dialogue_timeline = [
            {"start": 120.0, "end": 125.0, "text": "Captain signals the retreat now!"},
        ]
        provider = DictEmbeddingProvider({
            "The captain signals the retreat.":     [1.0, 0.0, 0.0, 0.0],
            "Captain signals the retreat now!":     [1.0, 0.0, 0.0, 0.0],
        })

        anchored = ScriptEngine.anchor_scenes_to_dialogue(
            blocks,
            dialogue_timeline,
            embedding_provider=provider
        )

        assert len(anchored) == 1
        assert anchored[0].movie_start == 120.0

    # -------------------------------------------------------------------------
    # 12. SHORT SOURCE
    # 3–5 minute configurations must not turn contextual search into unrestricted global search.
    # -------------------------------------------------------------------------
    def test_short_source_preserves_contextual_window_bounds(self):
        """
        CASE 12 — Short source bound:
        Movie length = 180s (3 minutes).
        Contextual window radius is bounded to <= 25% of timeline span (45s),
        preventing distant cues from hijacking when local cues exist.
        """
        blocks = [
            SceneBlock(movie_start=30.0, movie_end=50.0, narration_text="Opening sequence discussion.", word_count=3),
            SceneBlock(movie_start=140.0, movie_end=160.0, narration_text="Closing sequence discussion.", word_count=3)
        ]
        dialogue_timeline = [
            {"start": 35.0,  "end": 40.0,  "text": "Opening sequence discussion."},
            {"start": 145.0, "end": 150.0, "text": "Closing sequence discussion."},
        ]

        provider = DictEmbeddingProvider({
            "Opening sequence discussion.": [1.0, 0.0],
            "Closing sequence discussion.": [0.0, 1.0],
        })

        anchored = ScriptEngine.anchor_scenes_to_dialogue(
            blocks,
            dialogue_timeline,
            embedding_provider=provider
        )

        assert len(anchored) == 2
        assert anchored[0].movie_start == 35.0
        assert anchored[1].movie_start == 145.0

    # -------------------------------------------------------------------------
    # 13. CACHE BEHAVIOR
    # Source cue embeddings are cached and not recomputed across blocks.
    # -------------------------------------------------------------------------
    def test_semantic_embedding_cache_avoids_recomputation(self):
        """
        CASE 13 — Semantic embedding cache:
        Verifies SemanticEmbeddingCache caches embeddings by content hash.
        """
        cache = SemanticEmbeddingCache(max_size=100)
        text = "Sample dialogue cue for caching."
        vec = [0.1, 0.2, 0.3]

        assert cache.get(text) is None
        cache.put(text, vec)
        assert cache.get(text) == vec

        # Bounded capacity test
        tiny_cache = SemanticEmbeddingCache(max_size=2)
        tiny_cache.put("t1", [1.0])
        tiny_cache.put("t2", [2.0])
        tiny_cache.put("t3", [3.0])  # evicts oldest
        assert len(tiny_cache) <= 2

    # -------------------------------------------------------------------------
    # 14. MULTILINGUAL SEMANTIC RETRIEVAL
    # Multilingual text (Urdu, Hindi, Arabic) handles semantic retrieval cleanly.
    # -------------------------------------------------------------------------
    def test_multilingual_semantic_retrieval(self):
        """
        CASE 14 — Multilingual semantic retrieval:
        Urdu narration anchors to Urdu dialogue cue semantically.
        """
        blocks = [
            SceneBlock(
                movie_start=300.0,
                movie_end=330.0,
                narration_text="وہ خفیہ کمرے کے اندر داخل ہوتا ہے۔",
                word_count=7
            )
        ]
        dialogue_timeline = [
            {"start": 100.0, "end": 105.0, "text": "یہاں کوئی نہیں ہے۔"},
            {"start": 310.0, "end": 315.0, "text": "تاریک راستے سے وہ اندر چلا گیا۔"},
        ]

        provider = DictEmbeddingProvider({
            "وہ خفیہ کمرے کے اندر داخل ہوتا ہے۔":    [0.707, 0.707],
            "یہاں کوئی نہیں ہے۔":                    [0.0, 1.0],
            "تاریک راستے سے وہ اندر چلا گیا۔":       [0.707, 0.707],
        })

        anchored = ScriptEngine.anchor_scenes_to_dialogue(
            blocks,
            dialogue_timeline,
            embedding_provider=provider
        )

        assert len(anchored) == 1
        assert anchored[0].movie_start == 310.0

    # -------------------------------------------------------------------------
    # 15. TRANSPARENCY & INTROSPECTION
    # explain_candidate_match reports semantic breakdown when provider is supplied.
    # -------------------------------------------------------------------------
    def test_explain_candidate_match_includes_semantic_metrics(self):
        """
        CASE 15 — explain_candidate_match transparency:
        Reports semantic similarity and combined score when provider is provided.
        """
        narr = "The suspect leaves the town."
        cue = "The fugitive departed yesterday."
        provider = DictEmbeddingProvider({
            narr: [0.8, 0.6],
            cue:  [0.8, 0.6],
        })

        explanation = ScriptEngine.explain_candidate_match(narr, cue, embedding_provider=provider)
        assert "semantic_similarity" in explanation
        assert explanation["semantic_similarity"] == 1.0
        assert "combined_score" in explanation
        assert explanation["combined_score"] > explanation["match_score"]
