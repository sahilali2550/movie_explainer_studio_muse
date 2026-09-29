import pytest
from app.services.script_engine import ScriptEngine, SceneBlock


def test_anchor_scenes_to_dialogue_matches_urdu_cues():
    """
    Verifies that anchor_scenes_to_dialogue correctly tokenizes non-Latin (Urdu/Hindi)
    text and anchors the scene block to the matching dialogue timeline timestamp.
    """
    blocks = [
        SceneBlock(
            movie_start=5.0,
            movie_end=15.0,
            narration_text="داؤد نے سخت لہجے میں ارباز کو للکارا کہ بکواس بند کرو اور دفع ہو جاؤ",
            word_count=14
        )
    ]

    dialogue_timeline = [
        {"start": 12.0, "end": 18.0, "text": "کچھ مہمان تقریب میں باتیں کر رہے ہیں"},
        {"start": 145.0, "end": 152.0, "text": "داؤد: بکواس بند کرو اور دفع ہو جاؤ"},
        {"start": 300.0, "end": 305.0, "text": "بریدہ اپنی نئی بائیک پر آ گئی"}
    ]

    anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)

    assert len(anchored) == 1
    # Before the fix, the regex [a-zA-Z]{3,} produced 0 tokens on Urdu text,
    # so anchor_scenes_to_dialogue never matched and kept the fallback (5.0).
    # With the Unicode fix, it must match Cue 2 at 145.0s!
    assert anchored[0].movie_start == 145.0
    assert anchored[0].movie_end >= 150.0


def test_anchor_scenes_to_dialogue_matches_mixed_script_chronologically():
    blocks = [
        SceneBlock(movie_start=0.0, movie_end=10.0, narration_text="داؤد کی پارٹی میں شاندار انٹری ہوتی ہے", word_count=8),
        SceneBlock(movie_start=10.0, movie_end=20.0, narration_text="دستور علی خان کمرے میں خاموش اور لاچار پڑا ہے", word_count=9)
    ]

    dialogue_timeline = [
        {"start": 30.0, "end": 35.0, "text": "سب داؤد کی انٹری دیکھ کر دنگ رہ گئے"},
        {"start": 60.0, "end": 65.0, "text": "موسیقی بج رہی ہے"},
        {"start": 180.0, "end": 188.0, "text": "دستور علی خان بستر پر لاچار پڑا ہے"}
    ]

    anchored = ScriptEngine.anchor_scenes_to_dialogue(blocks, dialogue_timeline)
    assert anchored[0].movie_start == 30.0
    assert anchored[1].movie_start == 180.0
