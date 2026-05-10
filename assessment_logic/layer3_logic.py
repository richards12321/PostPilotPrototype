"""Layer 3 logic: AI-led structured behavioral interview.

Scores 5 competencies (A10, A1, A12, A6, A15) on a 0-20 scale, summing
to a Layer 3 total of 0-100. One question per competency (randomly
chosen from a bank of 5), one targeted follow-up per question.

Question selection is seeded by candidate_id for reproducibility.
LLM-driven follow-up generation and rubric scoring use temperature=0.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
from typing import List, Tuple

from .llm_client import chat_complete

QUESTIONS_PATH = Path(__file__).parent.parent / "data" / "interview_questions.json"
PER_QUESTION_SECONDS = 120  # 2 min per answer; 5 competencies x (main+followup) ~= 20 min


def _load_competencies() -> list[dict]:
    if not QUESTIONS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {QUESTIONS_PATH}. Expected JSON with 4 competencies."
        )
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    comps = data.get("competencies", [])
    if len(comps) != 4:
        raise ValueError(
            f"Expected 4 competencies in {QUESTIONS_PATH}, got {len(comps)}."
        )
    return comps


COMPETENCIES = _load_competencies()
COMPETENCY_COUNT = len(COMPETENCIES)  # 4
# kept for backward-compat with views/state.py that references this name
MAIN_QUESTIONS_COUNT = COMPETENCY_COUNT


# ---- Prompts ----

FOLLOWUP_PROMPT = """You are conducting a structured behavioral interview for a consulting role at Capgemini Invent. The candidate just answered this question on the competency "{competency_name}":

Question: "{main_question}"

Their answer:
"{transcript}"

Your goal for the follow-up: {followup_goal}

Pick exactly ONE of these four follow-up types based on what the candidate actually said:

A) GET SPECIFIC, if the answer was vague or general (no concrete moment, no specific action they personally took)
B) GET EVIDENCE, if the answer sounded prepared or abstract (no real outcome, sounds rehearsed)
C) GET REASONING, if the answer was good but didn't explain the thinking behind their choice
D) GET REFLECTION, if the answer described an outcome but not what they learned

The follow-up must respond directly to what they said, not a generic probe. It must be answerable in under 2 minutes.

Return ONLY a JSON object in this exact format, no preamble or markdown:
{{"bucket": "<A|B|C|D>", "question": "<the follow-up question>"}}"""


SCORING_PROMPT = """You are scoring a candidate's answer for the competency "{competency_name}" on a 0-25 scale. Be strict, evidence-based, and use the full scale. Do not compress scores toward the middle.

Main question: "{main_question}"
Main answer: "{main_transcript}"

Follow-up question: "{followup_question}"
Follow-up answer: "{followup_transcript}"

What the follow-up was trying to surface: {followup_goal}

Use these anchor points as reference. Whole numbers between anchors are encouraged when the candidate falls between levels.

0  : No evidence. Generic, off-topic, or no example provided.
6  : Weak. A situation was mentioned but vague, with no clear personal contribution.
13 : Adequate. Clear example, some personal ownership, basic reflection. Meets the bar.
19 : Strong. Specific example, clear personal contribution, meaningful outcome, genuine reflection.
25 : Exceptional. Outstanding specificity, deep self-awareness, behavioral change demonstrated.

Also flag whether the answer appears scripted (perfect STAR structure with no emotional texture, identical phrasing patterns, sounds rehearsed). Scripted does NOT mean low-scoring on its own; flag for human review only.

Return ONLY a JSON object in this exact format, no preamble or markdown:
{{"score": <integer 0-25>, "scripted_flag": <true|false>, "rationale": "<one short sentence>"}}"""


GENERIC_FALLBACK_FOLLOWUP = {
    "bucket": "A",
    "question": "Can you walk me through exactly what you personally did, not the team, just you?",
}


# ---- Question selection ----

def _seed_for(candidate_id: str) -> int:
    h = hashlib.sha256(f"{candidate_id}:layer3".encode()).hexdigest()
    return int(h[:12], 16)


def load_main_questions(candidate_id: str) -> List[dict]:
    """Pick one question per competency, seeded by candidate_id.

    Returns a list of 5 dicts in the spec's competency order:
      {"competency_id": "A10", "competency_key": "proactivity",
       "competency_name": "...", "question": "...", "followup_goal": "..."}
    """
    rng = random.Random(_seed_for(candidate_id))
    selected = []
    for comp in COMPETENCIES:
        chosen = rng.choice(comp["questions"])
        selected.append({
            "competency_id": comp["id"],
            "competency_key": comp["key"],
            "competency_name": comp["name"],
            "question": chosen,
            "followup_goal": comp["followup_goal"],
        })
    return selected


# ---- Follow-up generation ----

def _parse_json_object(raw: str) -> dict | None:
    """Strip code fences and parse the first JSON object found."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*?\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def generate_followup(
    main_question: str,
    transcript: str,
    competency_name: str,
    followup_goal: str,
) -> dict:
    """Returns {"bucket": "A|B|C|D", "question": "..."}.

    On parse failure or empty transcript, returns a generic GET SPECIFIC probe.
    """
    if not transcript or len(transcript.strip()) < 5:
        return dict(GENERIC_FALLBACK_FOLLOWUP)

    prompt = FOLLOWUP_PROMPT.format(
        competency_name=competency_name,
        main_question=main_question,
        transcript=transcript[:2000],
        followup_goal=followup_goal,
    )
    try:
        raw = chat_complete(prompt, temperature=0.0, max_tokens=200)
    except Exception:
        return dict(GENERIC_FALLBACK_FOLLOWUP)

    parsed = _parse_json_object(raw)
    if not parsed:
        return dict(GENERIC_FALLBACK_FOLLOWUP)

    bucket = str(parsed.get("bucket", "A")).strip().upper()[:1]
    if bucket not in {"A", "B", "C", "D"}:
        bucket = "A"
    question = str(parsed.get("question", "")).strip().strip('"')
    if not question:
        return dict(GENERIC_FALLBACK_FOLLOWUP)

    return {"bucket": bucket, "question": question}


