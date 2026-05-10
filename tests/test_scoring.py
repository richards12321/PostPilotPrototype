"""Regression tests for pure scoring functions.

These tests do NOT call the LLM or the DB. They cover:
  - Layer 1 deterministic question selection and scoring
  - Layer 2 simulation engine (week ticks, fatigue, cash, completions, scoring)
  - Layer 2 decision overwrites (v7: idempotent retain -> let_go)
  - Layer 3 aggregation (no LLM, 0-25 per competency)
  - Scoring matrix (overall + simplified Top Fit)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from assessment_logic import layer1_logic, layer2_logic, scoring_matrix


# ----- Layer 1 -----

def test_theme_score_perfect():
    assert layer1_logic.theme_score(10, 10) == 100.0


def test_theme_score_zero():
    assert layer1_logic.theme_score(0, 10) == 0.0


def test_theme_score_partial():
    assert layer1_logic.theme_score(7, 10) == 70.0


def test_theme_time_limits_match_spec():
    """v7: theme totals are 750/900/450 seconds."""
    assert layer1_logic.theme_time_limit_for("logical") == 750
    assert layer1_logic.theme_time_limit_for("numerical") == 900
    assert layer1_logic.theme_time_limit_for("verbal") == 450


def test_time_limit_for_is_per_question_average_shim():
    """The backward-compat shim returns the per-question average."""
    assert layer1_logic.time_limit_for("logical") == 75
    assert layer1_logic.time_limit_for("numerical") == 90
    assert layer1_logic.time_limit_for("verbal") == 45


def test_aggregate_layer1_averages_themes():
    total, comp = layer1_logic.aggregate_layer1(
        {"logical": 80, "numerical": 60, "verbal": 70}
    )
    assert total == 70.0
    assert comp["competency_analytical"] == 80
    assert comp["competency_numerical"] == 60
    assert comp["competency_verbal"] == 70


def test_select_questions_is_deterministic():
    q1 = layer1_logic.select_questions("candidate-abc", "logical")
    q2 = layer1_logic.select_questions("candidate-abc", "logical")
    assert [q.question_id for q in q1] == [q.question_id for q in q2]
    assert [q.correct_option for q in q1] == [q.correct_option for q in q2]


def test_select_questions_different_candidates_may_differ():
    q1 = layer1_logic.select_questions("candidate-aaa", "logical")
    q2 = layer1_logic.select_questions("candidate-zzz", "logical")
    assert q1 != q2


# ----- Layer 2 simulation engine -----

@pytest.fixture
def scenario():
    return layer2_logic.load_scenario()


def test_initial_state_seeds_correctly(scenario):
    state = layer2_logic.initial_state(scenario)
    assert state["current_week"] == 1
    assert state["cash"] == 500000
    assert state["reputation"] == 60
    assert state["total_weeks"] == 8
    assert all(v == 0 for v in state["fatigue"].values())
    assert len(state["fatigue"]) == 6
    assert all(p["status"] == "available" for p in state["projects"].values())
    # v7: decision_applied_effects is initialized empty
    assert state["decision_applied_effects"] == {}


def test_advance_week_increments_counter(scenario):
    state = layer2_logic.initial_state(scenario)
    new_state = layer2_logic.advance_week(scenario, state, weekly_assignments={})
    assert new_state["current_week"] == 2
    assert state["current_week"] == 1


def test_unstaffed_active_project_eventually_cancels(scenario):
    """If a project becomes active and is then unstaffed for 2+ weeks, it cancels."""
    state = layer2_logic.initial_state(scenario)
    state = layer2_logic.advance_week(scenario, state, {"P3": ["C4", "C5"]})
    assert state["projects"]["P3"]["status"] == "active"
    state = layer2_logic.advance_week(scenario, state, {})
    state = layer2_logic.advance_week(scenario, state, {})
    assert state["projects"]["P3"]["status"] == "cancelled"
    assert state["reputation"] < 60


def test_project_completes_when_fully_staffed_for_duration(scenario):
    """P1 has duration 4 weeks. Staff Anna for 4 straight weeks -> completes."""
    state = layer2_logic.initial_state(scenario)
    initial_cash = state["cash"]
    for _ in range(4):
        state = layer2_logic.advance_week(scenario, state, {"P1": ["C1"]})
    assert state["projects"]["P1"]["status"] == "completed"
    assert state["cash"] > initial_cash


def test_fatigue_rises_with_staffing_falls_on_bench(scenario):
    state = layer2_logic.initial_state(scenario)
    state = layer2_logic.advance_week(scenario, state, {"P1": ["C1"]})
    state = layer2_logic.advance_week(scenario, state, {"P1": ["C1"]})
    assert state["fatigue"]["C1"] == 30
    state = layer2_logic.advance_week(scenario, state, {})
    assert state["fatigue"]["C1"] == 5


def test_sick_consultant_cant_be_staffed(scenario):
    state = layer2_logic.initial_state(scenario)
    for _ in range(2):
        state = layer2_logic.advance_week(scenario, state, {})
    assert state["current_week"] == 3
    state = layer2_logic.advance_week(scenario, state, {"P2": ["C2"]})
    assert state["projects"]["P2"]["weeks_unstaffed_consecutive"] >= 1


def test_double_booking_only_counts_first_project(scenario):
    state = layer2_logic.initial_state(scenario)
    state = layer2_logic.advance_week(scenario, state, {"P1": ["C1"], "P2": ["C1"]})
    assert state["fatigue"]["C1"] == 15
    assert state["projects"]["P1"]["weeks_staffed_correctly"] == 1
    assert state["projects"]["P2"]["weeks_staffed_correctly"] == 0


def test_validate_weekly_assignments_catches_double_booking(scenario):
    state = layer2_logic.initial_state(scenario)
    warnings = layer2_logic.validate_weekly_assignments(
        scenario, state, week=1,
        assignments={"P1": ["C1"], "P2": ["C1"]},
    )
    assert any("multiple" in w.lower() for w in warnings)


def test_validate_weekly_assignments_catches_invisible_project(scenario):
    state = layer2_logic.initial_state(scenario)
    warnings = layer2_logic.validate_weekly_assignments(
        scenario, state, week=1,
        assignments={"P5": ["C1"]},
    )
    assert any("aren't active" in w or "not active" in w.lower() for w in warnings)


def test_tradeoff_choice_applied_in_week_6(scenario):
    state = layer2_logic.initial_state(scenario)
    for _ in range(5):
        state = layer2_logic.advance_week(scenario, state, {})
    assert state["current_week"] == 6
    cash_before = state["cash"]
    rep_before = state["reputation"]
    state = layer2_logic.advance_week(scenario, state, {}, tradeoff_choice="A")
    assert state["cash"] == cash_before + 220000
    assert state["reputation"] == rep_before - 5
    assert state["tradeoff_choice"] == "A"


def test_visible_projects_filters_by_week_and_status(scenario):
    state = layer2_logic.initial_state(scenario)
    visible_w1 = [p["id"] for p in layer2_logic.projects_visible_in_week(scenario, state, 1)]
    assert "P5" not in visible_w1
    assert "P8" not in visible_w1
    assert "P1" in visible_w1

    visible_w7 = [p["id"] for p in layer2_logic.projects_visible_in_week(scenario, state, 7)]
    assert "P5" in visible_w7
    assert "P8" in visible_w7


def test_outcome_score_starting_state_baseline(scenario):
    """End the sim with no actions: low score, with partial credit for not
    burning cash or reputation. The calibration was tuned in v6 to give
    break-even a modest baseline (cash 20pts + rep 10pts = 30 outcome pts,
    weighted to ~21 total) rather than 0, so a candidate who freezes isn't
    pushed to a 0 floor while a candidate who actively makes things worse is.
    """
    state = layer2_logic.initial_state(scenario)
    for _ in range(8):
        state = layer2_logic.advance_week(scenario, state, {})
    result = layer2_logic.final_layer2_score(state, scenario)
    assert result["process_score"] == 0.0     # never staffed anything
    assert result["layer2_total"] < 30.0      # well below a real "good" score
    assert 0 <= result["outcome_score"] <= 35
    assert 0 <= result["layer2_total"] <= 30


def test_decent_play_scores_meaningfully(scenario):
    state = layer2_logic.initial_state(scenario)
    plans = [
        {"P1": ["C1"], "P2": ["C2", "C3"], "P3": ["C4", "C5"], "P4": ["C6"]},
        {"P1": ["C1"], "P2": ["C2", "C3"], "P3": ["C4", "C5"], "P4": ["C6"]},
        {"P1": ["C1"], "P2": ["C3"],       "P3": ["C4", "C5"], "P4": ["C6"]},
        {"P1": ["C1"], "P2": ["C2", "C3"], "P3": ["C4", "C5"], "P4": ["C6"]},
        {"P2": ["C2", "C3"], "P3": ["C4", "C5"], "P5": ["C1", "C6"]},
        {"P2": ["C2", "C3"], "P3": ["C4", "C5"], "P5": ["C1", "C6"]},
        {"P2": ["C2", "C3"], "P3": ["C4", "C5"], "P8": ["C6"]},
        {"P3": ["C4", "C5"], "P8": ["C6"]},
    ]
    for week_idx, plan in enumerate(plans, start=1):
        d = ("david_resigns", "retain") if week_idx == 2 else None
        t = "A" if week_idx == 6 else None
        state = layer2_logic.advance_week(scenario, state, plan, tradeoff_choice=t, decision_choice=d)
    result = layer2_logic.final_layer2_score(state, scenario)
    assert result["layer2_total"] >= 70


def test_week2_decision_retain_preserves_consultant(scenario):
    state = layer2_logic.initial_state(scenario)
    state = layer2_logic.advance_week(scenario, state, {"P3": ["C4", "C5"]})
    cash_after_w1 = state["cash"]
    state = layer2_logic.advance_week(
        scenario, state, {"P3": ["C4", "C5"]},
        decision_choice=("david_resigns", "retain"),
    )
    assert state["cash"] < cash_after_w1
    available_w5 = layer2_logic.consultants_available_in_week(scenario, state, 5)
    assert any(c["id"] == "C4" for c in available_w5)


def test_week2_decision_let_go_consultant_leaves_after_notice(scenario):
    state = layer2_logic.initial_state(scenario)
    state = layer2_logic.advance_week(scenario, state, {})
    state = layer2_logic.advance_week(
        scenario, state, {},
        decision_choice=("david_resigns", "let_go"),
    )
    available_w3 = layer2_logic.consultants_available_in_week(scenario, state, 3)
    assert any(c["id"] == "C4" for c in available_w3)
    available_w4 = layer2_logic.consultants_available_in_week(scenario, state, 4)
    assert not any(c["id"] == "C4" for c in available_w4)


def test_week2_decision_accelerate_consultant_leaves_immediately(scenario):
    state = layer2_logic.initial_state(scenario)
    state = layer2_logic.advance_week(scenario, state, {})
    state = layer2_logic.advance_week(
        scenario, state, {},
        decision_choice=("david_resigns", "accelerate"),
    )
    available_w3 = layer2_logic.consultants_available_in_week(scenario, state, 3)
    assert not any(c["id"] == "C4" for c in available_w3)


def test_pending_decision_detected_in_week2(scenario):
    state = layer2_logic.initial_state(scenario)
    state = layer2_logic.advance_week(scenario, state, {})
    pending = layer2_logic.pending_decision_for_week(scenario, state, 2)
    assert pending is not None
    assert pending["consultant_id"] == "C4"


def test_pending_decision_cleared_after_choice(scenario):
    state = layer2_logic.initial_state(scenario)
    state = layer2_logic.advance_week(scenario, state, {})
    state = layer2_logic.advance_week(
        scenario, state, {},
        decision_choice=("david_resigns", "retain"),
    )
    pending_w3 = layer2_logic.pending_decision_for_week(scenario, state, 3)
    assert pending_w3 is None


# ----- v7: idempotent decision overwrite -----

def test_decision_overwrite_retain_then_let_go_refunds_and_applies_let_go(scenario):
    """v7 bug fix: switching retain -> let_go must refund the €40,000 retention
    bonus and apply let_go's penalties cleanly. David must be unavailable from
    Week 4 onwards (let_go = leave_week_3 means departed_at_week = 4)."""
    state = layer2_logic.initial_state(scenario)

    cash_before = state["cash"]
    rep_before = state["reputation"]

    # First: apply retain (the candidate's first pick).
    layer2_logic.apply_decision(state, scenario, "david_resigns", "retain")
    assert state["cash"] == cash_before - 40000
    assert state["reputation"] == rep_before  # retain has 0 rep effect
    # David is NOT in the departed map after retain.
    assert "C4" not in state.get("consultants_departed_at_week", {})

    # Now: candidate changes their mind, picks let_go before clicking Advance.
    layer2_logic.apply_decision(state, scenario, "david_resigns", "let_go")

    # The €40k retention bonus must have been refunded; let_go has 0 cash effect.
    # Net change vs the pristine starting state: 0.
    assert state["cash"] == cash_before
    # let_go's reputation effect (-2) must apply.
    assert state["reputation"] == rep_before - 2
    # David must have a departure week set (let_go = current_week + 2 = 1 + 2 = 3).
    # Note: at the time apply_decision is called, current_week is still 1, since
    # the decision is applied at the top of advance_week before current_week increments.
    assert state["consultants_departed_at_week"].get("C4") == 3
    # The recorded final choice is let_go.
    assert state["decision_choices"]["david_resigns"] == "let_go"


def test_decision_overwrite_through_advance_week(scenario):
    """End-to-end: the same overwrite happens cleanly when invoked via
    advance_week. Switching retain -> let_go before the week ticks results
    in only let_go's effects on the post-advance state.
    """
    state = layer2_logic.initial_state(scenario)
    state = layer2_logic.advance_week(scenario, state, {})  # to Week 2
    cash_before_w2 = state["cash"]
    rep_before_w2 = state["reputation"]

    # Apply retain first (simulating an earlier UI selection).
    layer2_logic.apply_decision(state, scenario, "david_resigns", "retain")
    # Then advance the week with the candidate's *final* choice = let_go.
    state = layer2_logic.advance_week(
        scenario, state, {},
        decision_choice=("david_resigns", "let_go"),
    )

    # Net cash effect of the decision over Week 2 should be 0 (let_go cost),
    # any other Week 2 cash flow (none here, no projects staffed) included.
    assert state["cash"] == cash_before_w2
    assert state["reputation"] == rep_before_w2 - 2
    # David available in W3 (notice period), gone from W4.
    available_w3 = layer2_logic.consultants_available_in_week(scenario, state, 3)
    assert any(c["id"] == "C4" for c in available_w3)
    available_w4 = layer2_logic.consultants_available_in_week(scenario, state, 4)
    assert not any(c["id"] == "C4" for c in available_w4)


def test_full_layer2_score_keys(scenario):
    state = layer2_logic.initial_state(scenario)
    for _ in range(8):
        state = layer2_logic.advance_week(scenario, state, {})
    result = layer2_logic.final_layer2_score(state, scenario)
    assert set(result.keys()) >= {"layer2_total", "outcome_score", "process_score",
                                    "outcome_breakdown", "process_breakdown"}
    assert 0 <= result["layer2_total"] <= 100
    assert 0 <= result["outcome_score"] <= 100
    assert 0 <= result["process_score"] <= 100


def test_aggregate_layer2_returns_competencies(scenario):
    state = layer2_logic.initial_state(scenario)
    for _ in range(8):
        state = layer2_logic.advance_week(scenario, state, {})
    total, comp = layer2_logic.aggregate_layer2(state, scenario)
    assert "competency_strategic" in comp
    assert "competency_adaptability" in comp


def test_good_player_scores_higher_than_no_action(scenario):
    no_action = layer2_logic.initial_state(scenario)
    for _ in range(8):
        no_action = layer2_logic.advance_week(scenario, no_action, {})
    no_action_result = layer2_logic.final_layer2_score(no_action, scenario)

    good = layer2_logic.initial_state(scenario)
    weekly_plan = [
        {"P1": ["C1"], "P2": ["C2", "C3"], "P3": ["C4", "C5"], "P4": ["C6"]},
        {"P1": ["C1"], "P2": ["C2", "C3"], "P3": ["C4", "C5"], "P4": ["C6"]},
        {"P1": ["C1"], "P2": ["C3"],       "P3": ["C4", "C5"], "P4": ["C6"]},
        {"P1": ["C1"], "P2": ["C2", "C3"], "P3": ["C4", "C5"], "P4": ["C6"]},
        {"P2": ["C2", "C3"], "P3": ["C4", "C5"], "P4": ["C6"], "P1": ["C1"]},
        {"P2": ["C2", "C3"], "P3": ["C4", "C5"], "P4": ["C6"]},
        {"P2": ["C2", "C3"], "P3": ["C4", "C5"], "P8": ["C6", "C1"]},
        {"P3": ["C4", "C5"], "P8": ["C6", "C1"]},
    ]
    for week_idx, plan in enumerate(weekly_plan, start=1):
        tradeoff = "A" if week_idx == 6 else None
        good = layer2_logic.advance_week(scenario, good, plan, tradeoff_choice=tradeoff)
    good_result = layer2_logic.final_layer2_score(good, scenario)

    assert good_result["layer2_total"] > no_action_result["layer2_total"]


# ----- Scoring matrix (v7: simplified Top Fit) -----

def test_overall_score_weights():
    # 60*0.30 + 70*0.35 + 80*0.35 = 18 + 24.5 + 28 = 70.5
    assert scoring_matrix.overall_score(60, 70, 80) == 70.5


def test_top_fit_v7_overall_70_or_higher_passes():
    """Single rule: overall >= 70 is the only criterion."""
    assert scoring_matrix.classify_top_fit(70) == 1
    assert scoring_matrix.classify_top_fit(85) == 1


def test_top_fit_v7_below_70_fails():
    assert scoring_matrix.classify_top_fit(69) == 0
    assert scoring_matrix.classify_top_fit(0) == 0


def test_top_fit_ignores_extra_args():
    """Old multi-criteria args are accepted but ignored under v7."""
    assert scoring_matrix.classify_top_fit(75, 50, 50, 50, {}) == 1
    assert scoring_matrix.classify_top_fit(60, 100, 100, 100, {"x": 99}) == 0


def test_assemble_final_scores_structure_v7():
    data = scoring_matrix.assemble_final_scores(
        candidate_id="cid-1",
        layer1=75, layer2=80, layer3=70,
        l1_comp={"competency_analytical": 75, "competency_numerical": 75, "competency_verbal": 75},
        l2_comp={"competency_strategic": 80, "competency_adaptability": 80},
        l3_comp={
            "competency_l3_growth_mindset": 70,
            "competency_l3_adaptability": 70,
            "competency_l3_collaboration": 70,
            "competency_l3_self_reflection": 70,
        },
        candidate_feedback="feedback",
        recruiter_summary="summary",
        ai_flags={"ai_flag_logical": 1, "ai_flag_layer2": 1},
    )
    assert data["candidate_id"] == "cid-1"
    assert data["top_fit"] == 1
    assert "overall_score" in data
    assert data["competency_l3_growth_mindset"] == 70
    # AI flags pass through as 0/1 ints
    assert data["ai_flag_logical"] == 1
    assert data["ai_flag_numerical"] == 0
    assert data["ai_flag_verbal"] == 0
    assert data["ai_flag_layer2"] == 1


# ----- Layer 3 aggregation (pure, no LLM, 0-25 per competency) -----

def test_aggregate_layer3_sums_to_100_v7():
    """v7: 4 competencies, scored 0-25 each, sum is 0-100 directly (no scaling)."""
    from assessment_logic import layer3_logic
    competency_scores = [
        {"competency_key": "growth_mindset", "score": 18},
        {"competency_key": "adaptability", "score": 15},
        {"competency_key": "collaboration", "score": 20},
        {"competency_key": "self_reflection", "score": 12},
    ]
    total, comp = layer3_logic.aggregate_layer3(competency_scores)
    assert total == 65.0  # 18+15+20+12
    # Per-competency scaled to 0-100 (* 4)
    assert comp["competency_l3_growth_mindset"] == 72.0   # 18 * 4
    assert comp["competency_l3_adaptability"] == 60.0     # 15 * 4
    assert comp["competency_l3_collaboration"] == 80.0    # 20 * 4
    assert comp["competency_l3_self_reflection"] == 48.0  # 12 * 4


def test_aggregate_layer3_empty_v7():
    from assessment_logic import layer3_logic
    total, comp = layer3_logic.aggregate_layer3([])
    assert total == 0.0
    # All four v7 keys present and zero
    assert comp["competency_l3_growth_mindset"] == 0.0
    assert comp["competency_l3_adaptability"] == 0.0
    assert comp["competency_l3_collaboration"] == 0.0
    assert comp["competency_l3_self_reflection"] == 0.0


def test_aggregate_layer3_clamps_total():
    """Total caps at 100 even if scores somehow exceed (defensive)."""
    from assessment_logic import layer3_logic
    competency_scores = [
        {"competency_key": "growth_mindset", "score": 25},
        {"competency_key": "adaptability", "score": 25},
        {"competency_key": "collaboration", "score": 25},
        {"competency_key": "self_reflection", "score": 25},
    ]
    total, _ = layer3_logic.aggregate_layer3(competency_scores)
    assert total == 100.0


def test_interpret_total_bands():
    from assessment_logic import layer3_logic
    assert layer3_logic.interpret_total(35)["label"] == "Below threshold"
    assert layer3_logic.interpret_total(50)["label"] == "Borderline"
    assert layer3_logic.interpret_total(65)["label"] == "Good"
    assert layer3_logic.interpret_total(80)["label"] == "Strong"
    assert layer3_logic.interpret_total(95)["label"] == "Exceptional"
