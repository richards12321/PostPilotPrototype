"""Layer 2 view: 8-week firm simulation.

Single big 20-minute timer. Each week, the candidate sees the firm dashboard
(cash, reputation, fatigue, project board), assigns consultants to projects,
and clicks 'Advance to next week.' At Week 6, a trade-off modal interrupts.

No scoring is shown to the candidate during play. Only at the very end
(after Layer 3) are full results revealed.
"""

from __future__ import annotations

import time

import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

from assessment_logic.layer2_logic import (
    LAYER_TIME_LIMIT_SECONDS,
    advance_week,
    aggregate_layer2,
    consultants_available_in_week,
    events_for_week,
    final_layer2_score,
    initial_state,
    is_simulation_complete,
    load_scenario,
    pending_decision_for_week,
    projects_visible_in_week,
    validate_weekly_assignments,
)
from database import db

from .state import advance_stage


def render() -> None:
    if not st.session_state.get("l2_started", False):
        _intro()
        return

    scenario = load_scenario()

    if "l2_state" not in st.session_state or st.session_state.l2_state is None:
        st.session_state.l2_state = initial_state(scenario)
        st.session_state.l2_started_at = time.time()

    state = st.session_state.l2_state

    # Time check (single big timer)
    elapsed = time.time() - (st.session_state.l2_started_at or time.time())
    remaining = max(0, int(LAYER_TIME_LIMIT_SECONDS - elapsed))
    timed_out = remaining <= 0

    # End-of-game conditions: simulation complete OR time up
    if is_simulation_complete(state):
        _finalize_and_advance(scenario, state, int(elapsed))
        return

    if timed_out:
        st.warning("⏰ Time's up. Auto-advancing remaining weeks with no new staffing.")
        # auto-advance through remaining weeks with empty assignments
        while not is_simulation_complete(state):
            state = advance_week(scenario, state, weekly_assignments={}, tradeoff_choice=None)
        st.session_state.l2_state = state
        _finalize_and_advance(scenario, state, int(elapsed))
        return

    # Otherwise render the current week
    _render_week(scenario, state, remaining, elapsed)


def _intro() -> None:
    st.title("Layer 2: Firm Simulation")
    st.markdown(
        """
        ### The setup
        You're the resource lead at a consulting firm with **6 consultants** and a starting
        cash balance of **€500,000**. Over the next **8 simulated weeks**, you'll decide
        who works on which project, respond to events, and try to keep the firm in good
        shape, both financially and reputationally.

        Each week you'll see your firm dashboard, the active project board, and your
        consultants' current state. You assign people to projects, then click
        **Advance to next week**. Time, cash, fatigue, and reputation all carry forward.

        ### How you're judged
        Your performance is scored on two things: outcomes (70%) and process (30%).

        **Outcomes (what you actually achieved):**
        - **Cash management**: did you protect the firm's money or burn through it?
          Holding cash flat earns partial credit; growing it earns full marks.
        - **Reputation**: starts at 60. Holding it steady is solid; gaining
          reputation is excellent. Losing it through cancellations and missed deadlines
          will cost you.
        - **Project completions**: projects only count if they finish properly.
          Quality failures and missed deadlines don't count.
        - **Consultant fatigue**: keeping the team from burning out matters.

        **Process (how well you ran it):**
        - **Constraint compliance**: did you respect skill and seniority requirements?
        - **Skill match quality**: staffing the wrong people on a project lowers
          its quality multiplier and shrinks the revenue when it completes.

        ### What to prioritize
        - **Match skills and seniority before anything else.** A skill mismatch
          cuts that project's quality to 55%. A seniority mismatch cuts it to 65%.
          These stack. A badly-staffed project pays a fraction of its revenue.
        - **Use the smallest viable team.** Adding more people doesn't speed projects
          up or improve quality past 100%. Extra bodies just leave other projects
          unstaffed.
        - **Don't let projects sit idle.** Two consecutive unstaffed weeks
          and the project gets cancelled with a -15 reputation hit.
        - **Watch deadlines.** Missing one costs -8 reputation and the project pays nothing.
        - **Plan around fatigue.** A consultant staffed every week hits high fatigue
          (≥70) and starts dragging quality down. Rotate the bench.

        ### What to look out for
        - **Two binding decisions** will interrupt the game. You can't advance until
          you choose. Read the options carefully because they have lasting effects on
          cash, reputation, and your team.
        - **Sick leave, budget cuts, and new project arrivals** will happen mid-game.
          You'll need to adapt your staffing on the fly.
        - **New projects arrive in later weeks.** Some have very short windows
          (a 2-week project arriving in week 7, for example). You may need to
          free people up to chase them.

        ### The clock
        You have **20 minutes total** to play through all 8 weeks. The timer runs
        continuously. There's no per-week limit. If time runs out, remaining weeks
        auto-advance with no new staffing, which usually goes badly.

        Think long. A decision in Week 2 will shape what's possible in Week 6.
        """
    )

    if st.button("Begin Layer 2", type="primary", use_container_width=True):
        st.session_state.l2_started = True
        st.session_state.l2_state = None
        st.session_state.l2_started_at = time.time()
        st.rerun()


