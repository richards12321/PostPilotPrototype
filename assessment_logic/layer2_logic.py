"""Layer 2 logic: 8-week firm simulation with calibrated scoring.

Pure functions over (state, weekly_assignments) -> new_state. The candidate
plays a resource manager for 8 simulated weeks. Cash, reputation, consultant
fatigue, and project progress all carry forward.

Scoring:
    Layer 2 total = 0.70 * outcome_score + 0.30 * process_score

Calibration anchors:
    - Doing nothing for 8 weeks => 0
    - Near-perfect play         => 100
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCENARIO_PATH = Path(__file__).parent.parent / "data" / "layer2_scenario.json"

TOTAL_WEEKS = 8
LAYER_TIME_LIMIT_SECONDS = 20 * 60

OUTCOME_WEIGHT = 0.70
PROCESS_WEIGHT = 0.30

SENIORITY_RANK = {"Consultant": 1, "Manager": 2, "Senior": 3}


def initial_state(scenario: dict) -> dict:
    """Build the starting state dict that we'll mutate week by week."""
    starting = scenario["starting_state"]
    return {
        "current_week": 1,
        "cash": starting["cash"],
        "reputation": starting["reputation"],
        "starting_cash": starting["cash"],
        "starting_reputation": starting["reputation"],
        "total_weeks": starting["total_weeks"],
        "fatigue": {c["id"]: 0 for c in scenario["consultants"]},
        "projects": {
            p["id"]: {
                "weeks_staffed_correctly": 0,
                "weeks_unstaffed_consecutive": 0,
                "status": "available",
                "quality_multiplier": 1.0,
                "completion_week": None,
            } for p in scenario["projects"]
        },
        "weekly_assignments_history": {},
        "events_history": {},
        "tradeoff_choice": None,
        "decision_choices": {},
        # Tracks the deltas we already applied for each decision_id, so that
        # if the candidate changes their mind and a different choice is
        # applied for the same decision, we can refund the previous effect
        # cleanly before applying the new one. Keyed by decision_id; each
        # value is {"cash": int, "reputation": int, "consultant_id": str|None,
        # "departed_at_week": int|None}.
        "decision_applied_effects": {},
        # consultant_id -> week they leave (exclusive). If absent, they're still around.
        "consultants_departed_at_week": {},
        "weekly_log": [],
    }


