import pytest
import time
from app.services.script_engine import (
    ScriptEngine,
    EvidencePacket,
    StoryPlanItem
)


# =============================================================================
# PHASE 3B — UNIT & ADVERSARIAL TEST SUITE
# Evidence Packets + Plan -> Write Narrative Architecture
# =============================================================================


def test_single_roadmap_cue_to_single_evidence_packet():
    """Test 1: 1 roadmap cue produces exactly 1 well-formed evidence packet."""
    subs = "[00:30] The detective enters the dark lobby."
    packets = ScriptEngine.build_evidence_packets(
        subs_text=subs,
        total_movie_dur=600.0,
        target_output_dur_mins=3
    )

    assert len(packets) == 1
    p = packets[0]
    assert p["packet_id"] == "EP-001"
    assert p["sequence_index"] == 0
    assert p["is_resolved"] is True
    assert p["confidence"] == 1.0
    assert "detective enters the dark lobby" in p["source_text"]
    assert p["movie_start"] == 30.0
    assert p["act"] == "Act 1"


def test_multiple_roadmap_cues_ordered_with_act_labels():
    """Test 2: Multiple roadmap cues produce chronologically ordered packets with correct act labels."""
    # 5 cues distributed across a 100-minute (6000s) film
    subs = """
    01:00
    Opening scene at the docks.
    20:00
    The detective discovers the forged passport.
    50:00
    Midpoint chase through the underground tunnels.
    75:00
    Climax showdown in the abandoned clock tower.
    95:00
    Epilogue: the detective watches the sunset in silence.
    """
    packets = ScriptEngine.build_evidence_packets(
        subs_text=subs,
        total_movie_dur=6000.0,
        target_output_dur_mins=5
    )

    assert len(packets) >= 4
    acts = [p["act"] for p in packets]
    # Check acts appear in chronological progression
    assert "Act 1" in acts
    assert any(a in ("Act 2A", "Act 2B") for a in acts)
    assert any(a in ("Act 3", "Epilogue") for a in acts)

    # Verify chronological ordering
    starts = [p["movie_start"] for p in packets]
    for i in range(len(starts) - 1):
        assert starts[i] <= starts[i + 1], f"Chronology violated: {starts[i]} > {starts[i+1]}"


def test_sparse_source_material_no_hallucinated_packets():
    """Test 3: Sparse source material produces at most the available cues, never inventing packets."""
    subs = """
    00:15
    First whisper in the dark.
    00:45
    Second whisper in the dark.
    """
    packets = ScriptEngine.build_evidence_packets(
        subs_text=subs,
        total_movie_dur=3600.0,
        target_output_dur_mins=10
    )

    # With only 2 source cues, packets cannot exceed 2
    assert len(packets) <= 2
    for p in packets:
        assert p["source_text"] in ("First whisper in the dark.", "Second whisper in the dark.")


def test_duplicate_timestamps_handled_cleanly():
    """Test 4: Duplicate timestamps in source dialogue are matched without collision or crash."""
    subs = """
    [05:00] Alice: Watch out!
    [05:00] Bob: Duck!
    [05:30] Charlie: Clear!
    """
    packets = ScriptEngine.build_evidence_packets(
        subs_text=subs,
        total_movie_dur=600.0,
        target_output_dur_mins=3
    )

    assert len(packets) >= 2
    assert all(p["is_resolved"] for p in packets)
    starts = [p["movie_start"] for p in packets]
    for i in range(len(starts) - 1):
        assert starts[i] <= starts[i + 1]


def test_missing_source_match_marks_unresolved():
    """Test 5: Selected cues missing from source dialogue are flagged as unresolved with zero confidence."""
    synthetic_selected = [
        {"start": 9999.0, "end": 10000.0, "text": "Completely phantom dialogue not in source", "act": "Act 3"}
    ]
    real_source = [
        {"start": 10.0, "end": 15.0, "text": "Legitimate opening dialogue"}
    ]

    packets = ScriptEngine.build_evidence_packets(
        selected_cues=synthetic_selected,
        all_source_cues=real_source,
        total_movie_dur=10000.0
    )

    assert len(packets) == 1
    p = packets[0]
    assert p["is_resolved"] is False
    assert p["confidence"] == 0.0
    assert p["cue_index"] is None


