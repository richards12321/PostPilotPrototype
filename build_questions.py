"""Build Layer-1 question files from raw uploads.

Produces:
  data/questions/numerical_na.xlsx     (90 questions, 5 options each)
  data/questions/numerical_nb.xlsx     (90 questions, 4 options each)
  data/questions/abstract_aa.xlsx      (90 questions, 5 options, locked)
  data/questions/abstract_ab.xlsx      (90 questions, 5 options, locked)
  data/questions/verbal_easy.xlsx      (90 questions, T/F/CS, locked)
  data/questions/verbal_difficult.xlsx (90 questions, T/F/CS, locked)
  data/charts/<image_file>.png         (all images, copied with stable names)

The existing logical.xlsx file is left alone.

Schema (per row):
  question_id          str  unique within the file (e.g. NA1, AA7, VE12, VD3)
  question_text        str  question prompt
  option_a..option_e   str  options (cells may be blank for 3- or 4-option Qs)
  correct_answer       str  letter A-E, in original/unshuffled order
  image_file           str  filename in data/charts/ (or blank)
  answer_image_file    str  optional second image (abstract only)
  lock_options         str  "TRUE" disables shuffling at runtime
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import xlrd

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent
RAW = ROOT.parent / "new_data"
QUESTIONS_DIR = ROOT / "data" / "questions"
CHARTS_DIR = ROOT / "data" / "charts"
QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# manual answer overrides for questions where the source file has no bold
# (computed by hand from the underlying chart/table)
# ---------------------------------------------------------------------------
MANUAL_ANSWERS = {
    "NA34": "0.021",                # 8% of Romania's 1200 comorbid / 4500 total
    "NA35": "0.17",                 # Malta 19500 / total 113620 in 2012
    "NB39": "Cannot be determined", # half-full data not in table
}


# ---------------------------------------------------------------------------
# numerical: parse .xls with bold detection
# ---------------------------------------------------------------------------
def parse_numerical_xls() -> dict:
    """Returns {'NA': [...], 'NB': [...]} where each item is a question dict."""
    src = RAW / "NUMERICAL.xls"
    book = xlrd.open_workbook(src, formatting_info=True)
    sheet = book.sheet_by_index(0)

    def is_bold(r: int, c: int) -> bool:
        xf = book.xf_list[sheet.cell_xf_index(r, c)]
        font = book.font_list[xf.font_index]
        return bool(font.bold) or font.weight >= 700

    out = {"NA": [], "NB": []}
    current = None
    current_rows = []

    def flush():
        if current is None:
            return
        prefix = "NA" if current["id"].startswith("NA") else "NB"
        # determine correct answer letter
        bolds = [i for i, (_, b) in enumerate(current_rows) if b]
        if len(bolds) == 1:
            correct_idx = bolds[0]
            correct_letter = "ABCDE"[correct_idx]
        elif current["id"] in MANUAL_ANSWERS:
            target = MANUAL_ANSWERS[current["id"]]
            # match by string against options
            correct_idx = None
            for i, (opt, _) in enumerate(current_rows):
                # normalize numeric comparison: "0.021" matches "0.021" or "0.0210"
                if str(opt).strip().lower() == str(target).strip().lower():
                    correct_idx = i
                    break
                # try float comparison
                try:
                    if abs(float(opt) - float(target)) < 1e-9:
                        correct_idx = i
                        break
                except (ValueError, TypeError):
                    pass
            if correct_idx is None:
                raise ValueError(
                    f"Manual answer {target!r} for {current['id']} not found "
                    f"in options {[o for o, _ in current_rows]}"
                )
            correct_letter = "ABCDE"[correct_idx]
        else:
            raise ValueError(
                f"{current['id']} has {len(bolds)} bold answers and no manual override. "
                f"Options: {[o for o, _ in current_rows]}"
            )

        # str(o), but defend against the literal string "None" which Excel
        # reads back as NaN. NB14 has "None" as a real answer option.
        opts = []
        for o, _ in current_rows:
            s = str(o)
            if s.strip().lower() == "none":
                s = "None (none of the values)"
            opts.append(s)
        # pad to 5
        while len(opts) < 5:
            opts.append("")

        out[prefix].append({
            "question_id": current["id"],
            "question_text": current["text"],
            "option_a": opts[0],
            "option_b": opts[1],
            "option_c": opts[2],
            "option_d": opts[3],
            "option_e": opts[4],
            "correct_answer": correct_letter,
            "image_file": f"{current['id']}.png",
            "answer_image_file": "",
            "lock_options": "FALSE",  # numerical = shuffle
        })

    for r in range(1, sheet.nrows):  # skip header
        qid = str(sheet.cell(r, 0).value).strip()
        qtext_raw = sheet.cell(r, 1).value
        qtext = str(qtext_raw).strip() if qtext_raw != "" else ""
        opt_raw = sheet.cell(r, 2).value
        opt_str = str(opt_raw).strip() if opt_raw != "" else ""

        if qid.startswith(("NA", "NB")):
            flush()
            current = {"id": qid, "text": qtext}
            current_rows = []
            if opt_str:
                current_rows.append((opt_str, is_bold(r, 2)))
        else:
            if current and opt_str:
                current_rows.append((opt_str, is_bold(r, 2)))
    flush()

    return out


# ---------------------------------------------------------------------------
# abstract: parse answers.xlsx
# ---------------------------------------------------------------------------
def parse_abstract_answers() -> dict:
    """Returns {'AA': {'AA1': 'E', ...}, 'AB': {...}}"""
    src = RAW / "answers.xlsx"
    df = pd.read_excel(src, header=None)
    # data starts at row 4 (header row is row 3 with 'question'/'answer')
    # cols 0-1 are AA, cols 3-4 are AB
    out = {"AA": {}, "AB": {}}
    for _, row in df.iloc[4:].iterrows():
        # AA pair
        q_aa = str(row[0]).strip().lower() if pd.notna(row[0]) else ""
        a_aa = str(row[1]).strip().upper() if pd.notna(row[1]) else ""
        if q_aa.startswith("aa_") and a_aa in "ABCDE":
            num = q_aa.split("_")[1]
            out["AA"][f"AA{num}"] = a_aa
        # AB pair
        q_ab = str(row[3]).strip().lower() if pd.notna(row[3]) else ""
        a_ab = str(row[4]).strip().upper() if pd.notna(row[4]) else ""
        if q_ab.startswith("ab_") and a_ab in "ABCDE":
            num = q_ab.split("_")[1]
            out["AB"][f"AB{num}"] = a_ab
    return out


def build_abstract_rows(prefix: str, answers: dict) -> list:
    """Build rows for abstract_aa or abstract_ab."""
    rows = []
    for n in range(1, 91):
        qid = f"{prefix}{n}"
        ans = answers.get(qid)
        if ans is None:
            print(f"  WARNING: no answer for {qid}, skipping")
            continue
        rows.append({
            "question_id": qid,
            "question_text": "Which figure comes next in the sequence?",
            "option_a": "A",
            "option_b": "B",
            "option_c": "C",
            "option_d": "D",
            "option_e": "E",
            "correct_answer": ans,
            "image_file": f"{qid}.png",
            "answer_image_file": f"{qid}_options.png",
            "lock_options": "TRUE",  # abstract = locked, letters baked into image
        })
    return rows


# ---------------------------------------------------------------------------
# image copying
# ---------------------------------------------------------------------------
def copy_images() -> None:
    """Copy all source PNGs into data/charts/ with stable names."""
    mapping = [
        # (source_dir, prefix, has_answer_image)
        (RAW / "Numerical - (NA)", "NA", False),
        (RAW / "Numerical - (NB)", "NB", False),
        (RAW / "Abstract -  (AA)", "AA", True),
        (RAW / "Abstract - (AB)", "AB", True),
    ]
    total = 0
    for src_dir, prefix, has_ans in mapping:
        for n in range(1, 91):
            q_src = src_dir / f"{n}.PNG"
            q_dst = CHARTS_DIR / f"{prefix}{n}.png"
            if q_src.exists():
                shutil.copy(q_src, q_dst)
                total += 1
            else:
                print(f"  missing: {q_src}")
            if has_ans:
                a_src = src_dir / f"{n}a.PNG"
                a_dst = CHARTS_DIR / f"{prefix}{n}_options.png"
                if a_src.exists():
                    shutil.copy(a_src, a_dst)
                    total += 1
                else:
                    print(f"  missing: {a_src}")
    print(f"copied {total} images to {CHARTS_DIR}")


# ---------------------------------------------------------------------------
# write xlsx
# ---------------------------------------------------------------------------
COLUMNS = [
    "question_id", "question_text",
    "option_a", "option_b", "option_c", "option_d", "option_e",
    "correct_answer", "image_file", "answer_image_file", "lock_options",
]


def write_xlsx(rows: list, name: str) -> None:
    df = pd.DataFrame(rows, columns=COLUMNS)
    path = QUESTIONS_DIR / f"{name}.xlsx"
    df.to_excel(path, index=False)
    print(f"wrote {path}: {len(df)} questions")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# verbal: parse easy/difficult into the same standard schema
# ---------------------------------------------------------------------------
def build_verbal_rows(src: Path, prefix: str) -> list:
    """Build rows from verbal_easy.xlsx or verbal_difficult.xlsx.

    Source columns: #, Text, Statement, Answer (A/B/C), Full Answer, ...
    A = True, B = False, C = Cannot Say.
    Options are LOCKED (True/False/Cannot Say must always appear in that
    order, shuffling the labels would defeat the format).
    """
    df = pd.read_excel(src)
    rows = []
    for _, r in df.iterrows():
        n = int(r["#"])
        # Combine passage + statement so the candidate sees both inline
        text = (
            f"**Passage:** {str(r['Text']).strip()}\n\n"
            f"**Statement:** {str(r['Statement']).strip()}"
        )
        ans = str(r["Answer"]).strip().upper()
        if ans not in {"A", "B", "C"}:
            print(f"  skipping {prefix}{n}: bad answer {ans!r}")
            continue
        rows.append({
            "question_id": f"{prefix}{n}",
            "question_text": text,
            "option_a": "True",
            "option_b": "False",
            "option_c": "Cannot Say",
            "option_d": "",
            "option_e": "",
            "correct_answer": ans,
            "image_file": "",
            "answer_image_file": "",
            "lock_options": "TRUE",  # T/F/CS order is canonical, do not shuffle
        })
    return rows


def main() -> None:
    print("=== numerical ===")
    num = parse_numerical_xls()
    write_xlsx(num["NA"], "numerical_na")
    write_xlsx(num["NB"], "numerical_nb")

    print("\n=== abstract ===")
    ans = parse_abstract_answers()
    print(f"  AA answers: {len(ans['AA'])}, AB answers: {len(ans['AB'])}")
    write_xlsx(build_abstract_rows("AA", ans["AA"]), "abstract_aa")
    write_xlsx(build_abstract_rows("AB", ans["AB"]), "abstract_ab")

    print("\n=== verbal ===")
    write_xlsx(build_verbal_rows(RAW / "verbal_easy.xlsx", "VE"), "verbal_easy")
    write_xlsx(build_verbal_rows(RAW / "verbal_difficult.xlsx", "VD"), "verbal_difficult")

    print("\n=== copying images ===")
    copy_images()

    print("\nDone.")


if __name__ == "__main__":
    main()