def load_scenario() -> dict:
    with open(SCENARIO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ----- Per-week queries the UI needs -----

def projects_visible_in_week(scenario: dict, state: dict, week: int) -> List[dict]:
    out = []
    for p in scenario["projects"]:
        if p["available_from_week"] > week:
            continue
        status = state["projects"][p["id"]]["status"]
        if status in ("completed", "cancelled", "quality_failure", "missed_deadline"):
            continue
        modified = dict(p)
        for ev in scenario.get("weekly_events", []):
            if ev["type"] == "budget_cut" and ev["week"] <= week and ev["project_id"] == p["id"]:
                modified["weekly_burn"] = ev["new_burn"]
        out.append(modified)
    return out


def consultants_available_in_week(scenario: dict, state: dict, week: int) -> List[dict]:
    """All consultants minus anyone sick this week minus anyone who has departed."""
    sick_ids: set = set()
    for ev in scenario.get("weekly_events", []):
        if ev["type"] != "sick_leave":
            continue
        start = ev["week"]
        end = start + ev.get("duration_weeks", 1) - 1
        if start <= week <= end:
            sick_ids.add(ev["consultant_id"])

    departed = state.get("consultants_departed_at_week", {})
    departed_ids = {cid for cid, leave_week in departed.items() if leave_week <= week}

    return [c for c in scenario["consultants"]
            if c["id"] not in sick_ids and c["id"] not in departed_ids]


def events_for_week(scenario: dict, week: int) -> List[dict]:
    return [ev for ev in scenario.get("weekly_events", []) if ev["week"] == week]


def pending_decision_for_week(scenario: dict, state: dict, week: int) -> Optional[dict]:
    """Return the decision spec if a decision is required this week and not yet made."""
    decisions = scenario.get("decisions", {})
    for ev in events_for_week(scenario, week):
        if ev.get("type") == "decision":
            decision_id = ev["decision_id"]
            if decision_id in state.get("decision_choices", {}):
                return None
            return decisions.get(decision_id)
    return None


# ----- Validation -----

def validate_weekly_assignments(
    scenario: dict, state: dict, week: int,
    assignments: Dict[str, List[str]],
) -> List[str]:
    warnings = []
    visible_projects = {p["id"] for p in projects_visible_in_week(scenario, state, week)}
    available_ids = {c["id"] for c in consultants_available_in_week(scenario, state, week)}

    seen: set = set()
    dupes: set = set()
    for cids in assignments.values():
        for cid in cids:
            if cid in seen:
                dupes.add(cid)
            seen.add(cid)
    if dupes:
        warnings.append(f"Consultants assigned to multiple projects this week: {', '.join(sorted(dupes))}")

    sick_assigned = [cid for cids in assignments.values() for cid in cids if cid not in available_ids]
    if sick_assigned:
        warnings.append(f"These consultants are unavailable this week: {', '.join(sick_assigned)}")

    bad_projects = [pid for pid in assignments if pid not in visible_projects]
    if bad_projects:
        warnings.append(f"Cannot staff projects that aren't active this week: {', '.join(bad_projects)}")

    return warnings


# ----- Quality calculation -----

def _project_week_quality(
    project: dict, assigned_consultants: List[dict], scenario: dict, state: dict,
) -> Tuple[float, List[str]]:
    consts = scenario["scoring_constants"]
    if not assigned_consultants:
        return 0.0, []

    multiplier = 1.0
    issues = []

    required = set(project.get("required_skills", []))
    covered: set = set()
    for c in assigned_consultants:
        covered.update(c["skills"])
    missing = required - covered
    if missing:
        multiplier *= consts["skill_mismatch_quality_penalty"]
        issues.append(f"Missing skills: {', '.join(sorted(missing))}")

    min_sen_rank = SENIORITY_RANK.get(project.get("min_seniority", "Consultant"), 1)
    if not any(SENIORITY_RANK.get(c["seniority"], 1) >= min_sen_rank for c in assigned_consultants):
        multiplier *= consts["seniority_mismatch_quality_penalty"]
        issues.append(f"No one meets min seniority ({project.get('min_seniority')})")

    max_fatigue = max(state["fatigue"].get(c["id"], 0) for c in assigned_consultants)
    if max_fatigue >= consts["fatigue_quality_threshold"]:
        multiplier *= consts["quality_penalty_high_fatigue"]
        issues.append(f"High consultant fatigue ({max_fatigue})")

    return multiplier, issues


# ----- Decisions (Week 2 resignation, etc.) -----

def apply_decision(state: dict, scenario: dict, decision_id: str, choice_id: str) -> None:
    """Apply (or re-apply) a decision to state.

    Idempotent and overwriting: if this decision has already been applied
    once and the candidate changes their mind, we first reverse the prior
    effects (refund cash, reverse reputation, clear any departure record)
    before applying the new choice. This means the radio re-selection in
    the UI cannot leave stale effects behind.
    """
    decision = scenario.get("decisions", {}).get(decision_id)
    if not decision:
        return
    chosen = next((o for o in decision["options"] if o["id"] == choice_id), None)
    if not chosen:
        return

    state.setdefault("decision_applied_effects", {})

    # 1. Reverse any prior application of this decision.
    prior = state["decision_applied_effects"].get(decision_id)
    if prior:
        state["cash"] -= prior.get("cash", 0)
        state["reputation"] -= prior.get("reputation", 0)
        prior_cid = prior.get("consultant_id")
        if prior_cid is not None:
            state.get("consultants_departed_at_week", {}).pop(prior_cid, None)

    # 2. Apply the new choice.
    state["decision_choices"][decision_id] = choice_id

    effects = chosen.get("effects", {})
    cash_delta = int(effects.get("cash", 0))
    rep_delta = int(effects.get("reputation", 0))
    state["cash"] += cash_delta
    state["reputation"] += rep_delta

    consultant_change = effects.get("consultant_change")
    cid = decision.get("consultant_id")
    departed_at_week: int | None = None
    if cid:
        if consultant_change == "leave_immediately":
            departed_at_week = state["current_week"]
            state["consultants_departed_at_week"][cid] = departed_at_week
        elif consultant_change == "leave_week_3":
            # leaves at the end of next week, i.e. unavailable from current_week+2
            departed_at_week = state["current_week"] + 2
            state["consultants_departed_at_week"][cid] = departed_at_week
        # "keep" means no departure recorded

    # 3. Record what we just did so a future overwrite can reverse it.
    state["decision_applied_effects"][decision_id] = {
        "cash": cash_delta,
        "reputation": rep_delta,
        "consultant_id": cid,
        "departed_at_week": departed_at_week,
    }


# ----- Week tick -----

def advance_week(
    scenario: dict, state: dict,
    weekly_assignments: Dict[str, List[str]],
    tradeoff_choice: Optional[str] = None,
    decision_choice: Optional[Tuple[str, str]] = None,
) -> dict:
    """Advance one week. Returns a new state dict."""
    new_state = copy.deepcopy(state)
    consts = scenario["scoring_constants"]
    week = new_state["current_week"]
    consultants_by_id = {c["id"]: c for c in scenario["consultants"]}
    projects_by_id = {p["id"]: p for p in scenario["projects"]}

    burn_overrides = {}
    for ev in scenario.get("weekly_events", []):
        if ev["type"] == "budget_cut" and ev["week"] <= week:
            burn_overrides[ev["project_id"]] = ev["new_burn"]

    week_log = {
        "week": week,
        "actions": [],
        "events_fired": [ev["message"] for ev in events_for_week(scenario, week)],
        "cash_change": 0,
        "reputation_change": 0,
        "completions": [],
        "cancellations": [],
        "quality_failures": [],
        "missed_deadlines": [],
        "tradeoff_choice": None,
        "decision": None,
    }

    # 0. Apply decision if one was made this week
    if decision_choice:
        decision_id, choice_id = decision_choice
        cash_before = new_state["cash"]
        rep_before = new_state["reputation"]
        apply_decision(new_state, scenario, decision_id, choice_id)
        week_log["decision"] = {"decision_id": decision_id, "choice_id": choice_id}
        week_log["cash_change"] += new_state["cash"] - cash_before
        week_log["reputation_change"] += new_state["reputation"] - rep_before

    # 1. Trade-off (Week 6), applies before regular week processing
    if week == scenario.get("tradeoff", {}).get("trigger_week") and tradeoff_choice:
        tradeoff = scenario["tradeoff"]
        chosen = next((o for o in tradeoff["options"] if o["id"] == tradeoff_choice), None)
        if chosen:
            new_state["tradeoff_choice"] = tradeoff_choice
            effects = chosen.get("effects", {})
            new_state["cash"] += effects.get("cash", 0)
            new_state["reputation"] += effects.get("reputation", 0)
            week_log["tradeoff_choice"] = tradeoff_choice
            week_log["cash_change"] += effects.get("cash", 0)
            week_log["reputation_change"] += effects.get("reputation", 0)

    # 2. Process each project's staffing this week
    staffed_consultants_this_week: set = set()
    for project_id, project in projects_by_id.items():
        proj_state = new_state["projects"][project_id]
        if proj_state["status"] in ("completed", "cancelled", "quality_failure", "missed_deadline"):
            continue
        if project["available_from_week"] > week:
            continue

        cids = weekly_assignments.get(project_id, [])
        available_ids = {c["id"] for c in consultants_available_in_week(scenario, new_state, week)}
        cids = [cid for cid in cids if cid in consultants_by_id and cid in available_ids]
        cids = [cid for cid in cids if cid not in staffed_consultants_this_week]
        for cid in cids:
            staffed_consultants_this_week.add(cid)

        assigned = [consultants_by_id[cid] for cid in cids]

        if not assigned:
            proj_state["weeks_unstaffed_consecutive"] += 1
            if proj_state["status"] == "active" and proj_state["weeks_unstaffed_consecutive"] >= consts["unstaffed_weeks_before_cancellation"]:
                proj_state["status"] = "cancelled"
                new_state["reputation"] += consts["reputation_on_cancellation"]
                week_log["reputation_change"] += consts["reputation_on_cancellation"]
                week_log["cancellations"].append(project_id)
            continue

        proj_state["weeks_unstaffed_consecutive"] = 0
        if proj_state["status"] == "available":
            proj_state["status"] = "active"

        weekly_burn = burn_overrides.get(project_id, project["weekly_burn"])
        new_state["cash"] -= weekly_burn
        week_log["cash_change"] -= weekly_burn

        quality_mult, issues = _project_week_quality(project, assigned, scenario, new_state)
        proj_state["weeks_staffed_correctly"] += 1
        proj_state["quality_multiplier"] = (
            (proj_state["quality_multiplier"] * (proj_state["weeks_staffed_correctly"] - 1) + quality_mult)
            / proj_state["weeks_staffed_correctly"]
        )

        action = {
            "project_id": project_id,
            "consultant_ids": cids,
            "burn": weekly_burn,
            "quality_mult_this_week": quality_mult,
            "issues": issues,
        }
        week_log["actions"].append(action)

        if proj_state["weeks_staffed_correctly"] >= project["duration_weeks"]:
            proj_state["completion_week"] = week
            avg_quality = proj_state["quality_multiplier"]
            if avg_quality < 0.6:
                proj_state["status"] = "quality_failure"
                payout = int(project.get("revenue", 0) * 0.5)
                new_state["cash"] += payout
                new_state["reputation"] += consts["reputation_on_quality_failure"]
                week_log["cash_change"] += payout
                week_log["reputation_change"] += consts["reputation_on_quality_failure"]
                week_log["quality_failures"].append(project_id)
            else:
                proj_state["status"] = "completed"
                payout = int(project.get("revenue", 0) * avg_quality)
                new_state["cash"] += payout
                tier = project.get("priority_tier", "C")
                rep_gain = consts.get(f"reputation_on_completion_tier_{tier}", 3)
                new_state["reputation"] += rep_gain
                week_log["cash_change"] += payout
                week_log["reputation_change"] += rep_gain
                week_log["completions"].append(project_id)

    # 3. Update fatigue
    for cid in new_state["fatigue"]:
        if cid in staffed_consultants_this_week:
            new_state["fatigue"][cid] = min(100, new_state["fatigue"][cid] + consts["fatigue_per_week_staffed"])
        else:
            new_state["fatigue"][cid] = max(0, new_state["fatigue"][cid] - consts["fatigue_recovery_per_week_unstaffed"])

    # 4. Missed deadlines
    for project_id, project in projects_by_id.items():
        proj_state = new_state["projects"][project_id]
        deadline = project.get("deadline_week", scenario["starting_state"]["total_weeks"])
        if proj_state["status"] == "active" and week >= deadline:
            proj_state["status"] = "missed_deadline"
            new_state["reputation"] += consts["reputation_on_missed_deadline"]
            week_log["reputation_change"] += consts["reputation_on_missed_deadline"]
            week_log["missed_deadlines"].append(project_id)

    new_state["reputation"] = max(0, min(100, new_state["reputation"]))

    new_state["weekly_assignments_history"][str(week)] = weekly_assignments
    new_state["weekly_log"].append(week_log)
    new_state["current_week"] = week + 1

    return new_state


def is_simulation_complete(state: dict) -> bool:
    return state["current_week"] > state["total_weeks"]


# ----- Final scoring (calibrated) -----
#
# Calibration: doing nothing => ~0-5. Competent play => 65-75. Strong play => 85+.
#
# Outcome (out of 100):
#   - Cash management (40 pts): rewards holding or growing cash.
#       Losing 20%+ of starting cash => 0 pts.
#       Break-even (no change) => 20 pts (half marks for sound management).
#       Gaining 20% of starting cash => 40 pts (full marks).
#       Linear in between.
#   - Reputation (25 pts): rewards holding or growing reputation.
#       Holding flat (no change) => 10 pts (partial credit for not losing rep).
#       Gaining 10 reputation => 25 pts (full marks).
#       Losing rep scales down to 0 at -10 or worse.
#   - Project completions (25 pts): completed (not failed) over completable.
#       Realistic ceiling given 6 consultants and 4-6 week durations is 3-4 of 8.
#       3 completions = 25 pts; scales linearly below.
#   - Fatigue management (10 pts): only counted if at least 4 projects staffed.
#       Avoids gaming by leaving everyone on the bench.
#
# Process (out of 100):
#   - Constraint compliance (50 pts): per-violation penalty.
#       First violation is forgiven. Each violation after = -4 pts. Floor 0.
#   - Skill match (50 pts): only awarded based on weeks where the candidate
#       actually staffed projects. If never staffed, this is 0.
#       Average quality multiplier across staffed weeks * 50.

CASH_GAIN_FOR_FULL_MARKS_RATIO = 0.20   # gain = 20% of starting cash => full 40 pts
CASH_LOSS_FOR_ZERO_MARKS_RATIO = 0.20   # loss of 20% of starting cash => 0 pts
CASH_BREAK_EVEN_PTS = 20.0              # break-even => half marks
REPUTATION_TARGET_GAIN = 10             # +10 reputation => full 25 pts
REPUTATION_HOLD_PTS = 10.0              # holding rep flat => partial credit
REPUTATION_LOSS_FOR_ZERO = 10           # losing 10 rep => 0 pts
NEAR_PERFECT_COMPLETIONS = 3            # 3 of 8 completed => full 25 pts
MIN_STAFFED_PROJECTS_FOR_FATIGUE_BONUS = 4
VIOLATION_PENALTY = 4                   # per unique (project, issue) violation past the first
FORGIVEN_VIOLATIONS = 1                 # first N violations don't cost points (real firms aren't perfect)


def _outcome_score(state: dict, scenario: dict) -> Tuple[float, dict]:
    starting_cash = state.get("starting_cash", scenario["starting_state"]["cash"])
    starting_rep = state.get("starting_reputation", scenario["starting_state"]["reputation"])

    # Cash management: piecewise linear with partial credit for break-even.
    # -20% of starting => 0 pts, break-even => 20 pts, +20% => 40 pts.
    cash_gain = state["cash"] - starting_cash
    if starting_cash <= 0:
        cash_pts = 0.0
    elif cash_gain >= 0:
        target_gain = starting_cash * CASH_GAIN_FOR_FULL_MARKS_RATIO
        gain_ratio = cash_gain / target_gain if target_gain > 0 else 0
        cash_pts = CASH_BREAK_EVEN_PTS + min(1.0, gain_ratio) * (40.0 - CASH_BREAK_EVEN_PTS)
    else:
        loss_threshold = starting_cash * CASH_LOSS_FOR_ZERO_MARKS_RATIO
        loss_ratio = (-cash_gain) / loss_threshold if loss_threshold > 0 else 1.0
        cash_pts = max(0.0, CASH_BREAK_EVEN_PTS * (1.0 - min(1.0, loss_ratio)))

    # Reputation: partial credit for holding flat, full marks for +10.
    # -10 or worse => 0 pts, flat => 10 pts, +10 => 25 pts.
    rep_gain = state["reputation"] - starting_rep
    if rep_gain >= 0:
        gain_ratio = rep_gain / REPUTATION_TARGET_GAIN if REPUTATION_TARGET_GAIN > 0 else 0
        rep_pts = REPUTATION_HOLD_PTS + min(1.0, gain_ratio) * (25.0 - REPUTATION_HOLD_PTS)
    else:
        loss_ratio = (-rep_gain) / REPUTATION_LOSS_FOR_ZERO if REPUTATION_LOSS_FOR_ZERO > 0 else 1.0
        rep_pts = max(0.0, REPUTATION_HOLD_PTS * (1.0 - min(1.0, loss_ratio)))

    # Completions
    completed = sum(1 for ps in state["projects"].values() if ps["status"] == "completed")
    completion_pts = min(25.0, (completed / NEAR_PERFECT_COMPLETIONS) * 25.0)

    # Fatigue: only awarded if the candidate actually played
    projects_engaged = sum(1 for ps in state["projects"].values()
                            if ps["weeks_staffed_correctly"] > 0
                            or ps["status"] in ("completed", "active", "quality_failure", "cancelled", "missed_deadline"))
    if projects_engaged >= MIN_STAFFED_PROJECTS_FOR_FATIGUE_BONUS:
        avg_fatigue = sum(state["fatigue"].values()) / len(state["fatigue"]) if state["fatigue"] else 0
        fatigue_pts = ((100 - avg_fatigue) / 100.0) * 10.0
    else:
        fatigue_pts = 0.0

    breakdown = {
        "cash_pts": round(cash_pts, 2),
        "reputation_pts": round(rep_pts, 2),
        "completion_pts": round(completion_pts, 2),
        "fatigue_pts": round(fatigue_pts, 2),
    }
    total = cash_pts + rep_pts + completion_pts + fatigue_pts
    return round(min(100.0, max(0.0, total)), 2), breakdown


def _process_score(state: dict, scenario: dict) -> Tuple[float, dict]:
    # Dedupe violations: count each unique (project, issue) pair once even if it persists
    unique_violations: set = set()
    quality_samples: List[float] = []

    for week_log in state.get("weekly_log", []):
        for action in week_log.get("actions", []):
            quality_samples.append(action["quality_mult_this_week"])
            for issue in action.get("issues", []):
                unique_violations.add((action["project_id"], issue))

    violations = len(unique_violations)

    if not quality_samples:
        # Did nothing -> no process score (no actions = no compliance to grade)
        constraint_pts = 0.0
        skill_pts = 0.0
    else:
        chargeable = max(0, violations - FORGIVEN_VIOLATIONS)
        constraint_pts = max(0.0, 50.0 - (chargeable * VIOLATION_PENALTY))
        avg_quality = sum(quality_samples) / len(quality_samples)
        skill_pts = avg_quality * 50.0

    breakdown = {
        "constraint_pts": round(constraint_pts, 2),
        "skill_match_pts": round(skill_pts, 2),
        "violations": violations,
    }
    total = constraint_pts + skill_pts
    return round(min(100.0, max(0.0, total)), 2), breakdown


def final_layer2_score(state: dict, scenario: dict) -> dict:
    outcome, outcome_breakdown = _outcome_score(state, scenario)
    process, process_breakdown = _process_score(state, scenario)
    total = OUTCOME_WEIGHT * outcome + PROCESS_WEIGHT * process
    return {
        "layer2_total": round(total, 2),
        "outcome_score": outcome,
        "process_score": process,
        "outcome_breakdown": outcome_breakdown,
        "process_breakdown": process_breakdown,
    }


def aggregate_layer2(state: dict, scenario: dict) -> Tuple[float, dict]:
    """Return (layer2_total, competency_dict)."""
    result = final_layer2_score(state, scenario)
    layer_total = result["layer2_total"]

    # Strategic: anchored on outcome score (cash/reputation/completions reflect strategy)
    strategic = result["outcome_score"]

    # Adaptability: process quality (handling sick leave, mismatch recovery, fatigue mgmt)
    # blended with reputation (reputation reflects how well disruptions were absorbed)
    adaptability = result["process_score"] * 0.7 + min(state["reputation"], 100) * 0.3

    return layer_total, {
        "competency_strategic": round(strategic, 2),
        "competency_adaptability": round(min(100.0, adaptability), 2),
    }
