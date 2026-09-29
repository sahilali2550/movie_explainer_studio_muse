"""
Phase 3A Narrative Roadmap & Source Density Verification Suite.
Validates dynamic capacity scaling, act-aware distribution, narrative preservation,
adversarial cue selection, and chronological integrity without hardcoded static scene counts.
"""
import sys
import re
import pytest

sys.path.insert(0, "backend")

from app.services.script_engine import ScriptEngine


def make_synthetic_transcript(total_dur_sec: float, num_cues: int, act_weights: tuple = (0.20, 0.25, 0.25, 0.20, 0.10)):
    """
    Creates a synthetic chronological transcript distributed across the 5 universal narrative acts.
    """
    cues = []
    acts = [
        ("Act 1", 0.0, 0.20 * total_dur_sec),
        ("Act 2A", 0.20 * total_dur_sec, 0.45 * total_dur_sec),
        ("Act 2B", 0.45 * total_dur_sec, 0.70 * total_dur_sec),
        ("Act 3", 0.70 * total_dur_sec, 0.90 * total_dur_sec),
        ("Epilogue", 0.90 * total_dur_sec, total_dur_sec),
    ]

    # Distribute cues according to act_weights
    total_w = sum(act_weights)
    for act_idx, (name, a_start, a_end) in enumerate(acts):
        w = act_weights[act_idx]
        act_cues_count = max(1, int(round(num_cues * (w / total_w))))
        span = max(1.0, a_end - a_start)
        step = span / float(act_cues_count)
        for j in range(act_cues_count):
            t = a_start + (j + 0.5) * step
            if t >= 3600.0:
                h = int(t // 3600)
                m = int((t % 3600) // 60)
                s = int(t % 60)
                cues.append(f"[{h:02d}:{m:02d}:{s:02d}] {name} narrative dialogue beat {j} at {int(t)}s.")
            else:
                m = int(t // 60)
                s = int(t % 60)
                cues.append(f"[{m:02d}:{s:02d}] {name} narrative dialogue beat {j} at {int(t)}s.")

    raw_subs = "\n".join(cues)
    return raw_subs, cues


class TestPhase3aDurationScaling:
    """
    Validates dynamic, duration-aware roadmap capacity across diverse explainer lengths (3m to 180m).
    Proves that roadmap size scales with output duration without fixed constant quotas.
    """

    @pytest.mark.parametrize("out_mins", [3, 5, 8, 12, 15, 20, 30, 60, 90, 120, 180])
    def test_duration_matrix_coverage(self, out_mins):
        # Movie of 7200s (120m) with 500 cues
        total_dur = 7200.0
        subs, _ = make_synthetic_transcript(total_dur, 500)
        metrics = ScriptEngine.explain_roadmap_coverage(
            subs_text=subs,
            total_movie_dur=total_dur,
            target_output_dur_mins=out_mins
        )

        retained = metrics["retained_event_count"]
        assert retained > 0
        # Beginning, middle, climax, and ending must all be covered
        assert metrics["beginning_coverage"], f"Missing beginning coverage for {out_mins}m"
        assert metrics["middle_coverage"], f"Missing middle coverage for {out_mins}m"
        assert metrics["climax_coverage"], f"Missing climax coverage for {out_mins}m"
        assert metrics["ending_coverage"], f"Missing ending coverage for {out_mins}m"

        # Timestamp boundaries
        assert metrics["earliest_timestamp"] <= total_dur * 0.10
        assert metrics["latest_timestamp"] >= total_dur * 0.85

    def test_increasing_duration_increases_or_maintains_capacity(self):
        """Invariant 5: Increasing output duration must not reduce source coverage."""
        total_dur = 5400.0
        subs, _ = make_synthetic_transcript(total_dur, 400)
        durations = [3, 5, 8, 12, 15, 20, 30, 60, 90, 120]
        retained_counts = []
        for d in durations:
            m = ScriptEngine.explain_roadmap_coverage(
                subs_text=subs,
                total_movie_dur=total_dur,
                target_output_dur_mins=d
            )
            retained_counts.append(m["retained_event_count"])

        for i in range(len(retained_counts) - 1):
            assert retained_counts[i+1] >= retained_counts[i], (
                f"Capacity decreased from {durations[i]}m ({retained_counts[i]}) to {durations[i+1]}m ({retained_counts[i+1]})"
            )


class TestPhase3aSourceDensity:
    """
    Validates behavior under extreme source density variations (sparse vs dense source).
    """

    def test_sparse_source_never_invents_cues(self):
        """Invariant 6: If source material is sparse, do not invent density."""
        sparse_subs = """
        [01:00] Intro event
        [15:00] Early conflict
        [30:00] Midpoint reveal
        [50:00] Climax confrontation
        [65:00] Final resolution
        """
        metrics = ScriptEngine.explain_roadmap_coverage(
            subs_text=sparse_subs,
            total_movie_dur=4200.0,
            target_output_dur_mins=30  # Requesting large output duration
        )
        assert metrics["source_event_count"] == 5
        assert metrics["retained_event_count"] <= 5
        assert metrics["retained_event_count"] == 5  # Retains all available without hallucination

    def test_dense_source_scales_with_duration(self):
        """Invariant 7: If source material is highly dense, do not collapse to tiny static roadmap."""
        subs, _ = make_synthetic_transcript(7200.0, 1500)
        m_short = ScriptEngine.explain_roadmap_coverage(subs, 7200.0, target_output_dur_mins=3)
        m_long = ScriptEngine.explain_roadmap_coverage(subs, 7200.0, target_output_dur_mins=30)

        assert m_short["retained_event_count"] >= 20
        assert m_long["retained_event_count"] >= 70
        assert m_long["retained_event_count"] > m_short["retained_event_count"] * 2


class TestPhase3aNarrativePreservation:
    """
    Validates act-aware coverage, chronological ordering, and full arc representation.
    """

    def test_middle_act_preservation(self):
        """Invariant 3: Middle narrative region (Act 2A and 2B) is represented proportionally."""
        subs, _ = make_synthetic_transcript(5400.0, 300)
        metrics = ScriptEngine.explain_roadmap_coverage(subs, 5400.0, target_output_dur_mins=10)
        acts = metrics["act_breakdown"]
        middle_count = acts["act2a"] + acts["act2b"]
        assert middle_count >= 15
        assert middle_count >= metrics["retained_event_count"] * 0.40

    def test_climax_and_ending_preservation(self):
        """Invariant 4: Climax (Act 3) and Resolution (Epilogue) are guaranteed representation."""
        subs, _ = make_synthetic_transcript(5400.0, 300)
        metrics = ScriptEngine.explain_roadmap_coverage(subs, 5400.0, target_output_dur_mins=10)
        acts = metrics["act_breakdown"]
        assert acts["act3"] >= 6
        assert acts["epilogue"] >= 2
        assert metrics["latest_timestamp"] >= 5400.0 * 0.90

    def test_chronological_order_strictly_preserved(self):
        """Invariant 1: Roadmap events are strictly non-decreasing in chronological order."""
        subs, _ = make_synthetic_transcript(5400.0, 200)
        roadmap = ScriptEngine.compress_transcript_to_roadmap(subs, 5400.0, target_output_dur_mins=15)
        lines = [l for l in roadmap.splitlines() if l.strip().startswith("[")]
        ts_list = []
        for l in lines:
            m = re.search(r'\[(\d{1,2}):(\d{2})\]', l)
            assert m is not None
            ts_list.append(int(m.group(1)) * 60 + int(m.group(2)))

        assert len(ts_list) > 10
        for i in range(len(ts_list) - 1):
            assert ts_list[i+1] >= ts_list[i], f"Chronology violated: {ts_list[i]}s followed by {ts_list[i+1]}s"

    def test_no_invented_events(self):
        """Verifies that all timestamps and text snippets in roadmap map directly to actual source cues."""
        raw_subs = """
        [02:15] The hero discovers an ancient artifact hidden inside the cave.
        [10:30] A shadowy figure warns him about the impending curse.
        [25:45] The midpoint revelation changes everything they believed.
        [42:10] The ultimate battle commences at the castle gates.
        [58:20] Peace returns to the kingdom as the hero departs.
        """
        roadmap = ScriptEngine.compress_transcript_to_roadmap(raw_subs, 3600.0, target_output_dur_mins=5)
        lines = [l for l in roadmap.splitlines() if l.strip()]
        for l in lines:
            # Must contain one of the original dialogue phrases
            assert any(phrase in l for phrase in ["ancient artifact", "shadowy figure", "midpoint revelation", "ultimate battle", "Peace returns"])


class TestPhase3aAdversarialCases:
    """
    Mandatory adversarial test scenarios from Step 12.
    """

    def test_adversarial_case_a_crucial_middle_event_with_few_words(self):
        """
        Case A: The middle contains a highly important event with relatively few words.
        The algorithm must not lose it merely because rival lines in the same bucket have more words.
        """
        subs = """
        [45:00] Well anyway as I was saying yesterday we really ought to get some groceries and check the weather outside.
        [45:10] The killer is my brother.
        [45:30] I think the supermarket is probably going to be closed early today because of the holiday weekend.
        """
        # 1-bucket target in this interval
        roadmap = ScriptEngine.compress_transcript_to_roadmap(subs, 5400.0, max_points=1)
        assert "killer is my brother" in roadmap, (
            f"Crucial revelation was dropped in favor of verbose filler. Roadmap:\n{roadmap}"
        )

    def test_adversarial_case_b_ending_with_fewer_words(self):
        """
        Case B: Ending contains far fewer words and cues than Act 2.
        Epilogue must still retain meaningful representation and not be starved.
        """
        cues = []
        # Act 1 & 2: 200 verbose banter cues
        for i in range(200):
            t = i * 20.0  # 0 to 4000s
            m = int(t // 60)
            s = int(t % 60)
            cues.append(f"[{m:02d}:{s:02d}] Long rambling discussion between officers discussing paperwork.")
        # Ending (Epilogue at 5000s): only 1 brief revelation cue
        cues.append("[85:00] It is finally over, we can rest now.")

        raw_subs = "\n".join(cues)
        metrics = ScriptEngine.explain_roadmap_coverage(raw_subs, 5400.0, target_output_dur_mins=10)
        assert metrics["ending_coverage"], "Ending was starved by verbose Act 1/2 dialogue!"
        assert metrics["act_breakdown"]["epilogue"] >= 1
        assert "85:00" in metrics["roadmap_lines_count"] * " " or "rest now" in ScriptEngine.compress_transcript_to_roadmap(raw_subs, 5400.0, target_output_dur_mins=10)

    def test_adversarial_case_c_dense_first_act_does_not_consume_budget(self):
        """
        Case C: First act has extremely dense dialogue (500 cues).
        It must not consume the entire roadmap budget at the expense of later acts.
        """
        cues = []
        # 400 cues packed into first 15 mins (Act 1)
        for i in range(400):
            t = i * 2.0  # 0 to 800s
            m = int(t // 60)
            s = int(t % 60)
            cues.append(f"[{m:02d}:{s:02d}] Rapid fire dialogue in Act 1 scene {i}.")
        # Moderate cues in rest of movie (800s to 5400s)
        for i in range(50):
            t = 1000.0 + i * 85.0
            m = int(t // 60)
            s = int(t % 60)
            cues.append(f"[{m:02d}:{s:02d}] Later movie progression event {i}.")

        raw_subs = "\n".join(cues)
        metrics = ScriptEngine.explain_roadmap_coverage(raw_subs, 5400.0, target_output_dur_mins=15)
        act1_count = metrics["act_breakdown"]["act1"]
        total_retained = metrics["retained_event_count"]

        # Act 1 must be bounded to approximately 20-30% of total roadmap, NOT 90%!
        assert act1_count <= total_retained * 0.35, (
            f"Act 1 hijacked roadmap budget: {act1_count} out of {total_retained} points"
        )
        assert metrics["climax_coverage"]
        assert metrics["ending_coverage"]

    def test_adversarial_case_d_repetitive_low_information_dialogue(self):
        """
        Case D: Low-information repetitive dialogue (loops/stuttering) is penalized
        in favor of narrative content.
        """
        subs = """
        [12:00] No no no no no wait wait wait wait what what what.
        [12:15] The detective discovered the secret document in the safe.
        """
        roadmap = ScriptEngine.compress_transcript_to_roadmap(subs, 3600.0, max_points=1)
        assert "secret document" in roadmap, (
            f"Repetitive dialogue loop was selected over informative cue. Roadmap:\n{roadmap}"
        )


class TestPhase3aIntrospectionAndFallback:
    """
    Validates introspection helpers and unparsed transcript fallback handling.
    """

    def test_explain_roadmap_coverage_returns_comprehensive_metrics(self):
        subs, _ = make_synthetic_transcript(3600.0, 100)
        res = ScriptEngine.explain_roadmap_coverage(subs, 3600.0, target_output_dur_mins=5)
        assert "source_event_count" in res
        assert "retained_event_count" in res
        assert "retention_ratio" in res
        assert "act_breakdown" in res
        assert res["beginning_coverage"] is True
        assert res["middle_coverage"] is True
        assert res["climax_coverage"] is True
        assert res["ending_coverage"] is True

    def test_unparsed_raw_text_balanced_fallback(self):
        """Step 8: If transcript has no parseable timestamps, balanced sample prevents ending loss."""
        raw_text = "Act 1 world introduction beginning. " * 50 + \
                   "Act 2 middle deep crisis escalation. " * 50 + \
                   "Act 3 climax final confrontation resolution ending. " * 50
        roadmap = ScriptEngine.compress_transcript_to_roadmap(raw_text, 3600.0)
        # Should contain beginning, middle, and climax markers
        assert "Act 1 world introduction" in roadmap
        assert "Act 2 middle deep crisis" in roadmap
        assert "Act 3 climax final confrontation" in roadmap
