"""Feedback generator: candidate-facing + recruiter-facing summaries."""

from __future__ import annotations

from .llm_client import chat_complete

CANDIDATE_PROMPT = """You are providing developmental feedback to a consulting candidate who just completed an assessment. Be constructive, specific, and professional. Do NOT mention whether they would be hired. Focus on growth.

Their scores (0-100):
- Overall: {overall}
- Layer 1 (Cognitive): {layer1} (Logical: {analytical}, Numerical: {numerical}, Verbal: {verbal})
- Layer 2 (Staffing Simulation): {layer2} (Strategic: {strategic}, Adaptability: {adaptability})
- Layer 3 (Interview): {layer3}
    - Growth Mindset: {growth_mindset}
    - Adaptability: {l3_adaptability}
    - Collaboration: {collaboration}
    - Self-Reflection: {self_reflection}

Produce feedback with three sections:
1. STRENGTHS: 2-3 bullet points on their top-performing competencies, with specific observations.
2. DEVELOPMENT AREAS: 2-3 bullet points on the weakest competencies, with actionable suggestions.
3. OVERALL OBSERVATION: A short paragraph (3-4 sentences) giving a balanced perspective.

Use plain, professional language. No jargon. Return as markdown."""

RECRUITER_PROMPT = """You are summarizing a candidate's assessment for a hiring recruiter. Be direct, evidence-based, and decision-oriented.

Scores (0-100):
- Overall: {overall}
- Layer 1 (Cognitive): {layer1} (Logical: {analytical}, Numerical: {numerical}, Verbal: {verbal})
- Layer 2 (Staffing Simulation): {layer2} (Strategic: {strategic}, Adaptability: {adaptability})
- Layer 3 (Interview): {layer3}
    - Growth Mindset: {growth_mindset}
    - Adaptability: {l3_adaptability}
    - Collaboration: {collaboration}
    - Self-Reflection: {self_reflection}
Top Fit flag: {top_fit_label}

Produce:
1. ONE-LINE VERDICT (e.g., "Strong candidate with standout strategic reasoning, some gaps in numerical fluency.")
2. KEY STRENGTHS (2 bullets)
3. KEY CONCERNS (2 bullets)
4. RECOMMENDED NEXT STEP: Choose one of [Strong Hire, Hire, Borderline (Additional Interview), No Hire] with a one-sentence rationale.

Return as markdown."""


def _format_args(scores: dict) -> dict:
    return dict(
        overall=scores["overall_score"],
        layer1=scores["layer1_score"],
        layer2=scores["layer2_score"],
        layer3=scores["layer3_score"],
        analytical=scores.get("competency_analytical", 0),
        numerical=scores.get("competency_numerical", 0),
        verbal=scores.get("competency_verbal", 0),
        strategic=scores.get("competency_strategic", 0),
        adaptability=scores.get("competency_adaptability", 0),
        growth_mindset=scores.get("competency_l3_growth_mindset", 0),
        l3_adaptability=scores.get("competency_l3_adaptability", 0),
        collaboration=scores.get("competency_l3_collaboration", 0),
        self_reflection=scores.get("competency_l3_self_reflection", 0),
    )


def _rule_based_candidate_feedback(scores: dict) -> str:
    """Deterministic feedback used when the AI call fails.

    Generates a real, useful summary from the scores rather than a generic
    'we had a problem' message. Uses simple thresholds to identify top and
    bottom competencies and writes a short narrative.
    """
    competencies = {
        "Logical reasoning": scores.get("competency_analytical", 0) or 0,
        "Numerical reasoning": scores.get("competency_numerical", 0) or 0,
        "Verbal reasoning": scores.get("competency_verbal", 0) or 0,
        "Strategic thinking": scores.get("competency_strategic", 0) or 0,
        "Adaptability under pressure": scores.get("competency_adaptability", 0) or 0,
        "Growth mindset": scores.get("competency_l3_growth_mindset", 0) or 0,
        "Adaptability (interview)": scores.get("competency_l3_adaptability", 0) or 0,
        "Collaboration": scores.get("competency_l3_collaboration", 0) or 0,
        "Self-reflection": scores.get("competency_l3_self_reflection", 0) or 0,
    }
    ranked = sorted(competencies.items(), key=lambda kv: kv[1], reverse=True)
    top = [name for name, score in ranked[:3] if score >= 60]
    bottom = [name for name, score in ranked[-3:] if score < 60]

    overall = scores.get("overall_score", 0) or 0
    if overall >= 75:
        overall_line = (
            "Overall, you performed strongly across the assessment, with results that "
            "place you in the upper tier of candidates we typically see."
        )
    elif overall >= 60:
        overall_line = (
            "Overall, you delivered a solid performance with a balanced profile across "
            "cognitive, simulation, and interview components."
        )
    elif overall >= 45:
        overall_line = (
            "Overall, your results show a mixed profile with clear strengths in some "
            "areas and room to grow in others."
        )
    else:
        overall_line = (
            "Overall, this assessment surfaced several areas where focused practice "
            "would meaningfully improve your performance next time."
        )

    parts = ["## Your developmental feedback", "", overall_line, ""]

    if top:
        parts.append("### Strengths")
        for name in top:
            parts.append(f"- **{name}**: your score here was among your highest, "
                         f"suggesting this is a real area of strength to lean on.")
        parts.append("")

    if bottom:
        parts.append("### Development areas")
        for name in bottom:
            parts.append(f"- **{name}**: this scored below average for you. "
                         f"Targeted practice in this area would lift your overall profile.")
        parts.append("")

    parts.append(
        "Your full results have been recorded and will be reviewed by the recruitment "
        "team. Treat this feedback as a snapshot of one assessment, not a verdict on "
        "your potential."
    )
    return "\n".join(parts)


def generate_candidate_feedback(scores: dict) -> str:
    prompt = CANDIDATE_PROMPT.format(**_format_args(scores))
    try:
        return chat_complete(prompt, temperature=0.3, max_tokens=600)
    except Exception as e:
        # AI call failed (most often Azure DeploymentNotFound). Fall back to
        # a real rule-based summary so the candidate still sees useful feedback.
        # Append a small italicised note so we can spot config issues in review.
        fallback = _rule_based_candidate_feedback(scores)
        return f"{fallback}\n\n*Note for recruiter: AI feedback unavailable ({type(e).__name__}); rule-based summary shown.*"


def generate_recruiter_summary(scores: dict) -> str:
    args = _format_args(scores)
    args["top_fit_label"] = "Yes" if scores.get("top_fit") else "No"
    prompt = RECRUITER_PROMPT.format(**args)
    try:
        return chat_complete(prompt, temperature=0.0, max_tokens=500)
    except Exception as e:
        return f"*Recruiter summary generation failed: {type(e).__name__}*"
