"""
TDD: Dialogue-Anchored Scene Sync Tests
Tests for T-01, T-03, T-05, T-06 — Written BEFORE implementation (RED phase).
"""
import pytest
import inspect
from app.services.script_engine import ScriptEngine, SceneBlock


# =========================================================================
# T-01: anchor_scenes_to_dialogue() — Dialogue → Real Movie Timestamp Match
# =========================================================================

class TestDialogueAnchor:

    def _make_blocks(self):
        return [
            SceneBlock(movie_start=60.0,  movie_end=120.0,  narration_text="The hero storms into the building guns blazing shouting get your hands up now", word_count=13),
            SceneBlock(movie_start=180.0, movie_end=240.0,  narration_text="A massive explosion rocks the warehouse as the villain escapes through a back door", word_count=14),
            SceneBlock(movie_start=300.0, movie_end=360.0,  narration_text="In the climax the hero confronts the mastermind on the rooftop with a final showdown", word_count=15),
        ]

    def _make_dialogue_timeline(self):
        return [
            {"start": 1234.5, "end": 1238.0, "text": "Get your hands up now! Nobody move!"},
            {"start": 2456.0, "end": 2460.5, "text": "Run! The warehouse is going to blow!"},
            {"start": 2470.0, "end": 2475.0, "text": "Explosion heard across three blocks"},
            {"start": 4890.0, "end": 4895.0, "text": "This ends now. Face me on the rooftop."},
            {"start": 4900.0, "end": 4905.0, "text": "Final showdown begins at the rooftop helipad"},
        ]

    def test_anchor_method_exists(self):
        assert hasattr(ScriptEngine, "anchor_scenes_to_dialogue"), \
            "ScriptEngine must have anchor_scenes_to_dialogue() method"
        assert callable(ScriptEngine.anchor_scenes_to_dialogue)

    def test_anchor_returns_scene_blocks(self):
        blocks = self._make_blocks()
        timeline = self._make_dialogue_timeline()
        result = ScriptEngine.anchor_scenes_to_dialogue(blocks, timeline)
        assert isinstance(result, list)
        assert len(result) == len(blocks)
        for b in result:
            assert isinstance(b, SceneBlock)

    def test_anchor_replaces_ai_timestamps_with_real_ones(self):
        blocks = self._make_blocks()
        timeline = self._make_dialogue_timeline()
        result = ScriptEngine.anchor_scenes_to_dialogue(blocks, timeline)
        assert result[0].movie_start >= 1200.0, f"Block 0 should anchor near 1234s, got {result[0].movie_start}"
        assert result[0].movie_start <= 1300.0
        assert result[1].movie_start >= 2420.0, f"Block 1 should anchor near 2456s, got {result[1].movie_start}"
        assert result[1].movie_start <= 2520.0
        assert result[2].movie_start >= 4850.0, f"Block 2 should anchor near 4890s, got {result[2].movie_start}"
        assert result[2].movie_start <= 4950.0

    def test_anchor_preserves_chronological_order(self):
        blocks = self._make_blocks()
        timeline = self._make_dialogue_timeline()
        result = ScriptEngine.anchor_scenes_to_dialogue(blocks, timeline)
        for i in range(len(result) - 1):
            assert result[i].movie_start <= result[i+1].movie_start

    def test_anchor_fallback_when_no_timeline(self):
        blocks = self._make_blocks()
        result = ScriptEngine.anchor_scenes_to_dialogue(blocks, [])
        assert len(result) == len(blocks)
        assert result[0].movie_start == blocks[0].movie_start

    def test_anchor_fallback_when_no_blocks(self):
        timeline = self._make_dialogue_timeline()
        result = ScriptEngine.anchor_scenes_to_dialogue([], timeline)
        assert result == []

    def test_anchor_sets_movie_end_after_start(self):
        blocks = self._make_blocks()
        timeline = self._make_dialogue_timeline()
        result = ScriptEngine.anchor_scenes_to_dialogue(blocks, timeline)
        for i, b in enumerate(result):
            assert b.movie_end > b.movie_start, f"Block {i}: movie_end must be > movie_start"

    def test_anchor_minimum_scene_duration(self):
        blocks = self._make_blocks()
        timeline = self._make_dialogue_timeline()
        result = ScriptEngine.anchor_scenes_to_dialogue(blocks, timeline)
        for i, b in enumerate(result):
            assert (b.movie_end - b.movie_start) >= 3.0, f"Block {i} duration {b.movie_end - b.movie_start:.1f}s below 3s"


