CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    current_stage TEXT NOT NULL DEFAULT 'intro'
);

CREATE TABLE IF NOT EXISTS layer1_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL,
    theme TEXT NOT NULL,
    question_id TEXT NOT NULL,
    question_text TEXT,
    options_shown TEXT,
    correct_option TEXT,
    candidate_answer TEXT,
    is_correct INTEGER NOT NULL,
    time_taken_seconds INTEGER,
    FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
);

CREATE TABLE IF NOT EXISTS layer2_simulation (
    candidate_id TEXT PRIMARY KEY,
    final_state_json TEXT NOT NULL,
    weekly_log_json TEXT NOT NULL,
    weeks_played INTEGER NOT NULL,
    final_cash REAL NOT NULL,
    final_reputation REAL NOT NULL,
    projects_completed INTEGER NOT NULL,
    projects_cancelled INTEGER NOT NULL,
    tradeoff_choice TEXT,
    outcome_score REAL NOT NULL,
    process_score REAL NOT NULL,
    layer2_total REAL NOT NULL,
    time_taken_seconds INTEGER,
    FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
);

CREATE TABLE IF NOT EXISTS layer3_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL,
    competency_order INTEGER NOT NULL,        -- 1..4, the order asked
    competency_id TEXT NOT NULL,              -- 'A1A10', 'A12', 'A6', 'A15'
    competency_key TEXT NOT NULL,             -- 'growth_mindset', 'adaptability', 'collaboration', 'self_reflection'
    competency_name TEXT NOT NULL,            -- human-readable label
    main_question TEXT NOT NULL,
    main_transcript TEXT,
    main_audio_duration_seconds REAL,
    followup_bucket TEXT,                     -- 'A' | 'B' | 'C' | 'D'
    followup_question TEXT,
    followup_transcript TEXT,
    followup_audio_duration_seconds REAL,
    competency_score INTEGER,                 -- 0-25
    scripted_flag INTEGER NOT NULL DEFAULT 0, -- 0/1
    rationale TEXT,
    FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
);

CREATE TABLE IF NOT EXISTS final_scores (
    candidate_id TEXT PRIMARY KEY,
    layer1_score REAL NOT NULL,
    layer2_score REAL NOT NULL,
    layer3_score REAL NOT NULL,
    overall_score REAL NOT NULL,
    competency_analytical REAL,
    competency_numerical REAL,
    competency_verbal REAL,
    competency_strategic REAL,
    competency_adaptability REAL,
    competency_l3_growth_mindset REAL,
    competency_l3_adaptability REAL,
    competency_l3_collaboration REAL,
    competency_l3_self_reflection REAL,
    ai_flag_logical INTEGER NOT NULL DEFAULT 0,
    ai_flag_numerical INTEGER NOT NULL DEFAULT 0,
    ai_flag_verbal INTEGER NOT NULL DEFAULT 0,
    ai_flag_layer2 INTEGER NOT NULL DEFAULT 0,
    top_fit INTEGER NOT NULL,
    recruiter_summary TEXT,
    candidate_feedback TEXT,
    FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
);

CREATE TABLE IF NOT EXISTS recruiter_auth (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL
);
