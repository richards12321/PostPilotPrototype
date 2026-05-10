"""Final scoring matrix.

Combines the three layer scores into an overall score, maps competencies,
and classifies top-fit candidates.

Top Fit is now a single rule: overall >= 70. The earlier multi-criteria
(no layer below 60, >=2 competencies >=75) was dropped in v7.
"""

from __future__ import annotations

from typing import Optional

LAYER1_WEIGHT = 0.30
LAYER2_WEIGHT = 0.35
LAYER3_WEIGHT = 0.35

TOP_FIT_MIN_OVERALL = 70


def overall_score(layer1: float, layer2: float, layer3: float) -> float:
    """Weighted sum of the three layer scores."""
    return round(
        LAYER1_WEIGHT * layer1 + LAYER2_WEIGHT * layer2 + LAYER3_WEIGHT * layer3,
        2,
    )


def classify_top_fit(
    overall: float,
    layer1: Optional[float] = None,
    layer2: Optional[float] = None,
    layer3: Optional[float] = None,
    competencies: Optional[dict] = None,
) -> int:
    """Returns 1 if top-fit, 0 otherwise.

    Single rule (v7): overall >= 70. Extra parameters are accepted for
    backward compatibility with callers that still pass layer scores and
    competencies, but they're ignored.
    """
    return 1 if overall >= TOP_FIT_MIN_OVERALL else 0


def assemble_final_scores(
    candidate_id: str,
    layer1: float,
    layer2: float,
    layer3: float,
    l1_comp: dict,
    l2_comp: dict,
    l3_comp: dict,
    candidate_feedback: str,
    recruiter_summary: str,
    ai_flags: Optional[dict] = None,
) -> dict:
    """Build the dict that goes into final_scores.

    ai_flags (optional) maps:
      ai_flag_logical, ai_flag_numerical, ai_flag_verbal, ai_flag_layer2
    to 0/1 ints. Missing keys default to 0.
    """
    overall = overall_score(layer1, layer2, layer3)
    top_fit = classify_top_fit(overall)
    flags = ai_flags or {}
    return {
        "candidate_id": candidate_id,
        "layer1_score": layer1,
        "layer2_score": layer2,
        "layer3_score": layer3,
        "overall_score": overall,
        "competency_analytical": l1_comp.get("competency_analytical"),
        "competency_numerical": l1_comp.get("competency_numerical"),
        "competency_verbal": l1_comp.get("competency_verbal"),
        "competency_strategic": l2_comp.get("competency_strategic"),
        "competency_adaptability": l2_comp.get("competency_adaptability"),
        "competency_l3_growth_mindset": l3_comp.get("competency_l3_growth_mindset"),
        "competency_l3_adaptability": l3_comp.get("competency_l3_adaptability"),
        "competency_l3_collaboration": l3_comp.get("competency_l3_collaboration"),
        "competency_l3_self_reflection": l3_comp.get("competency_l3_self_reflection"),
        "ai_flag_logical": int(bool(flags.get("ai_flag_logical", 0))),
        "ai_flag_numerical": int(bool(flags.get("ai_flag_numerical", 0))),
        "ai_flag_verbal": int(bool(flags.get("ai_flag_verbal", 0))),
        "ai_flag_layer2": int(bool(flags.get("ai_flag_layer2", 0))),
        "top_fit": top_fit,
        "recruiter_summary": recruiter_summary,
        "candidate_feedback": candidate_feedback,
    }