# =========================================================================
# T-03: parse_storyboard_blocks() Timestamp Validation
# =========================================================================

class TestStoryboardTimestampValidation:

    def test_parse_storyboard_blocks_accepts_dialogue_timeline(self):
        sig = inspect.signature(ScriptEngine.parse_storyboard_blocks)
        assert "dialogue_timeline" in sig.parameters

    def test_parse_storyboard_blocks_clamps_impossible_timestamps(self):
        timeline = [
            {"start": 1850.0, "end": 1855.0, "text": "The opening explosion rocked the building"},
            {"start": 2400.0, "end": 2405.0, "text": "Meanwhile at the police station"},
            {"start": 2900.0, "end": 2905.0, "text": "Final confrontation begins now"},
        ]
        script = (
            "[SCENE: 01:00 - 01:30]\n[VOICEOVER]\nThe opening explosion rocked the building.\n\n"
            "[SCENE: 02:00 - 02:30]\n[VOICEOVER]\nMeanwhile at the police station investigations begin.\n\n"
            "[SCENE: 03:00 - 03:30]\n[VOICEOVER]\nFinal confrontation begins now at the rooftop.\n\n"
        )
        blocks = ScriptEngine.parse_storyboard_blocks(script, dialogue_timeline=timeline)
        assert len(blocks) == 3, f"Expected 3 blocks, got {len(blocks)}"
        assert blocks[0].movie_start >= 1800.0, f"Block 0 should be anchored near 1850s, got {blocks[0].movie_start}"

    def test_parse_storyboard_blocks_no_timeline_backward_compat(self):
        script = (
            "[SCENE: 05:00 - 08:00]\n[VOICEOVER]\nThe story begins with a dramatic confrontation.\n\n"
            "[SCENE: 25:00 - 28:00]\n[VOICEOVER]\nMidpoint twist changes everything.\n\n"
        )
        blocks = ScriptEngine.parse_storyboard_blocks(script)
        assert len(blocks) == 2
        assert blocks[0].movie_start == pytest.approx(300.0, abs=5.0)
        assert blocks[1].movie_start == pytest.approx(1500.0, abs=5.0)


# =========================================================================
# T-06: Genre Auto-Detection Fix
# =========================================================================

class TestGenreAutoDetect:

    def test_action_spy_movie_detected_correctly(self):
        result = ScriptEngine.auto_detect_creative_context(
            title="AGENT ON THE RUN",
            description="Dave Bautista, Chloe Coleman, Ken Jeong. Hollywood Action Spy Thriller Movie.",
            transcript_sample=""
        )
        assert result["genre"] == "movie_recap", f"Action Spy movie should be movie_recap, got {result['genre']}"
        assert result["persona"] in ("hollywood_trailer", "viral_fast"), f"Got {result['persona']}"

    def test_horror_movie_detected_correctly(self):
        result = ScriptEngine.auto_detect_creative_context(
            title="THE HAUNTED MANSION",
            description="A terrifying ghost story of demon possession and haunted house."
        )
        assert result["genre"] == "movie_recap"
        assert result["mood"] in ("suspense", "tense")

    def test_documentary_content_detected_correctly(self):
        result = ScriptEngine.auto_detect_creative_context(
            title="WORLD WAR II THE UNTOLD STORY",
            description="A historical documentary about the ancient empire war history."
        )
        assert result["genre"] == "documentary"

    def test_keyword_agent_in_title_triggers_action(self):
        result = ScriptEngine.auto_detect_creative_context(
            title="AGENT 47 ASSASSINATION TARGET",
            description="",
            transcript_sample=""
        )
        assert result["genre"] == "movie_recap", f"Agent in title should trigger movie_recap, got {result['genre']}"
        assert result["persona"] != "documentary"


# =========================================================================
# T-05: Audio Stereo (inspects FFmpeg command in render_final_explainer)
# =========================================================================

class TestAudioStereo:

    def test_render_final_explainer_uses_stereo_audio(self):
        from app.services import video_engine
        ve_source = inspect.getsource(video_engine)
        has_stereo = ('"-ac", "2"' in ve_source or "'-ac', '2'" in ve_source)
        assert has_stereo, "render_final_explainer FFmpeg command must include '-ac', '2' for stereo audio"