def test_bounded_local_context_extraction():
    """Test 6: Bounded local context extracts at most max_context_cues within context_window_sec."""
    # 10 cues, spaced by 10 seconds: 10, 20, 30, 40, 50, 60, 70, 80, 90, 100
    source_cues = [{"start": float(i * 10), "end": float(i * 10 + 5), "text": f"Cue number {i}"} for i in range(1, 11)]
    # Target cue is cue 5 (at 50s)
    selected = [{"start": 50.0, "end": 55.0, "text": "Cue number 5", "act": "Act 2B"}]

    packets = ScriptEngine.build_evidence_packets(
        selected_cues=selected,
        all_source_cues=source_cues,
        total_movie_dur=120.0,
        context_window_sec=45.0,
        max_context_cues=2
    )

    assert len(packets) == 1
    p = packets[0]
    # Context before: max 2 cues within 45s of 50s -> cue 3 (30s) and cue 4 (40s)
    assert "Cue number 4" in p["context_before"]
    assert "Cue number 3" in p["context_before"]
    assert "Cue number 1" not in p["context_before"]  # Out of max_context_cues limit

    # Context after: max 2 cues within 45s of 50s -> cue 6 (60s) and cue 7 (70s)
    assert "Cue number 6" in p["context_after"]
    assert "Cue number 7" in p["context_after"]
    assert "Cue number 9" not in p["context_after"]  # Out of max_context_cues limit


def test_multilingual_unicode_preservation():
    """Test 7: Multilingual Unicode text (Urdu, Hindi, Arabic, Chinese) preserved without corruption."""
    subs = """
    [01:00] داؤد نے ارباز سے کہا: تم کبھی نہیں جیت سکتے۔
    [03:00] कबीर ने चुपचाप कमरे का दरवाज़ा बंद कर दिया।
    [05:00] الحقيقة ستظهر قريباً مهما طال الوقت.
    [07:00] 侦探在桌子底下发现了一把钥匙。
    """
    packets = ScriptEngine.build_evidence_packets(
        subs_text=subs,
        total_movie_dur=600.0,
        target_output_dur_mins=3
    )

    texts = " ".join([p["source_text"] for p in packets])
    assert "داؤد نے ارباز" in texts
    assert "कबीर ने चुपचाप" in texts
    assert "الحقيقة ستظهر" in texts
    assert "侦探在桌子底下" in texts


def test_sentinel_token_provenance():
    """Test 8: Grounded sentinel token (#KEY9942, Agent-707) preserved across evidence and plan."""
    subs = "[02:30] Elena hides blue key #KEY9942 beneath floor tile near Agent-707."
    packets = ScriptEngine.build_evidence_packets(
        subs_text=subs,
        total_movie_dur=600.0,
        target_output_dur_mins=3
    )
    assert len(packets) == 1
    assert "#KEY9942" in packets[0]["source_text"]

    plan = ScriptEngine.create_grounded_story_plan(
        evidence_packets=packets,
        target_duration_mins=3
    )
    assert len(plan) == 1
    # Check that sentinel was captured in core_event or entities
    item = plan[0]
    assert "#KEY9942" in item["core_event"] or "#KEY9942" in item["entities"]


def test_strict_chronological_non_decreasing_timestamps():
    """Test 9: Generated story plan strictly enforces non-decreasing timestamps (t_i <= t_{i+1})."""
    subs = """
    00:10 Intro sequence
    05:20 Investigation begins
    12:45 First suspect questioned
    25:10 Car chase through downtown
    40:00 Final confrontation
    48:30 Epilogue
    """
    packets = ScriptEngine.build_evidence_packets(
        subs_text=subs,
        total_movie_dur=3000.0,
        target_output_dur_mins=5
    )
    plan = ScriptEngine.create_grounded_story_plan(
        evidence_packets=packets,
        target_duration_mins=5
    )

    prev_t = -1.0
    for item in plan:
        curr_t = item["source_timestamp"]
        assert curr_t >= prev_t, f"Chronology violated: {curr_t} < {prev_t}"
        prev_t = curr_t


def test_packet_sequence_indexing_format():
    """Test 10: Packet sequence indexing strictly follows 'EP-001', 'EP-002' format."""
    subs = """
    01:00 Cue one
    02:00 Cue two
    03:00 Cue three
    """
    packets = ScriptEngine.build_evidence_packets(
        subs_text=subs,
        total_movie_dur=300.0,
        target_output_dur_mins=3
    )

    for idx, p in enumerate(packets):
        expected_id = f"EP-{idx+1:03d}"
        assert p["packet_id"] == expected_id
        assert p["sequence_index"] == idx


