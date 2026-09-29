import pytest
from app.services.script_engine import ScriptEngine


def test_detect_episode_info():
    ep1 = ScriptEngine.detect_episode_info("Nashtar Episode 01 [Eng Sub] Digitally Presented by...")
    assert ep1["is_episodic"] is True
    assert ep1["episode_num"] == 1
    assert ep1["next_episode_num"] == 2

    ep2 = ScriptEngine.detect_episode_info("Khaie Drama Ep 14 Full")
    assert ep2["is_episodic"] is True
    assert ep2["episode_num"] == 14
    assert ep2["next_episode_num"] == 15

    urdu_ep = ScriptEngine.detect_episode_info("ڈرامہ سیریل قسط 5")
    assert urdu_ep["is_episodic"] is True
    assert urdu_ep["episode_num"] == 5
    assert urdu_ep["next_episode_num"] == 6

    non_ep = ScriptEngine.detect_episode_info("Inception Full Movie Explained in Hindi")
    assert non_ep["is_episodic"] is False


def test_build_prompt_for_genre_injects_episodic_hook():
    prompt_ur = ScriptEngine.build_prompt_for_genre(
        genre="movie_recap",
        title="Nashtar Episode 01",
        description="Danish Taimoor new drama",
        subs_text="[01:15] Dawood enters the hall.",
        target_lang="ur"
    )

    # Must contain instructions for Episode 1 recap and directing viewers to Episode 2!
    assert "Episode 2" in prompt_ur or "قسط 2" in prompt_ur or "Episode 02" in prompt_ur
    assert "EPISODIC" in prompt_ur or "CLIFFHANGER" in prompt_ur