def _render_week(scenario: dict, state: dict, remaining: int, elapsed: float) -> None:
    # Scroll to top if we just advanced a week. The script keeps retrying via
    # requestAnimationFrame for up to ~1.5s because on Streamlit Cloud the page
    # finishes painting after our injected iframe loads, so a single scroll call
    # often misses. We also target every plausible scroll container, Streamlit
    # has changed which one actually scrolls between versions.
    if st.session_state.pop("_scroll_top_needed", False):
        components.html(
            """
            <script>
                (function () {
                    const startedAt = Date.now();
                    const scrollAll = () => {
                        try {
                            const doc = window.parent.document;
                            const targets = [
                                doc.querySelector('section.main'),
                                doc.querySelector('[data-testid="stAppViewContainer"]'),
                                doc.querySelector('[data-testid="stMain"]'),
                                doc.querySelector('main'),
                                doc.scrollingElement,
                                doc.documentElement,
                                doc.body,
                            ].filter(Boolean);
                            targets.forEach(el => { el.scrollTop = 0; });
                            window.parent.scrollTo(0, 0);
                            // also nudge the hash to force layout
                            if (doc.getElementById('week-top')) {
                                doc.getElementById('week-top').scrollIntoView({block: 'start'});
                            }
                        } catch (e) { /* cross-frame edge cases */ }
                    };
                    // run immediately, then keep retrying for ~1.5s
                    scrollAll();
                    const tick = () => {
                        scrollAll();
                        if (Date.now() - startedAt < 1500) {
                            requestAnimationFrame(tick);
                        }
                    };
                    requestAnimationFrame(tick);
                })();
            </script>
            """,
            height=0,
        )

    # Anchor at the very top of the week content, used by the scroll script.
    st.markdown('<div id="week-top"></div>', unsafe_allow_html=True)

    # Tick down the timer every second
    st_autorefresh(interval=1000, key=f"l2_tick_{state['current_week']}")

    week = state["current_week"]
    total = state["total_weeks"]

    # Header
    mins, secs = divmod(remaining, 60)
    h1, h2 = st.columns([3, 1])
    with h1:
        st.markdown(f"### Week {week} of {total}")
        st.progress((week - 1) / total)
    with h2:
        color = "🟢" if remaining > 300 else ("🟡" if remaining > 60 else "🔴")
        st.metric("Time remaining", f"{color} {mins:02d}:{secs:02d}")

    # Firm KPI strip
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Cash", f"€{state['cash']:,.0f}")
    k2.metric("Reputation", f"{state['reputation']:.0f}/100")
    completed = sum(1 for ps in state["projects"].values() if ps["status"] == "completed")
    failed = sum(1 for ps in state["projects"].values() if ps["status"] in ("cancelled", "quality_failure", "missed_deadline"))
    k3.metric("Projects done", completed)
    k4.metric("Projects failed", failed)

    # Events firing this week
    events = events_for_week(scenario, week)
    for ev in events:
        if ev["type"] == "sick_leave":
            st.warning(f"🤒 {ev['message']}")
        elif ev["type"] == "budget_cut":
            st.warning(f"💸 {ev['message']}")
        elif ev["type"] == "new_project_alert":
            st.info(f"📨 {ev['message']}")
        elif ev["type"] == "tradeoff":
            st.error(f"⚠️ {ev['message']}")

    st.divider()

    # Week 2 decision modal (David resigns), must be made before advancing
    decision_choice_tuple = None
    pending = pending_decision_for_week(scenario, state, week)
    if pending is not None:
        decision_choice_tuple = _render_decision(pending, scenario)
        if decision_choice_tuple is None:
            st.stop()

    # Trade-off modal in Week 6
    tradeoff_choice = None
    is_tradeoff_week = any(ev["type"] == "tradeoff" for ev in events)
    if is_tradeoff_week:
        tradeoff_choice = _render_tradeoff(scenario)
        if tradeoff_choice is None:
            st.stop()

    # Two-column main view: consultants + projects
    left, right = st.columns([1, 1])

    with left:
        st.subheader("Your team")
        available = consultants_available_in_week(scenario, state, week)
        available_ids = {c["id"] for c in available}
        departed_ids = set(state.get("consultants_departed_at_week", {}).keys())
        for c in scenario["consultants"]:
            fatigue = state["fatigue"].get(c["id"], 0)
            sick = c["id"] not in available_ids and c["id"] not in departed_ids
            departed = c["id"] in departed_ids and c["id"] not in available_ids
            tag = ""
            if departed:
                tag = " ❌ *no longer with the firm*"
            elif sick:
                tag = " 🤒 *sick this week*"
            fatigue_color = "🟢" if fatigue < 40 else ("🟡" if fatigue < 70 else "🔴")
            st.markdown(
                f"**{c['name']}** ({c['id']}), {c['seniority']}{tag}  \n"
                f"Skills: {', '.join(c['skills'])}  \n"
                f"Fatigue: {fatigue_color} {fatigue}/100"
            )

    with right:
        st.subheader("Active projects")
        visible_projects = projects_visible_in_week(scenario, state, week)
        if not visible_projects:
            st.info("No active projects this week.")
        for p in visible_projects:
            ps = state["projects"][p["id"]]
            tier_emoji = {"A": "🔴", "B": "🟡", "C": "⚪"}.get(p.get("priority_tier"), "⚪")
            urgent_tag = " 🚨 URGENT" if p.get("urgent") else ""
            progress = ps["weeks_staffed_correctly"]
            duration = p["duration_weeks"]
            revenue = p.get("revenue", 0)
            revenue_str = f"€{revenue:,}" if revenue else "Strategic (no revenue)"

            status_str = ""
            if ps["status"] == "active":
                status_str = f" · ▶️ {progress}/{duration} weeks done"
            elif ps["status"] == "available":
                status_str = " · 🆕 Not started"

            st.markdown(
                f"{tier_emoji} **{p['name']}** ({p['id']}){urgent_tag}{status_str}  \n"
                f"Skills: {', '.join(p.get('required_skills', []))} · Min. seniority: {p.get('min_seniority')}  \n"
                f"Burn: €{p['weekly_burn']:,}/wk · Revenue: {revenue_str} · Deadline: Week {p.get('deadline_week', total)}"
            )

    st.divider()

    # Assignment widget: multiselect per visible project
    st.subheader("Staff projects this week")
    st.caption("Each consultant can be on at most one project per week.")

    consultant_label = {c["id"]: f"{c['name']} ({c['id']}, {c['seniority']})"
                        for c in available}

    assignments_key = f"l2_week_{week}_assignments"
    if assignments_key not in st.session_state:
        # carry forward last week's assignments as defaults (continuity)
        prev_week = week - 1
        prev_assignments = state["weekly_assignments_history"].get(str(prev_week), {})
        # filter out finished projects and unavailable consultants
        visible_pids = {p["id"] for p in visible_projects}
        carried = {
            pid: [cid for cid in cids if cid in consultant_label]
            for pid, cids in prev_assignments.items()
            if pid in visible_pids
        }
        for pid in visible_pids:
            if pid not in carried:
                carried[pid] = []
        st.session_state[assignments_key] = carried

    assignments = st.session_state[assignments_key]
    new_assignments = {}
    for project in visible_projects:
        pid = project["id"]
        current = [cid for cid in assignments.get(pid, []) if cid in consultant_label]
        chosen = st.multiselect(
            f"**{project['name']}** ({pid})",
            options=list(consultant_label.keys()),
            default=current,
            format_func=lambda cid: consultant_label[cid],
            key=f"l2_assign_w{week}_{pid}",
        )
        new_assignments[pid] = chosen
    st.session_state[assignments_key] = new_assignments

    # Validation warnings (live, doesn't block)
    warnings = validate_weekly_assignments(scenario, state, week, new_assignments)
    for w in warnings:
        st.warning(f"⚠️ {w}")

    st.divider()

    # Recent activity
    if state.get("weekly_log"):
        with st.expander("📜 Recent weeks log", expanded=False):
            for log in state["weekly_log"][-3:]:
                _render_log_entry(log, scenario)

    # Advance button
    advance_label = (
        f"Advance to Week {week + 1}" if week < total else "Finish Layer 2"
    )
    if st.button(advance_label, type="primary", use_container_width=True):
        new_state = advance_week(
            scenario, state, new_assignments,
            tradeoff_choice=tradeoff_choice,
            decision_choice=decision_choice_tuple,
        )
        st.session_state.l2_state = new_state
        # clear the prepared assignments key so the next week picks up via prev_assignments carry-forward
        if assignments_key in st.session_state:
            del st.session_state[assignments_key]
        # signal scroll-to-top on next render
        st.session_state["_scroll_top_needed"] = True
        st.rerun()


