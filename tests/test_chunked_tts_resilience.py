import os
import pytest
from unittest.mock import patch, MagicMock
from app.services.voice_engine import VoiceEngine
from app.services.script_engine import ScriptEngine


def test_split_text_into_chunks_urdu():
    """Verifies that Urdu text with traditional punctuation (۔) is cleanly chunked without losing words."""
    urdu_sentences = [
        "یہ کہانی ایک نوجوان کی ہے جو رات کے اندھیرے میں سچ تلاش کر رہا تھا۔",
        "پولیس نے جب اس کا تعاقب کیا تو وہ جنگل کی طرف بھاگ گیا۔",
        "وہاں ایک پرانی عمارت تھی جس کے دروازے بند تھے۔",
        "اس نے دیوار پھلانگ کر اندر قدم رکھا تو اسے خون کے نشانات ملے۔",
        "یہ دیکھ کر اس کے ہوش اڑ گئے اور اس نے فوری طور پر پیچھے ہٹنے کا فیصلہ کیا۔"
    ]
    full_text = " ".join(urdu_sentences * 15) # ~1,200 words, ~7,500 chars
    chunks = VoiceEngine.split_text_into_chunks(full_text, max_chars=600)

    assert len(chunks) > 1, "Should split 7500-char text into multiple chunks"
    for c in chunks:
        assert len(c) <= 650, f"Chunk length {len(c)} exceeds safe limit"
        assert len(c.strip()) > 0
    # Ensure no loss of words
    total_words_original = len(full_text.split())
    total_words_chunked = sum(len(c.split()) for c in chunks)
    assert total_words_original == total_words_chunked


def test_split_text_into_chunks_english():
    """Verifies English text splits cleanly at sentence boundaries."""
    sentences = [
        "The detective walked into the dimly lit room.",
        "A cold breeze blew through the shattered window pane.",
        "On the desk lay an envelope sealed with crimson wax.",
        "Inside was a photograph from twenty years ago.",
        "He knew then that his partner had lied to him all along."
    ]
    full_text = " ".join(sentences * 15)
    chunks = VoiceEngine.split_text_into_chunks(full_text, max_chars=500)

    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 550
    assert sum(len(c.split()) for c in chunks) == len(full_text.split())


def test_clamp_script_word_budget():
    """Verifies that ScriptEngine prunes runaway scripts exceeding duration budgets at scene boundaries."""
    # 10 minutes budget should be max ~1900 words
    fake_scene_template = (
        "[00:00 - 01:00] Scene {n}: "
        + "This is a detailed narrative sentence describing characters, conflict, and suspense in the film. " * 8
    ) # ~100 words per scene
    long_script = "\n\n".join(fake_scene_template.format(n=i+1) for i in range(40)) # 40 scenes = ~4000 words
    
    clamped = ScriptEngine.clamp_script_word_budget(long_script, target_duration_mins=10)
    clamped_word_count = len(clamped.split())
    
    assert clamped_word_count <= 1900, f"Clamped script has {clamped_word_count} words, expected <= 1900"
    assert clamped_word_count >= 1400, f"Clamped script has {clamped_word_count} words, expected >= 1400"
    assert "Scene" in clamped
    # Verify it ends cleanly at a scene, not mid-sentence
    assert clamped.strip().endswith(".") or clamped.strip().endswith("۔") or clamped.strip().endswith("!")


@pytest.mark.anyio
async def test_synthesize_speech_chunked_cues(tmp_path):
    """Verifies that long text is chunked and cues have continuous monotonic offsets."""
    text = (
        "First sentence of part one. Second sentence of part one. "
        "Third sentence of part one. Fourth sentence of part one. "
        "Fifth sentence of part two. Sixth sentence of part two. "
        "Seventh sentence of part two. Eighth sentence of part two. "
    ) * 10 # > 1000 chars

    out_file = str(tmp_path / "test_long_speech.mp3")

    class AsyncChunkStream:
        def __init__(self, c_text):
            self.c_text = c_text
        async def stream(self):
            yield {"type": "audio", "data": b"ID3" + b"\x00" * 200}
            yield {
                "type": "SentenceBoundary",
                "offset": 0,
                "duration": 50_000_000, # 5.0s
                "text": "Sentence sample."
            }

    with patch("edge_tts.Communicate", side_effect=lambda t, *a, **kw: AsyncChunkStream(t)):
        with patch.object(VoiceEngine, "get_audio_duration", return_value=5.0):
            ok = await VoiceEngine.synthesize_speech(text, "en-US-ChristopherNeural", out_file)
            assert ok is True
            assert os.path.exists(out_file)
            cues = VoiceEngine.get_speech_cues(out_file)
            assert len(cues) > 1, "Should have multiple chunk cues"
            for i in range(1, len(cues)):
                assert cues[i]["start"] >= cues[i-1]["start"], "Cues must be monotonically increasing"