def test_plan_evidence_references_match_valid_packet_ids():
    """Test 11: Every StoryPlanItem links to a valid, existing EvidencePacket ID."""
    subs = """
    01:00 Scene one
    05:00 Scene two
    10:00 Scene three
    15:00 Scene four
    """
    packets = ScriptEngine.build_evidence_packets(
        subs_text=subs,
        total_movie_dur=1200.0,
        target_output_dur_mins=3
    )
    plan = ScriptEngine.create_grounded_story_plan(
        evidence_packets=packets,
        target_duration_mins=3
    )

    valid_packet_ids = {p["packet_id"] for p in packets}
    for item in plan:
        assert item["evidence_ref"] in valid_packet_ids


def test_validate_story_plan_catches_all_integrity_violations():
    """Test 12: validate_story_plan catches empty plan, sequence jumps, chronology violations, invalid refs, duplicate refs, and unresolved packets."""
    valid_packets = [
        {"packet_id": "EP-001", "movie_start": 10.0, "is_resolved": True},
        {"packet_id": "EP-002", "movie_start": 50.0, "is_resolved": True},
        {"packet_id": "EP-003", "movie_start": 100.0, "is_resolved": False},  # Unresolved!
    ]

    # Case 1: Empty plan
    is_valid, msg, _ = ScriptEngine.validate_story_plan([], valid_packets)
    assert not is_valid
    assert "empty" in msg.lower()

    # Case 2: Sequence step jump (step 1 then step 3)
    bad_seq_plan = [
        {"step": 1, "source_timestamp": 10.0, "evidence_ref": "EP-001"},
        {"step": 1, "source_timestamp": 50.0, "evidence_ref": "EP-002"},  # duplicate step
    ]
    is_valid, msg, _ = ScriptEngine.validate_story_plan(bad_seq_plan, valid_packets)
    assert not is_valid
    assert "sequencing error" in msg.lower()

    # Case 3: Chronology violation (timestamp decreases)
    bad_time_plan = [
        {"step": 1, "source_timestamp": 50.0, "evidence_ref": "EP-001"},
        {"step": 2, "source_timestamp": 10.0, "evidence_ref": "EP-002"},
    ]
    is_valid, msg, _ = ScriptEngine.validate_story_plan(bad_time_plan, valid_packets)
    assert not is_valid
    assert "chronology violation" in msg.lower()

    # Case 4: Invalid evidence ref (does not exist)
    bad_ref_plan = [
        {"step": 1, "source_timestamp": 10.0, "evidence_ref": "EP-999"},
    ]
    is_valid, msg, _ = ScriptEngine.validate_story_plan(bad_ref_plan, valid_packets)
    assert not is_valid
    assert "reference error" in msg.lower()

    # Case 5: Duplicate evidence ref
    bad_dup_plan = [
        {"step": 1, "source_timestamp": 10.0, "evidence_ref": "EP-001"},
        {"step": 2, "source_timestamp": 50.0, "evidence_ref": "EP-001"},
    ]
    is_valid, msg, _ = ScriptEngine.validate_story_plan(bad_dup_plan, valid_packets)
    assert not is_valid
    assert "duplicate reference" in msg.lower()

    # Case 6: Unresolved packet reference
    bad_unres_plan = [
        {"step": 1, "source_timestamp": 10.0, "evidence_ref": "EP-003"},
    ]
    is_valid, msg, _ = ScriptEngine.validate_story_plan(bad_unres_plan, valid_packets)
    assert not is_valid
    assert "unresolved evidence" in msg.lower()

    # Case 7: Valid plan passes
    good_plan = [
        {"step": 1, "source_timestamp": 10.0, "evidence_ref": "EP-001"},
        {"step": 2, "source_timestamp": 50.0, "evidence_ref": "EP-002"},
    ]
    is_valid, msg, metrics = ScriptEngine.validate_story_plan(good_plan, valid_packets)
    assert is_valid
    assert metrics["total_plan_items"] == 2


def test_plan_word_budget_dynamic_scaling():
    """Test 13: Story plan budget words scale dynamically across target output durations (3m, 5m, 15m, 30m)."""
    subs = "\n".join([f"[{i*60:02d}:00] Event at minute {i} with critical character action." for i in range(1, 40)])
    
    budgets = []
    for dur in [3, 5, 15, 30]:
        packets = ScriptEngine.build_evidence_packets(
            subs_text=subs,
            total_movie_dur=3600.0,
            target_output_dur_mins=dur
        )
        plan = ScriptEngine.create_grounded_story_plan(
            evidence_packets=packets,
            target_duration_mins=dur,
            target_lang="en"
        )
        total_budget = sum(item["budget_words"] for item in plan)
        budgets.append((dur, total_budget))

    # Verify strictly monotonic scaling of total allocated plan words with duration
    for i in range(len(budgets) - 1):
        assert budgets[i][1] < budgets[i+1][1], f"Budget did not scale: {budgets[i]} >= {budgets[i+1]}"