def _render_decision(decision: dict, scenario: dict) -> tuple[str, str] | None:
    """Render a one-off decision modal. Returns (decision_id, choice_id) or None."""
    st.markdown("### 📋 Decision required")
    st.warning(decision["description"])

    option_labels = [f"**{opt['id'].replace('_', ' ').title()}**, {opt['label']}"
                     for opt in decision["options"]]
    choice_display = st.radio(
        "Pick one:",
        options=option_labels,
        key=f"l2_decision_{decision.get('id', 'x')}",
        index=None,
    )
    if choice_display is None:
        st.info("You must make this decision before continuing the week.")
        return None
    chosen = decision["options"][option_labels.index(choice_display)]
    # find the decision_id by looking it up in scenario['decisions']
    decision_id = None
    for did, d in scenario.get("decisions", {}).items():
        if d == decision:
            decision_id = did
            break
    if decision_id is None:
        # fallback: use the consultant_id as a key (for our single decision case)
        decision_id = next(iter(scenario.get("decisions", {})), None)
    return (decision_id, chosen["id"])


def _render_tradeoff(scenario: dict) -> str | None:
    """Render the Week 6 trade-off modal. Returns the choice id or None if not chosen yet."""
    tradeoff = scenario["tradeoff"]
    st.markdown("### ⚠️ Trade-off decision")
    st.error(tradeoff["description"])

    option_labels = [f"**{opt['id']}**, {opt['label']}" for opt in tradeoff["options"]]
    choice_display = st.radio(
        "Choose one option:",
        options=option_labels,
        key="l2_tradeoff_radio",
        index=None,
    )
    if choice_display is None:
        st.info("You must make this decision before continuing the week.")
        return None
    return tradeoff["options"][option_labels.index(choice_display)]["id"]


