import pytest
from unittest.mock import patch, MagicMock
from app.services.script_engine import ScriptEngine


def test_strip_code_and_developer_artifacts():
    # Exact scenario from user's screenshot where 9Router leaked a python test harness
    leaked_script = """[SCENE: 01:20 - 02:45]
[VOICEOVER]
اور گرمی کی شدت سے تڑپ تڑپ کر مر جائیں گے۔ فرینک کی آنکھوں میں اب حتمی فیصلہ دکھائی دے رہا تھا—
اپنے تمام اصول توڑ کر، 400 انسانی زندگیوں کو بچانے کے لیے آخری جنگ لڑنے کا وقت آ چکا تھا۔

```python
# ponytail: test script word count directly without frameworks
def test_word_count(text: str) -> bool:
    count = len(text.split())
    assert count >= 2128, f"Word count low: {count}"
    return True
```
-> skipped: full testing harness, add when running automated CI pipeline.
"""
    cleaned = ScriptEngine.strip_code_and_developer_artifacts(leaked_script)

    assert "def test_word_count" not in cleaned
    assert "assert count" not in cleaned
    assert "```python" not in cleaned
    assert "-> skipped" not in cleaned
    assert "فرینک کی آنکھوں میں اب حتمی فیصلہ" in cleaned
    assert "[SCENE: 01:20 - 02:45]" in cleaned
    assert "[VOICEOVER]" in cleaned


def test_strip_thinking_tags():
    raw_with_think = """<think>
The user wants an Urdu movie explanation for 10 minutes.
Let's make sure the story reaches 2000 words.
</think>
[SCENE: 00:00 - 00:30]
[VOICEOVER]
یہ کہانی شروع ہوتی ہے ایک پراسرار جزیرے پر۔
"""
    cleaned = ScriptEngine.strip_code_and_developer_artifacts(raw_with_think)
    assert "<think>" not in cleaned
    assert "</think>" not in cleaned
    assert "The user wants an Urdu movie explanation" not in cleaned
    assert "یہ کہانی شروع ہوتی ہے" in cleaned


def test_build_prompt_includes_master_prompt_principles():
    prompt = ScriptEngine.build_prompt_for_genre(
        genre="movie_recap",
        title="Cold Skin",
        description="A young man arrives at a deserted island.",
        subs_text="",
        target_lang="ur",
        duration_mins=5
    )

    # Negative constraint against code blocks
    assert "Do NOT include code blocks" in prompt or "no code" in prompt.lower()
    # Conversational tone from master prompt
    assert "conversational" in prompt.lower() or "friend" in prompt.lower()
    # Conclusion / Short Review
    assert "conclusion" in prompt.lower() or "review" in prompt.lower() or "takeaway" in prompt.lower()