def test_entity_extraction_extracts_only_source_tokens():
    """Test 14: Entity extraction extracts only tokens present in source text (no hallucinated entities)."""
    text = "Commander Shepard spoke with Dr. Liara T'Soni aboard the Normandy SR-2."
    entities = ScriptEngine._extract_grounded_entities(text)

    # All extracted entities must be substrings of the original text
    assert len(entities) > 0
    for ent in entities:
        assert ent in text, f"Entity '{ent}' is not present in original text!"

    # Common English words must NOT be identified as entities
    assert "with" not in entities
    assert "aboard" not in entities
    assert "the" not in entities


def test_stage1_to_stage2_prompt_flow():
    """Test 15: Stage 1 (evidence packets + story plan) flows cleanly into Stage 2 prompt generation."""
    subs = """
    01:00 Elena arrives at the mansion.
    10:00 Elena discovers the hidden safe.
    20:00 The alarms sound as guards enter.
    """
    prompt = ScriptEngine.build_prompt_for_genre(
        genre="movie_recap",
        title="Heist Mansion",
        description="A daring burglary",
        subs_text=subs,
        target_lang="en",
        duration_mins=3
    )

    # Prompt must contain both Phase 3B grounding headers
    assert "=== MANDATORY SOURCE EVIDENCE PACKETS (FACTUAL AUTHORITY) ===" in prompt
    assert "=== MANDATORY CHRONOLOGICAL STORY PLAN (STRUCTURAL AUTHORITY) ===" in prompt
    # Prompt must contain packet IDs and plan step markers
    assert "[EP-001]" in prompt
    assert "Step 1" in prompt


def test_explain_script_traceability_links_scenes_to_plan_and_evidence():
    """Test 16: explain_script_traceability links generated script scene blocks back to story plan items and evidence packets."""
    subs = """
    [01:15] Detective Miller inspects the broken window.
    [10:45] The suspect flees across the wet rooftops.
    """
    packets = ScriptEngine.build_evidence_packets(
        subs_text=subs,
        total_movie_dur=1200.0,
        target_output_dur_mins=3
    )
    plan = ScriptEngine.create_grounded_story_plan(
        evidence_packets=packets,
        target_duration_mins=3
    )

    # Script containing exact dialogue refs
    script_text = """
    [SCENE: 01:15 - 02:00]
    [DIALOGUE_REF: "Detective Miller inspects the broken window."]
    [VOICEOVER]
    Detective Miller stepped into the rain, carefully inspecting every shard of broken glass.

    [SCENE: 10:45 - 11:30]
    [DIALOGUE_REF: "The suspect flees across the wet rooftops."]
    [VOICEOVER]
    A dark shadow scrambled over the slippery shingles into the stormy night.
    """

    audit = ScriptEngine.explain_script_traceability(script_text, plan, packets)
    assert audit["total_scenes"] == 2
    assert audit["grounded_scenes_count"] == 2
    assert audit["grounding_ratio"] == 1.0
    assert len(audit["traceability_chain"]) == 2
    assert audit["traceability_chain"][0]["matched_evidence_ref"] == "EP-001"
    assert audit["traceability_chain"][1]["matched_evidence_ref"] == "EP-002"


def test_performance_sanity_large_cue_counts():
    """Test 17: Performance sanity test verifying O(N) throughput for 100, 500, and 1000 cues."""
    for cue_count in [100, 500, 1000]:
        subs = "\n".join([f"[{i*2:02d}:00] Character dialogue line number {i} discussing plot point." for i in range(1, cue_count + 1)])
        
        t0 = time.perf_counter()
        packets = ScriptEngine.build_evidence_packets(
            subs_text=subs,
            total_movie_dur=float(cue_count * 120),
            target_output_dur_mins=10
        )
        plan = ScriptEngine.create_grounded_story_plan(
            evidence_packets=packets,
            target_duration_mins=10
        )
        is_valid, _, _ = ScriptEngine.validate_story_plan(plan, packets)
        elapsed = time.perf_counter() - t0

        assert is_valid
        assert len(packets) > 0
        assert len(plan) > 0
        # Must execute within 1.0 second even for 1000 cues
        assert elapsed < 1.0, f"Performance bottleneck detected for {cue_count} cues: took {elapsed:.3f}s"
