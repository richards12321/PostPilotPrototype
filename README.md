# Capgemini Invent, Consulting Recruitment Assessment

A Streamlit prototype for assessing consulting candidates across three layers:

1. **Cognitive Assessment**, 30 timed reasoning questions (logical, numerical, verbal)
2. **Firm Simulation**, 8-week continuous resource management game with cash, reputation, fatigue, and a mid-simulation trade-off
3. **AI-Led Interview**: 4 voice-recorded questions with live AI-generated follow-ups

Candidates receive personalized feedback on completion. Per-layer scores are not shown to candidates between layers, only the full breakdown after all three are done. A password-protected recruiter dashboard lets the hiring team filter, review, and export results.

---

## Quick start

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate      # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure your API key

```bash
cp .env.example .env
# Then open .env and paste your OpenAI API key
```

The prototype uses Capgemini's Azure OpenAI resource (`jt-learning-openai-7382` in `swedencentral`). The deployment names, region, and API version are hard-coded in `assessment_logic/llm_client.py` (`CAPSTONE_CONFIG`). Specifically:

- `gpt-4-1-mini-qc` (gpt-4.1-mini) for interview follow-ups, rubric scoring, and feedback generation.
- `capstone-transcribe` (gpt-4o-mini-transcribe) for voice answer transcription.
- The Layer 3 questions are also read out loud to the candidate using browser-side Web Speech (no Azure call required).

Only the API key needs to live in secrets. There is no longer any deployment-name configuration to set.

