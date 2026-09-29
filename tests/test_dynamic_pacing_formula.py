import pytest
from app.services.script_engine import ScriptEngine

def test_calculate_dynamic_pacing_short_video():
    """Short videos (< 900s / 15m) should yield 3 mins explainer and 5 scenes."""
    pacing = ScriptEngine.calculate_dynamic_pacing(600.0)
    assert pacing["category"] == "short"
    assert pacing["target_duration_mins"] == 3
    assert pacing["target_scenes"] == 5
    assert pacing["source_duration_sec"] == 600.0
    assert "SHORT: 3 mins explainer across ~5 scenes" in pacing["rule_description"]

def test_calculate_dynamic_pacing_boundary_short_to_medium():
    """Boundary conditions at 900s."""
    pacing_899 = ScriptEngine.calculate_dynamic_pacing(899.9)
    assert pacing_899["category"] == "short"
    assert pacing_899["target_duration_mins"] == 3
    assert pacing_899["target_scenes"] == 5

    pacing_900 = ScriptEngine.calculate_dynamic_pacing(900.0)
    assert pacing_900["category"] == "medium"
    assert pacing_900["target_duration_mins"] == 5
    assert pacing_900["target_scenes"] == 7

def test_calculate_dynamic_pacing_medium_drama():
    """Medium videos / dramas (15 to 45 mins) should yield 5 mins explainer and 7 scenes."""
    pacing = ScriptEngine.calculate_dynamic_pacing(1800.0)  # 30 mins
    assert pacing["category"] == "medium"
    assert pacing["target_duration_mins"] == 5
    assert pacing["target_scenes"] == 7
    assert pacing["source_duration_sec"] == 1800.0
    assert "MEDIUM: 5 mins explainer across ~7 scenes" in pacing["rule_description"]

def test_calculate_dynamic_pacing_boundary_medium_to_feature():
    """Boundary conditions at 2700s."""
    pacing_2700 = ScriptEngine.calculate_dynamic_pacing(2700.0)
    assert pacing_2700["category"] == "medium"
    assert pacing_2700["target_duration_mins"] == 5

    pacing_2701 = ScriptEngine.calculate_dynamic_pacing(2701.0)
    assert pacing_2701["category"] == "feature_film"
    assert pacing_2701["target_duration_mins"] == 8
    assert pacing_2701["target_scenes"] == 11

def test_calculate_dynamic_pacing_full_movie():
    """Full movie (1-3+ hours) should yield 8 mins explainer and 11 scenes."""
    pacing = ScriptEngine.calculate_dynamic_pacing(7200.0)  # 2 hours
    assert pacing["category"] == "feature_film"
    assert pacing["target_duration_mins"] == 8
    assert pacing["target_scenes"] == 11
    assert pacing["source_duration_sec"] == 7200.0
    assert "FEATURE_FILM: 8 mins explainer across ~11 scenes" in pacing["rule_description"]

def test_calculate_dynamic_pacing_fallback_on_zero_or_none():
    """Zero, negative, or None duration should fallback to 3600.0s (feature_film)."""
    pacing_zero = ScriptEngine.calculate_dynamic_pacing(0)
    assert pacing_zero["source_duration_sec"] == 3600.0
    assert pacing_zero["category"] == "feature_film"

    pacing_none = ScriptEngine.calculate_dynamic_pacing(None)
    assert pacing_none["source_duration_sec"] == 3600.0
    assert pacing_none["category"] == "feature_film"

    pacing_neg = ScriptEngine.calculate_dynamic_pacing(-50.0)
    assert pacing_neg["source_duration_sec"] == 3600.0
    assert pacing_neg["category"] == "feature_film"
