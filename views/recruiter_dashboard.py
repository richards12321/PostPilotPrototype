"""Recruiter dashboard: overview table, filters, stats, and per-candidate deep-dive."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from database import db


# Filter widget keys (explicit so the Reset button can clear them).
FILTER_KEYS = [
    "recruiter_min_overall",
    "recruiter_min_l1",
    "recruiter_min_l2",
    "recruiter_min_l3",
    "recruiter_name_search",
    "recruiter_top_fit_only",
    "recruiter_date_range",
]


def _format_ai_flags(row: dict) -> str:
    """Build the 'Possible AI use' cell string from the four flag columns.

    Empty if no flags. Otherwise lists which Layer 1 themes tripped, plus
    whether Layer 2 tripped. Examples:
      ""
      "L1 verbal"
      "L1 logical+numerical, L2"
      "L2"
    """
    l1_themes = []
    if int(row.get("ai_flag_logical") or 0):
        l1_themes.append("logical")
    if int(row.get("ai_flag_numerical") or 0):
        l1_themes.append("numerical")
    if int(row.get("ai_flag_verbal") or 0):
        l1_themes.append("verbal")
    parts = []
    if l1_themes:
        parts.append("L1 " + "+".join(l1_themes))
    if int(row.get("ai_flag_layer2") or 0):
        parts.append("L2")
    return ", ".join(parts) if parts else "-"


def render() -> None:
    st.title("Recruiter Dashboard")
    st.caption("Review completed candidate assessments, filter by score, and export.")

    # --- Load data ---
    rows = db.get_all_completed_candidates()
    if not rows:
        st.info("No completed assessments yet. Candidates will appear here once they finish.")
        return

    df = pd.DataFrame(rows)
    df["completed_at_dt"] = pd.to_datetime(df["completed_at"])

    # --- Sidebar filters ---
    with st.sidebar:
        st.header("Filters")
        min_overall = st.slider(
            "Min overall score", 0, 100, 0, key="recruiter_min_overall",
        )
        min_l1 = st.slider(
            "Min Layer 1 score", 0, 100, 0, key="recruiter_min_l1",
        )
        min_l2 = st.slider(
            "Min Layer 2 score", 0, 100, 0, key="recruiter_min_l2",
        )
        min_l3 = st.slider(
            "Min Layer 3 score", 0, 100, 0, key="recruiter_min_l3",
        )

        if not df.empty:
            date_min = df["completed_at_dt"].min().date()
            date_max = df["completed_at_dt"].max().date()
            date_range = st.date_input(
                "Completed between",
                value=(date_min, date_max),
                min_value=date_min, max_value=date_max,
                key="recruiter_date_range",
            )
        else:
            date_range = None

        name_search = st.text_input(
            "Name contains", "", key="recruiter_name_search",
        )
        top_fit_only = st.checkbox(
            "Top Fit only", key="recruiter_top_fit_only",
        )

        if st.button("Reset filters"):
            for k in FILTER_KEYS:
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()

    # --- Apply filters ---
    filtered = df.copy()
    filtered = filtered[filtered["overall_score"] >= min_overall]
    filtered = filtered[filtered["layer1_score"] >= min_l1]
    filtered = filtered[filtered["layer2_score"] >= min_l2]
    filtered = filtered[filtered["layer3_score"] >= min_l3]
    if name_search:
        filtered = filtered[filtered["full_name"].str.contains(name_search, case=False, na=False)]
    if top_fit_only:
        filtered = filtered[filtered["top_fit"] == 1]
    if date_range and isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        filtered = filtered[
            (filtered["completed_at_dt"].dt.date >= start)
            & (filtered["completed_at_dt"].dt.date <= end)
        ]

    # --- Summary stats ---
    st.subheader("At a glance")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Candidates assessed", len(df))
    c2.metric("In current view", len(filtered))
    c3.metric("Top Fit (in view)", int(filtered["top_fit"].sum()))
    avg_score = filtered["overall_score"].mean() if len(filtered) > 0 else 0
    c4.metric("Avg overall (in view)", f"{avg_score:.1f}")

    # Score distribution histogram
    if len(filtered) > 0:
        hist = px.histogram(
            filtered, x="overall_score", nbins=20,
            title="Overall score distribution",
            labels={"overall_score": "Overall score"},
        )
        hist.update_layout(height=280, margin=dict(t=40, b=20))
        st.plotly_chart(hist, use_container_width=True)

    st.divider()

    # --- Overview table ---
    st.subheader("Candidates")
    table_rows = []
    for _, row in filtered.iterrows():
        table_rows.append({
            "Name": row["full_name"],
            "Email": row["email"],
            "Completed": pd.to_datetime(row["completed_at"]).strftime("%Y-%m-%d %H:%M"),
            "Layer 1": round(float(row["layer1_score"] or 0), 1),
            "Layer 2": round(float(row["layer2_score"] or 0), 1),
            "Layer 3": round(float(row["layer3_score"] or 0), 1),
            "Overall": round(float(row["overall_score"] or 0), 1),
            "Possible AI use": _format_ai_flags(row.to_dict()),
            "Top Fit": "✓" if row["top_fit"] == 1 else "-",
        })
    display_df = pd.DataFrame(table_rows, columns=[
        "Name", "Email", "Completed", "Layer 1", "Layer 2", "Layer 3",
        "Overall", "Possible AI use", "Top Fit",
    ])

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        height=350,
    )

    # --- Export ---
    if len(filtered) > 0:
        csv = filtered.drop(columns=["completed_at_dt"]).to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Export filtered candidates to CSV",
            data=csv,
            file_name=f"candidates_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

    st.divider()

    # --- Individual deep-dive ---
    st.subheader("Individual deep-dive")
    if len(filtered) == 0:
        st.info("No candidates match the current filters.")
        return

    options = {
        f"{row['full_name']} ({row['email']}): Overall {row['overall_score']:.0f}": row["candidate_id"]
        for _, row in filtered.iterrows()
    }
    chosen_label = st.selectbox("Select a candidate", options=list(options.keys()))
    chosen_id = options[chosen_label]

    _render_deep_dive(chosen_id)


def _render_deep_dive(candidate_id: str) -> None:
    candidate = db.get_candidate(candidate_id)
    scores = db.get_final_score(candidate_id)
    if not candidate or not scores:
        st.error("Candidate data not found.")
        return

    st.markdown(f"### {candidate['full_name']}")
    st.caption(
        f"{candidate['email']} · Started {candidate['started_at'][:10]} · "
        f"Completed {candidate['completed_at'][:10] if candidate['completed_at'] else '-'}"
    )

    # Top Fit badge (v7: single rule, overall >= 70)
    if scores["top_fit"]:
        st.success("✓ **Top Fit**: Overall score ≥ 70")
    else:
        st.warning("Not flagged as Top Fit")

    # Score summary
    cols = st.columns(4)
    cols[0].metric("Overall", f"{scores['overall_score']:.1f}")
    cols[1].metric("Layer 1", f"{scores['layer1_score']:.1f}")
    cols[2].metric("Layer 2", f"{scores['layer2_score']:.1f}")
    cols[3].metric("Layer 3", f"{scores['layer3_score']:.1f}")

    # Possible AI use chip
    flags_str = _format_ai_flags(scores)
    if flags_str and flags_str != "-":
        st.warning(f"⚠️ Possible AI use flagged: **{flags_str}**  (informational only)")

    # Competency radar (v7: 4 L3 axes)
    comp_labels = [
        "Analytical", "Numerical", "Verbal",
        "Strategic", "Adaptability (sim)",
        "Growth Mindset", "Adaptability (interview)",
        "Collaboration", "Self-Reflection",
    ]
    comp_values = [
        scores.get("competency_analytical") or 0,
        scores.get("competency_numerical") or 0,
        scores.get("competency_verbal") or 0,
        scores.get("competency_strategic") or 0,
        scores.get("competency_adaptability") or 0,
        scores.get("competency_l3_growth_mindset") or 0,
        scores.get("competency_l3_adaptability") or 0,
        scores.get("competency_l3_collaboration") or 0,
        scores.get("competency_l3_self_reflection") or 0,
    ]
    radar = go.Figure()
    radar.add_trace(go.Scatterpolar(
        r=comp_values + [comp_values[0]],
        theta=comp_labels + [comp_labels[0]],
        fill="toself",
        line_color="#6366F1",
    ))
    radar.update_layout(
        polar=dict(radialaxis=dict(range=[0, 100], visible=True)),
        showlegend=False, height=380, margin=dict(t=20, b=20),
    )
    st.plotly_chart(radar, use_container_width=True)

    # Recruiter summary (LLM-generated)
    st.markdown("#### Recruiter summary")
    if scores.get("recruiter_summary"):
        st.markdown(scores["recruiter_summary"])
    else:
        st.info("No recruiter summary generated yet.")

    # Layer 1 detail
    with st.expander("Layer 1: Question-by-question detail"):
        l1_rows = db.get_layer1_results(candidate_id)
        if l1_rows:
            df1 = pd.DataFrame([{
                "Theme": r["theme"],
                "Question ID": r["question_id"],
                "Question": (r["question_text"] or "")[:80] + "...",
                "Candidate's Answer": r["candidate_answer"] or "-",
                "Correct": r["correct_option"],
                "✓": "✓" if r["is_correct"] else "✗",
                "Time (s)": r["time_taken_seconds"],
            } for r in l1_rows])
            st.dataframe(df1, use_container_width=True, hide_index=True)
        else:
            st.write("No Layer 1 data.")

    # Layer 2 detail
    with st.expander("Layer 2: Firm simulation detail"):
        l2_sim = db.get_layer2_simulation(candidate_id)
        if not l2_sim:
            st.write("No Layer 2 data.")
        else:
            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("Outcome score", f"{l2_sim['outcome_score']:.0f}")
            sc2.metric("Process score", f"{l2_sim['process_score']:.0f}")
            sc3.metric("Layer 2 total", f"{l2_sim['layer2_total']:.0f}")
            sc4.metric("Weeks played", l2_sim['weeks_played'])

            kc1, kc2, kc3, kc4 = st.columns(4)
            kc1.metric("Final cash", f"€{l2_sim['final_cash']:,.0f}")
            kc2.metric("Final reputation", f"{l2_sim['final_reputation']:.0f}/100")
            kc3.metric("Projects completed", l2_sim["projects_completed"])
            kc4.metric("Projects failed", l2_sim["projects_cancelled"])

            if l2_sim.get("tradeoff_choice"):
                st.markdown(f"**Week 6 trade-off:** Option **{l2_sim['tradeoff_choice']}**")
            else:
                st.markdown("*No trade-off decision recorded (didn't reach Week 6 or didn't choose).*")

            try:
                final_state = json.loads(l2_sim["final_state_json"])
                decisions = final_state.get("decision_choices", {})
                for did, choice in decisions.items():
                    st.markdown(f"**Week 2 decision ({did}):** chose **{choice}**")
            except (json.JSONDecodeError, TypeError, KeyError):
                pass

            st.markdown("**Week-by-week log:**")
            try:
                weekly_log = json.loads(l2_sim["weekly_log_json"])
            except (json.JSONDecodeError, TypeError):
                weekly_log = []

            for log in weekly_log:
                st.markdown(f"---\n**Week {log.get('week', '?')}**")
                cc1, cc2 = st.columns(2)
                cc1.markdown(f"*Cash change:* €{log.get('cash_change', 0):,.0f}")
                cc2.markdown(f"*Reputation change:* {log.get('reputation_change', 0):+d}")

                if log.get("events_fired"):
                    for ev in log["events_fired"]:
                        st.markdown(f"- 📢 {ev}")
                if log.get("tradeoff_choice"):
                    st.markdown(f"- 🎯 Trade-off chosen: **{log['tradeoff_choice']}**")
                if log.get("decision"):
                    decision_info = log["decision"]
                    st.markdown(
                        f"- 📋 Decision: **{decision_info.get('decision_id')}** -> "
                        f"option **{decision_info.get('choice_id')}**"
                    )
                if log.get("actions"):
                    for a in log["actions"]:
                        issues = f" ⚠️ {' / '.join(a['issues'])}" if a.get("issues") else ""
                        st.markdown(
                            f"- **{a['project_id']}** <- {', '.join(a['consultant_ids']) or '-'} "
                            f"(burn €{a['burn']:,}, quality {a['quality_mult_this_week']:.2f}){issues}"
                        )
                if log.get("completions"):
                    st.markdown(f"- ✅ Completed: {', '.join(log['completions'])}")
                if log.get("quality_failures"):
                    st.markdown(f"- ⚠️ Quality failure: {', '.join(log['quality_failures'])}")
                if log.get("cancellations"):
                    st.markdown(f"- ❌ Cancelled: {', '.join(log['cancellations'])}")
                if log.get("missed_deadlines"):
                    st.markdown(f"- ⏰ Missed deadline: {', '.join(log['missed_deadlines'])}")

    # Layer 3 detail
    with st.expander("Layer 3: Interview transcripts"):
        l3_rows = db.get_layer3_results(candidate_id)
        if not l3_rows:
            st.write("No Layer 3 data.")
        bucket_names = {
            "A": "GET SPECIFIC", "B": "GET EVIDENCE",
            "C": "GET REASONING", "D": "GET REFLECTION",
        }
        for r in l3_rows:
            header = (
                f"**Competency {r['competency_order']}: "
                f"{r['competency_id']}: {r['competency_name']}**"
            )
            if r.get("scripted_flag"):
                header += "  🚩 *flagged: possibly scripted*"
            st.markdown(header)

            score = r.get("competency_score")
            if score is not None:
                st.metric("Score (0-25)", f"{score}")
            if r.get("rationale"):
                st.caption(f"Scoring rationale: {r['rationale']}")

            st.markdown(f"*Main question:* {r['main_question']}")
            st.markdown(f"*Main answer:* > {r['main_transcript'] or '(no answer)'}")

            if r.get("followup_question"):
                bucket = r.get("followup_bucket")
                bucket_label = f" [{bucket_names.get(bucket, bucket)}]" if bucket else ""
                st.markdown(f"*Follow-up{bucket_label}:* {r['followup_question']}")
                st.markdown(f"*Follow-up answer:* > {r.get('followup_transcript') or '(no answer)'}")

            st.markdown("---")

    # Logout
    st.divider()
    if st.button("Log out"):
        st.session_state.mode = None
        st.session_state.recruiter_authed = False
        st.session_state.stage = "landing"
        st.rerun()