### 3. Run the app

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501`. First launch initializes the SQLite database and prints the default recruiter credentials to the console.

### Recruiter login

The recruiter password is read from `RECRUITER_PASSWORD` in your Streamlit secrets (or `.env` for local dev). The username is always `recruiter`.

If `RECRUITER_PASSWORD` is not set, the app falls back to `changeme-local-dev` for local development only.

The password is synced to the database on every app start, so rotating the secret is enough, no manual DB edits needed.

---

## Customizing content

### Layer 1 question banks

The three themes live in `data/questions/`:

- `logical.xlsx`
- `numerical.xlsx`
- `verbal.xlsx`

Each file needs these columns (case-sensitive):

| question_id | question_text | option_a | option_b | option_c | option_d | correct_answer |
|-------------|---------------|----------|----------|----------|----------|----------------|

`correct_answer` must be `A`, `B`, `C`, or `D`. You can include as many questions as you want; the app samples 10 per theme per candidate using a deterministic seed based on the candidate ID.

Optional: to attach a chart or image to a question, place it at `data/charts/{question_id}.png`. The app will auto-display it.

The placeholder banks currently ship with 20 questions per theme. Replace them with your real content whenever you're ready. There's a generator script at the project root (`generate_placeholder_questions.py`) if you want to rebuild the placeholders.

### Layer 2 scenario

Edit `data/layer2_scenario.json`. The file has four top-level keys:

- `starting_state`, initial cash, reputation, total weeks
- `consultants`, the 6 consultants with skills, seniority, daily rates
- `projects`, the project pool with availability windows, durations, weekly burn, revenue, deadlines
- `weekly_events`, pre-scripted disruptions (sick leave, budget cuts, new project alerts, trade-off trigger)
- `tradeoff`, the Week 6 trade-off scenario with 4 options and their scores
- `scoring_constants`, fatigue rates, quality penalties, reputation effects

Keep the IDs stable (`C1-C6`, `P1-P8`). The scoring code uses them.

### Layer 3 questions

Edit `data/interview_questions.txt`. One question per line. The app samples 5 per candidate with a deterministic seed.

---

## Scoring

**Layer weights in the overall score:**
- Layer 1: 30%
- Layer 2: 35%
- Layer 3: 35%

**Layer 2 score (deterministic, no AI):**
- Outcome score: 70% (final cash, reputation, projects completed, fatigue management)
- Process score: 30% (constraint compliance and skill match across all 8 weeks)

**Top Fit flag** (shown only to recruiters) requires all three:
- Overall score ≥ 70
- No single layer below 60
- At least 2 competencies ≥ 75

All scoring logic is in `assessment_logic/`. Regression tests in `tests/test_scoring.py` cover 29 test cases including the simulation engine.

**Candidates do not see scores between layers.** They see "Layer N complete, moving on" and only the full breakdown after all three layers are done.

---

## Running tests

```bash
pytest tests/
```

These tests cover pure scoring logic only. They do not call the OpenAI API or touch the database.

---

## Known limitations

- **Single concurrent session per candidate.** If the same candidate opens two tabs, the last write wins. Built for a pilot, not for scale.
- **Layer 2 mid-simulation resume restarts from Week 1.** The firm sim is continuous and intra-layer state isn't checkpointed weekly. Once a candidate finishes Layer 2, their final result is persisted and they can resume into Layer 3. To support mid-Layer-2 resume, add weekly state writes to a new DB table.
- **Layer 3 audio is not persisted.** Only the transcript is saved. If you need audio files for training or review, wire up file storage in `views/layer3.py`.
- **No PDF export.** The dashboard exports CSV only. PDF candidate reports would need something like `reportlab` bolted on to `views/candidate_results.py`.
- **Microphone permission required.** Browsers will ask for mic access on Layer 3. A typed fallback is always available.
- **Desktop-first.** Mobile layouts work but are not the priority.
- **LLM scoring is approximately reproducible.** Even at `temperature=0`, OpenAI has minor infrastructure-level variance in outputs. The rubric scoring includes a JSON-extraction fallback for robustness.
- **Password hashing is SHA-256, not bcrypt.** Fine for a pilot with one recruiter account. Swap for bcrypt before real deployment.
- **Per-question timer uses polling.** `streamlit-autorefresh` re-renders every second, which causes a visible flicker. Acceptable for a pilot; for production consider a JS component.

---

## Project layout

```
recruitment_prototype/
├── app.py                      # entry point, routing
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── generate_placeholder_questions.py
├── recruitment.db              # SQLite, created at first run
│
├── database/
│   ├── __init__.py
│   ├── db.py                   # CRUD helpers, auth
│   └── schema.sql              # 6 tables
│
├── assessment_logic/
│   ├── __init__.py
│   ├── llm_client.py           # OpenAI wrapper + logging
│   ├── layer1_logic.py         # question selection, theme scoring
│   ├── layer2_logic.py         # constraint/optimization/adaptability scoring
│   ├── layer3_logic.py         # follow-up generation, rubric scoring
│   ├── scoring_matrix.py       # overall score, top-fit classification
│   └── feedback_generator.py   # candidate + recruiter LLM summaries
│
├── views/
│   ├── __init__.py
│   ├── state.py                # session state + DB-backed resume
│   ├── landing.py              # candidate/recruiter choice
│   ├── candidate_intro.py      # welcome page
│   ├── layer1.py               # cognitive assessment UI
│   ├── layer2.py               # staffing simulation UI
│   ├── layer3.py               # voice interview UI
│   ├── candidate_results.py    # final feedback
│   └── recruiter_dashboard.py  # table, filters, deep-dive
│
├── data/
│   ├── layer2_scenario.json
│   ├── interview_questions.txt
│   ├── questions/
│   │   ├── logical.xlsx
│   │   ├── numerical.xlsx
│   │   └── verbal.xlsx
│   └── charts/                 # optional chart images
│
├── logs/
│   └── llm_calls.log           # JSON-per-line log of every LLM call
│
├── recordings/                 # reserved for audio if you wire persistence
│
└── tests/
    ├── __init__.py
    └── test_scoring.py         # 40 regression tests