def _render_log_entry(log: dict, scenario: dict) -> None:
    """Render one week's log entry."""
    project_names = {p["id"]: p["name"] for p in scenario["projects"]}
    st.markdown(f"**Week {log['week']}**")
    if log.get("events_fired"):
        for ev in log["events_fired"]:
            st.markdown(f"- 📢 {ev}")
    if log.get("tradeoff_choice"):
        st.markdown(f"- 🎯 Trade-off: chose option **{log['tradeoff_choice']}**")
    if log.get("completions"):
        names = [project_names.get(pid, pid) for pid in log["completions"]]
        st.markdown(f"- ✅ Completed: {', '.join(names)}")
    if log.get("quality_failures"):
        names = [project_names.get(pid, pid) for pid in log["quality_failures"]]
        st.markdown(f"- ⚠️ Quality failure: {', '.join(names)}")
    if log.get("cancellations"):
        names = [project_names.get(pid, pid) for pid in log["cancellations"]]
        st.markdown(f"- ❌ Cancelled (unstaffed too long): {', '.join(names)}")
    if log.get("missed_deadlines"):
        names = [project_names.get(pid, pid) for pid in log["missed_deadlines"]]
        st.markdown(f"- ⏰ Missed deadline: {', '.join(names)}")


def _finalize_and_advance(scenario: dict, state: dict, elapsed: int) -> None:
    """Persist the simulation result and move to Layer 3 with no score reveal."""
    if db.has_layer2_simulation(st.session_state.candidate_id):
        # already saved (resume case); just move on
        advance_stage("layer3")
        return

    result = final_layer2_score(state, scenario)
    completed = sum(1 for ps in state["projects"].values() if ps["status"] == "completed")
    cancelled = sum(1 for ps in state["projects"].values()
                    if ps["status"] in ("cancelled", "quality_failure", "missed_deadline"))

    # AI-use flag: high score on Layer 2 AND finished in <= 35% of the time
    # limit (i.e. <= 7 minutes of the 20). Informational only.
    layer2_total = result["layer2_total"]
    fast_threshold = int(LAYER_TIME_LIMIT_SECONDS * 0.35)
    ai_flag_layer2 = (layer2_total >= 80) and (elapsed <= fast_threshold)
    st.session_state["l2_ai_flag"] = bool(ai_flag_layer2)

    db.save_layer2_simulation(
        candidate_id=st.session_state.candidate_id,
        final_state=state,
        weekly_log=state.get("weekly_log", []),
        weeks_played=min(state["current_week"] - 1, state["total_weeks"]),
        final_cash=state["cash"],
        final_reputation=state["reputation"],
        projects_completed=completed,
        projects_cancelled=cancelled,
        tradeoff_choice=state.get("tradeoff_choice"),
        outcome_score=result["outcome_score"],
        process_score=result["process_score"],
        layer2_total=result["layer2_total"],
        time_taken_seconds=elapsed,
    )

    st.title("Layer 2 Complete")
    st.success(
        "You've finished the firm simulation. Moving on to the final layer: "
        "the AI-led interview."
    )
    st.markdown(
        """
        **Next: Layer 3 (AI-Led Interview)**
        
        Four questions, each with a follow-up. Each answer is voice-recorded,
        transcribed, and scored on clarity, structure, relevance, and depth.
        
        Make sure your microphone is working and that you're in a quiet space.
        Your full results will be shown after this final layer.
        """
    )

    if st.button("Begin Layer 3", type="primary", use_container_width=True):
        advance_stage("layer3")
