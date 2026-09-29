"""
T-FIX: 3-Act Proportional Fallback Regression Tests
Ensures that a plain-text script with NO [SCENE: MM:SS] tags produces MULTIPLE
SceneBlocks spread across the movie timeline — never a single (0.0, 60.0) block
that causes the entire video to loop one clip.
"""
import pytest
from app.services.script_engine import ScriptEngine, SceneBlock

PLAIN_SCRIPT = """The story begins in a quiet town. Everything seemed normal at first.
But beneath the surface, dark secrets were hiding. The detective arrived late one night.
She had seen cases like this before. The clues were scattered everywhere.
Act two unfolds with rising tension. The suspect was nowhere to be found.
Every door she knocked on was slammed shut. The clock was ticking faster.
A final confrontation loomed on the horizon. Nobody expected what happened next.
The truth was revealed in a shocking twist. Justice was finally served."""


class TestThreeActProportionalFallback:
    """
    Regression guard: a plain-text script with NO [SCENE: MM:SS] tags must
    produce MULTIPLE SceneBlocks spread across the movie timeline, not a
    single (0.0, 60.0) block that loops one clip for the whole video.
    """

    def test_plain_script_produces_multiple_blocks(self):
        """T-FIX core: no more (0.0, 60.0) single-block fallback."""
        blocks = ScriptEngine.parse_storyboard_blocks(PLAIN_SCRIPT)
        assert len(blocks) > 1, (
            f"Expected multiple scene blocks from plain script, got {len(blocks)}. "
            "The single-(0.0,60.0)-block bug has regressed."
        )

    def test_plain_script_blocks_span_full_movie(self):
        """Blocks should reference timestamps spread across a 90-min film (>100s apart)."""
        blocks = ScriptEngine.parse_storyboard_blocks(PLAIN_SCRIPT)
        starts = [b.movie_start for b in blocks]
        span = max(starts) - min(starts)
        assert span > 100.0, (
            f"All blocks are clustered within {span:.1f}s — expected spread across the film."
        )

    def test_plain_script_no_single_block_at_zero(self):
        """The old bug produced exactly 1 block starting at 0.0s and ending at 60.0s."""
        blocks = ScriptEngine.parse_storyboard_blocks(PLAIN_SCRIPT)
        is_old_bug = (
            len(blocks) == 1
            and blocks[0].movie_start == 0.0
            and blocks[0].movie_end == 60.0
        )
        assert not is_old_bug, "Old (0.0, 60.0) single-block fallback bug has regressed!"

    def test_act1_clips_precede_act2_clips(self):
        """Act1 clips must appear earlier in the movie than Act2 and Act3 clips."""
        blocks = ScriptEngine.parse_storyboard_blocks(PLAIN_SCRIPT)
        starts = [b.movie_start for b in blocks]
        n = len(starts)
        if n < 3:
            pytest.skip("Too few blocks to test act ordering")
        act1_max = max(starts[:max(1, n // 5)])
        act2_min = min(starts[max(1, n // 5) : max(1, n * 4 // 5)])
        assert act1_max <= act2_min, (
            f"Act1 clips (max start={act1_max:.1f}s) must precede Act2 clips (min start={act2_min:.1f}s)"
        )

    def test_every_block_has_narration_text(self):
        """Every generated block must have non-empty narration text."""
        blocks = ScriptEngine.parse_storyboard_blocks(PLAIN_SCRIPT)
        for i, b in enumerate(blocks):
            assert b.narration_text and b.narration_text.strip(), (
                f"Block {i} has empty narration_text"
            )

    def test_every_block_has_positive_word_count(self):
        """Every block's word_count must be >= 1."""
        blocks = ScriptEngine.parse_storyboard_blocks(PLAIN_SCRIPT)
        for i, b in enumerate(blocks):
            assert b.word_count >= 1, f"Block {i} has word_count={b.word_count}"

    def test_scene_with_scene_tags_not_affected(self):
        """Scripts WITH proper [SCENE:] tags must still parse correctly (no regression)."""
        tagged_script = (
            "[SCENE: 00:10 - 00:15]\n[VOICEOVER]\nHook: Something shocking happened.\n"
            "[SCENE: 05:00 - 05:05]\n[VOICEOVER]\nThe plot thickens at midpoint.\n"
            "[SCENE: 08:30 - 08:35]\n[VOICEOVER]\nThe ending nobody saw coming.\n"
        )
        blocks = ScriptEngine.parse_storyboard_blocks(tagged_script)
        assert len(blocks) == 3, f"Expected 3 tagged blocks, got {len(blocks)}"
        assert blocks[0].movie_start == 10.0
        assert blocks[1].movie_start == 300.0
        assert blocks[2].movie_start == 510.0