```

---

## v7 changes

This is the change set delivered in v7 (over v6).

### Layer 1
- **Theme-level timer.** One time block per theme replaces the per-question
  timer. Logical 12:30, Numerical 15:00, Verbal 7:30. The clock runs
  continuously over the whole theme. When time runs out, every unanswered
  question is auto-marked wrong and the candidate skips to the next theme.
- **Example questions on theme intros.** Each theme intro now shows a small
  worked example (one per theme: a rotation pattern, a percentage growth
  calc, a "Cannot Say" verbal item) inside an `Example question (not graded)`
  box, plus the theme total time and the implied per-question average.
- **Logical theme rewritten as 1×5 sequence.** The old "3×3 matrix" wording
  was wrong for the actual question format. Both the overview and the
  logical theme intro now describe a row of figures with one missing slot.
- **Don't-overthink-it line moved.** It now lives on the Layer 1 overview
  as a standalone bullet rather than buried in the logical theme intro.
- **All NA and NB chart PNGs replaced.** 90 NA + 90 NB images swapped in
  from the new attachments. The Excel question files were untouched.

### Layer 2
- **David decision bug fixed.** `apply_decision` is now idempotent and
  overwriting: switching retain → let_go before clicking Advance refunds
  the €40,000 retention bonus, applies let_go's reputation hit (-2), and
  sets David's departure week. State is tracked in
  `decision_applied_effects`. Covered by two new regression tests.
- **Daily rate display removed.** The `€X/day` line on each consultant was
  confusing because daily rates aren't deducted anywhere; only weekly
  project burn is. The data field stays in `layer2_scenario.json` for
  future use.

### Layer 3
- **Four competencies, not five.** A1 (Learning Mindset) and A10 (Proactivity)
  are merged into a single Growth Driven Mindset competency (id `A1A10`,
  key `growth_mindset`). The four are: Growth Driven Mindset, Adaptability,
  Collaboration, Self-Reflection. 5 questions per competency, sourced
  verbatim from the new system prompt doc.
- **0-25 per competency, total 0-100.** Anchor points: 0 / 6 / 13 / 19 / 25.
  Per-competency scaled scores in the radar are `* 4` (was `* 5`).
- **Continuous voice flow.** No more Continue buttons between exchanges.
  After the candidate stops recording, the system silently transcribes,
  generates the next thing to say, speaks it, and re-opens the mic. The
  view is built around a flat 8-turn list (4 competencies × 2 turns) and
  a single `l3_turn_idx`. Typed-fallback expander is still available.
- **16-minute total timer.** Starts when the first question is spoken
  (with a small offset for the spoken duration). When time expires, the
  in-flight competency is scored with whatever was captured; remaining
  competencies get a zero row with an "interview time expired" rationale.
- **120-second per-answer cap.** Up from 90s.
- **Pulsating / rotating orb.** `#1DB8F2` orb sits below the question
  header. Three states: speaking pulses (1.5s loop with glow), listening
  rotates (6s loop with subtle inner shimmer), idle is static. Inline
  HTML/CSS via `streamlit.components.v1.html`.

### AI-use detection (informational)
- **Per-theme L1 flags + L2 flag.** Each Layer 1 theme is flagged if score
  ≥ 80% AND theme total time ≤ 25% of the theme block. Layer 2 is flagged
  if total ≥ 80 AND elapsed ≤ 35% of the 20-minute limit. Flags are
  informational only and do not affect any score, top-fit classification,
  or filter logic.
- **Recruiter dashboard column.** New "Possible AI use" column between
  Overall and Top Fit, with values like "L1 verbal" or "L1 logical+numerical, L2".

### Schema
- **New columns on `final_scores`.** `competency_l3_growth_mindset`,
  `ai_flag_logical`, `ai_flag_numerical`, `ai_flag_verbal`, `ai_flag_layer2`.
- **Migration in `init_db`.** `_migrate_final_scores` runs on startup and
  adds any missing v7 columns via ALTER TABLE. Idempotent, safe on a fresh
  DB, safe on a v6 DB. The legacy `competency_l3_proactivity` and
  `competency_l3_learning_mindset` columns are left in place (we just stop
  writing to them) to keep migrations risk-free.

### Scoring matrix
- **Top Fit simplified.** Single rule: `overall >= 70`. The old multi-criteria
  (no layer below 60, ≥2 competencies ≥75) and the constants
  `TOP_FIT_MIN_LAYER` / `TOP_FIT_HIGH_COMPETENCY_THRESHOLD` /
  `TOP_FIT_MIN_HIGH_COMPETENCIES` are gone. The recruiter caption now reads
  "Overall score ≥ 70".

