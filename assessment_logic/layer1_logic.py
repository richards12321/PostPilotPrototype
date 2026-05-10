"""Layer 1 logic: cognitive assessment.

Pure functions with seeded randomness. The same (candidate_id, theme)
pair always yields the same questions in the same order with the same
option shuffling.

Themes are organised as parent themes (logical, numerical, verbal) plus
sub-themes that pull from different question pools. When a parent theme
has multiple sub-themes, candidates draw a balanced sample across them.
For example, the logical block draws from the original logical pool and
both abstract-reasoning sets (AA and AB).

Question files live in ``data/questions/<pool>.xlsx``. Required columns:
    question_id, question_text,
    option_a, option_b, option_c, option_d (option_e is optional),
    correct_answer (letter A-E in unshuffled order)
Optional columns:
    image_file       , file in data/charts/, displayed above the question
    answer_image_file, second image (used by abstract: A-E option grid)
    lock_options     , "TRUE" disables shuffling; required for image-locked
                        answer keys like the abstract sets
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# theme configuration
# ---------------------------------------------------------------------------
THEMES: List[str] = ["logical", "numerical", "verbal"]

# Each theme draws from one or more question pools. The runner samples
# QUESTIONS_PER_THEME questions, distributing them across pools as evenly
# as possible (any remainder goes to the first pool in the list).
THEME_POOLS: Dict[str, List[str]] = {
    "logical":   ["abstract_aa", "abstract_ab"],
    "numerical": ["numerical_na", "numerical_nb"],
    "verbal":    ["verbal_difficult"],
}

QUESTIONS_PER_THEME = 10

# Per-theme TOTAL time limits in seconds (one timer per theme block).
#   Logical:   750s = 12.5 min for 10 questions (~75s avg per question)
#   Numerical: 900s = 15.0 min for 10 questions (~90s avg per question)
#   Verbal:    450s =  7.5 min for 10 questions (~45s avg per question)
THEME_TIME_LIMITS: Dict[str, int] = {
    "logical":   750,
    "numerical": 900,
    "verbal":    450,
}


def theme_time_limit_for(theme: str) -> int:
    """Total time budget for a theme block, in seconds."""
    return THEME_TIME_LIMITS.get(theme, 600)


def time_limit_for(theme: str) -> int:
    """Backward-compat shim: returns the implied per-question average.

    Older code paths still call this expecting per-question seconds. We
    return the theme total divided by the question count so they don't
    blow up. New code should call theme_time_limit_for() instead.
    """
    return THEME_TIME_LIMITS.get(theme, 600) // QUESTIONS_PER_THEME


# Backward-compat: older code paths import TIME_LIMIT_SECONDS as a constant.
TIME_LIMIT_SECONDS = 60

DATA_DIR = Path(__file__).parent.parent / "data"
QUESTIONS_DIR = DATA_DIR / "questions"
CHARTS_DIR = DATA_DIR / "charts"

OPTION_COLUMNS = ["option_a", "option_b", "option_c", "option_d", "option_e"]
LETTERS = ["A", "B", "C", "D", "E"]


# ---------------------------------------------------------------------------
# data class
# ---------------------------------------------------------------------------
@dataclass
class Question:
    question_id: str
    question_text: str
    options: List[str]              # post-shuffle (or original order if locked)
    correct_option: str             # letter A..E indexing into options
    chart_path: str | None          # main image, or None
    answer_image_path: str | None = None   # secondary image (abstract grid)
    locked: bool = False            # True = options were not shuffled


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _seed_for(candidate_id: str, theme: str) -> int:
    """Stable integer seed from candidate + theme."""
    h = hashlib.sha256(f"{candidate_id}:{theme}".encode()).hexdigest()
    return int(h[:12], 16)


def _is_blank(v) -> bool:
    """True if a cell value should be treated as missing."""
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    s = str(v).strip()
    return s == "" or s.lower() == "nan"


def _load_pool(pool: str) -> pd.DataFrame:
    """Load one pool's Excel file."""
    path = QUESTIONS_DIR / f"{pool}.xlsx"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing question file: {path}. "
            f"Expected columns: [question_id, question_text, option_a..option_e, "
            f"correct_answer] plus optional [image_file, answer_image_file, lock_options]."
        )
    df = pd.read_excel(path)
    required = {"question_id", "question_text", "option_a", "option_b",
                "option_c", "option_d", "correct_answer"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {missing}")
    if df.empty:
        raise ValueError(f"{path.name} contains no questions.")
    return df


def _row_options(row: pd.Series) -> List[str]:
    """Extract the populated options for a row, in A-E order."""
    out: List[str] = []
    for col in OPTION_COLUMNS:
        if col in row.index and not _is_blank(row[col]):
            out.append(str(row[col]))
    return out


def _row_flag(row: pd.Series, col: str) -> bool:
    """True if the named column holds a truthy flag."""
    if col not in row.index:
        return False
    v = row[col]
    if _is_blank(v):
        return False
    return str(v).strip().lower() in {"true", "1", "yes", "y"}


def _row_image(row: pd.Series, col: str) -> str | None:
    """Resolve a chart filename column to an absolute path, or None."""
    if col not in row.index or _is_blank(row[col]):
        return None
    fname = str(row[col]).strip()
    p = CHARTS_DIR / fname
    return str(p) if p.exists() else None


def _allocate(total: int, n_pools: int) -> List[int]:
    """Split ``total`` across ``n_pools`` pools as evenly as possible."""
    base = total // n_pools
    rem = total % n_pools
    return [base + (1 if i < rem else 0) for i in range(n_pools)]


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------
def select_questions(candidate_id: str, theme: str) -> List[Question]:
    """Seeded sample + option shuffle for one theme.

    For themes with multiple pools (e.g. logical = logical + abstract_aa +
    abstract_ab), questions are drawn proportionally from each pool, then
    the combined list is shuffled so pools don't appear in clusters.
    """
    pools = THEME_POOLS.get(theme, [theme])
    rng = random.Random(_seed_for(candidate_id, theme))

    quota = _allocate(QUESTIONS_PER_THEME, len(pools))

    drawn: List[Tuple[str, pd.Series]] = []   # (pool, row)
    for pool, n_wanted in zip(pools, quota):
        df = _load_pool(pool)
        n = min(n_wanted, len(df))
        for idx in rng.sample(range(len(df)), n):
            drawn.append((pool, df.iloc[idx]))

    # interleave pools
    rng.shuffle(drawn)

    out: List[Question] = []
    for _pool, row in drawn:
        options = _row_options(row)
        if len(options) < 2:
            continue  # malformed; skip silently

        correct_letter_orig = str(row["correct_answer"]).strip().upper()
        if correct_letter_orig not in LETTERS[: len(options)]:
            continue  # answer letter outside option range
        correct_text = options[LETTERS.index(correct_letter_orig)]

        locked = _row_flag(row, "lock_options")
        if locked:
            shuffled = list(options)
        else:
            shuffled = list(options)
            rng.shuffle(shuffled)

        new_correct_letter = LETTERS[shuffled.index(correct_text)]

        out.append(Question(
            question_id=str(row["question_id"]),
            question_text=str(row["question_text"]),
            options=shuffled,
            correct_option=new_correct_letter,
            chart_path=_row_image(row, "image_file"),
            answer_image_path=_row_image(row, "answer_image_file"),
            locked=locked,
        ))

    return out


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
def theme_score(correct_count: int, total: int = QUESTIONS_PER_THEME) -> float:
    """Simple percentage. Kept as a function for consistency/testability."""
    if total <= 0:
        return 0.0
    return round((correct_count / total) * 100, 2)


def aggregate_layer1(theme_scores: dict) -> Tuple[float, dict]:
    """Returns (layer1_total, competency_dict).

    theme_scores must have keys 'logical', 'numerical', 'verbal'.
    """
    logical = theme_scores.get("logical", 0.0)
    numerical = theme_scores.get("numerical", 0.0)
    verbal = theme_scores.get("verbal", 0.0)
    total = round((logical + numerical + verbal) / 3, 2)
    competencies = {
        "competency_analytical": logical,
        "competency_numerical": numerical,
        "competency_verbal": verbal,
    }
    return total, competencies