# ---- Scoring ----

def score_competency(
    main_question: str,
    main_transcript: str,
    followup_question: str,
    followup_transcript: str,
    competency_name: str,
    followup_goal: str,
) -> dict:
    """Score a competency on 0-25 based on both the main answer and the follow-up.

    Returns {"score": int 0-25, "scripted_flag": bool, "rationale": str}.
    On LLM failure, returns score=13 (the "adequate" anchor) without a flag.
    """
    default = {"score": 13, "scripted_flag": False, "rationale": "Default: scoring failed."}

    # If both transcripts are essentially empty, that's "no evidence".
    main_clean = (main_transcript or "").strip()
    fu_clean = (followup_transcript or "").strip()
    if len(main_clean) < 3 and len(fu_clean) < 3:
        return {"score": 0, "scripted_flag": False, "rationale": "No answer provided."}

    prompt = SCORING_PROMPT.format(
        competency_name=competency_name,
        main_question=main_question,
        main_transcript=main_transcript[:3000],
        followup_question=followup_question or "(no follow-up)",
        followup_transcript=followup_transcript[:2000] if followup_transcript else "(no follow-up answer)",
        followup_goal=followup_goal,
    )
    try:
        raw = chat_complete(prompt, temperature=0.0, max_tokens=150)
    except Exception:
        return default

    parsed = _parse_json_object(raw)
    if not parsed:
        return default

    try:
        score = int(parsed.get("score", 13))
    except (ValueError, TypeError):
        score = 13
    score = max(0, min(25, score))

    scripted_flag = bool(parsed.get("scripted_flag", False))
    rationale = str(parsed.get("rationale", "")).strip()[:300]

    return {"score": score, "scripted_flag": scripted_flag, "rationale": rationale}


# ---- Aggregation & interpretation ----

INTERPRETATION_BANDS = [
    (0, 40, "Below threshold", "Significant gaps across multiple competencies. Not recommended to advance."),
    (41, 59, "Borderline", "Some strengths, but meaningful gaps remain. Warrants closer human review."),
    (60, 74, "Good", "Solid performance across competencies. Meets the baseline for a consulting role."),
    (75, 89, "Strong", "Clear evidence of consulting-relevant behaviors. Recommended to advance."),
    (90, 100, "Exceptional", "Outstanding across the board. Fast-track for next stage."),
]


def interpret_total(total: float) -> dict:
    """Map a 0-100 Layer 3 total to the spec's interpretation band."""
    for lo, hi, label, recommendation in INTERPRETATION_BANDS:
        if lo <= total <= hi:
            return {"label": label, "recommendation": recommendation}
    return {"label": "Unknown", "recommendation": ""}


def aggregate_layer3(
    competency_scores: List[dict],
) -> Tuple[float, dict]:
    """Returns (layer3_total_0_100, competency_dict_for_final_scores).

    competency_scores: list of dicts each with at least
      {"competency_key": str, "score": int 0-25}.

    Total = sum of the four 0-25 scores, naturally on 0-100 (no scaling).
    Each per-competency score (0-25) is scaled to 0-100 in the competency
    dict (* 4) so it's directly comparable with Layer 1/2 competencies in
    the recruiter dashboard radar.
    """
    keys = ("growth_mindset", "adaptability", "collaboration", "self_reflection")

    if not competency_scores:
        return 0.0, {f"competency_l3_{k}": 0.0 for k in keys}

    total = sum(int(s.get("score", 0)) for s in competency_scores)
    total = max(0, min(100, total))

    comp_dict: dict = {}
    for s in competency_scores:
        key = s.get("competency_key")
        if not key:
            continue
        comp_dict[f"competency_l3_{key}"] = round(int(s.get("score", 0)) * 4, 2)

    for key in keys:
        comp_dict.setdefault(f"competency_l3_{key}", 0.0)

    return float(total), comp_dict