### Recruiter dashboard
- **Removed sliders:** Min strategic, Min L3 proactivity.
- **Reset filters now actually resets.** Every filter widget gets a
  deterministic key (`recruiter_min_overall`, etc); the button deletes
  those keys and reruns.
- **Radar updated** to 4 L3 axes (Growth Mindset, Adaptability (interview),
  Collaboration, Self-Reflection) plus the existing 5 L1/L2 axes.

### Style
- **Em-dash sweep.** Every U+2014 character removed from `.py`, `.json`, `.sql`,
  and `.md` files. Replacements were context-sensitive: comma or sentence
  break for asides, colon for list/explanation introductions, hyphen with
  spaces for short alternatives.

### File-by-file changelog

- `data/charts/NA*.png`, `data/charts/NB*.png`: replaced (90 + 90).
- `data/interview_questions.json`: rewritten with 4 competencies and 5
  questions each from the new system prompt doc.
- `assessment_logic/layer1_logic.py`: `THEME_TIME_LIMITS` and
  `theme_time_limit_for()` added; `time_limit_for()` kept as a
  backward-compat per-question-average shim.
- `assessment_logic/layer2_logic.py`: `apply_decision` made idempotent and
  overwriting; `decision_applied_effects` tracked in `initial_state`.
- `assessment_logic/layer3_logic.py`: 4-competency loader, 0-25 scoring
  prompt, `aggregate_layer3` switched to the four new keys with `* 4`
  scaling, fallback default raised from 10 to 13.
- `assessment_logic/scoring_matrix.py`: `classify_top_fit` simplified to
  `overall >= 70`; `assemble_final_scores` now writes
  `competency_l3_growth_mindset` + the four AI flag columns; old constants
  removed.
- `assessment_logic/feedback_generator.py`: prompts and rule-based fallback
  rewritten for the four new L3 competencies.
- `database/schema.sql`: new columns on `final_scores`, comment on
  `layer3_results.competency_score` updated to 0-25.
- `database/db.py`: `_migrate_final_scores` added inside `init_db`;
  `save_final_score` and `get_all_completed_candidates` updated to the
  new column list.
- `views/layer1.py`: rewritten for theme-level timer, example questions,
  AI-flag computation on theme finish, auto-mark-wrong on timeout.
- `views/layer2.py`: daily rate removed from consultant info line; AI-flag
  computation in `_finalize_and_advance`.
- `views/layer3.py`: full rewrite for continuous voice flow, 16-min total
  timer, 120s per-answer cap, time-expiry handler that scores the
  in-flight competency and zero-fills the rest, pulsating/rotating orb.
- `views/recruiter_dashboard.py`: removed Min strategic / Min L3 proactivity
  sliders, deterministic filter keys, working Reset filters, new "Possible
  AI use" column, radar updated to 4 L3 axes, Top Fit caption simplified.
- `views/candidate_results.py`: radar updated to 4 L3 axes, AI flags pulled
  from session state and passed into `assemble_final_scores`.
- `views/state.py`: new layer 3 turn-based session keys
  (`l3_turns`, `l3_turn_idx`, `l3_started_at`, `l3_finished`); old
  `l3_phase`/`l3_current_followup`/etc removed; `reset_candidate_state`
  also strips dynamic per-turn / per-theme keys; `resume_from_db` updated
  for the new turn model.
- `tests/test_scoring.py`: 40 tests, including new
  `test_decision_overwrite_retain_then_let_go_refunds_and_applies_let_go`
  and `test_decision_overwrite_through_advance_week`; old multi-criteria
  Top Fit tests replaced with single-rule tests; Layer 3 aggregation tests
  updated for the four-competency 0-25 model.

---

## Credits

Built as part of the Capgemini Invent capstone at HSG, Group 4: Isabella Albertoni, Inés Frank, Dmytro Makukha, Richard, Mina Simic. Supervising faculty: Prof. Ursula Knorr. Capgemini Invent contacts: Jakob and Nicolas.
