CREATE TABLE IF NOT EXISTS companies (
    company_id INTEGER PRIMARY KEY,
    company_name TEXT NOT NULL,
    website TEXT NOT NULL UNIQUE,
    industry TEXT,
    location TEXT,
    size TEXT,
    hiring_status TEXT,
    priority TEXT,
    last_checked TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_pages (
    page_id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL,
    page_type TEXT NOT NULL,
    url TEXT NOT NULL,
    raw_text TEXT,
    status_code INTEGER,
    content_hash TEXT,
    scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies (company_id)
);

CREATE TABLE IF NOT EXISTS company_profiles (
    profile_id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL UNIQUE,
    company_summary TEXT,
    domain_tags TEXT,
    uses_ai INTEGER,
    biomedical_relevance INTEGER,
    neuroscience_relevance INTEGER,
    ml_relevance INTEGER,
    fit_score REAL,
    fit_reason TEXT,
    fit_details TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies (company_id)
);

CREATE TABLE IF NOT EXISTS job_postings (
    job_id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    url TEXT,
    description TEXT,
    date_found TEXT DEFAULT CURRENT_TIMESTAMP,
    active INTEGER DEFAULT 1,
    fit_score REAL,
    fit_reason TEXT,
    fit_details TEXT,
    source_board TEXT,
    discovery_run_id TEXT,
    keyword_score REAL,
    matched_keywords TEXT,
    evaluated_at TEXT,
    description_status TEXT,
    description_source TEXT,
    description_source_url TEXT,
    description_checked_at TEXT,
    description_error TEXT,
    FOREIGN KEY (company_id) REFERENCES companies (company_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY,
    run_type TEXT NOT NULL,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    companies_checked INTEGER,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_companies_website ON companies (website);
CREATE INDEX IF NOT EXISTS idx_company_pages_company_id ON company_pages (company_id);
CREATE INDEX IF NOT EXISTS idx_company_profiles_company_id ON company_profiles (company_id);
CREATE INDEX IF NOT EXISTS idx_job_postings_company_id ON job_postings (company_id);
CREATE INDEX IF NOT EXISTS idx_job_postings_active ON job_postings (active);

CREATE TABLE IF NOT EXISTS employer_ats_sources (
    ats_source_id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('greenhouse', 'lever', 'ashby', 'workday')),
    board_url TEXT NOT NULL,
    board_token TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    discovery_method TEXT NOT NULL DEFAULT 'career_page',
    status TEXT NOT NULL DEFAULT 'not_run',
    last_checked_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, provider, board_url),
    FOREIGN KEY (company_id) REFERENCES companies (company_id)
);

CREATE INDEX IF NOT EXISTS idx_employer_ats_sources_company
    ON employer_ats_sources (company_id);
CREATE INDEX IF NOT EXISTS idx_employer_ats_sources_provider
    ON employer_ats_sources (provider, enabled);

CREATE TABLE IF NOT EXISTS tracked_jobs (
    tracked_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL UNIQUE,
    stage TEXT NOT NULL DEFAULT 'tracked',
    notes TEXT,
    applied_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);

CREATE INDEX IF NOT EXISTS idx_tracked_jobs_stage ON tracked_jobs (stage);
CREATE INDEX IF NOT EXISTS idx_tracked_jobs_job_id ON tracked_jobs (job_id);

CREATE TABLE IF NOT EXISTS job_reviews (
    review_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL UNIQUE,
    decision TEXT NOT NULL CHECK (decision IN ('maybe', 'declined', 'accepted')),
    reviewed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);

CREATE INDEX IF NOT EXISTS idx_job_reviews_decision ON job_reviews (decision);
CREATE INDEX IF NOT EXISTS idx_job_reviews_job_id ON job_reviews (job_id);

CREATE TABLE IF NOT EXISTS application_preparation_steps (
    step_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    step_key TEXT NOT NULL,
    title TEXT NOT NULL,
    position INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'complete', 'not_required')),
    details TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, step_key),
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);

CREATE INDEX IF NOT EXISTS idx_application_steps_job_id
    ON application_preparation_steps (job_id, position);

CREATE TABLE IF NOT EXISTS application_sessions (
    session_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL UNIQUE,
    application_url TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'inspected',
    current_page TEXT,
    requires_account INTEGER NOT NULL DEFAULT 0,
    privacy_consent_required INTEGER NOT NULL DEFAULT 0,
    captcha_required INTEGER NOT NULL DEFAULT 0,
    automation_class TEXT NOT NULL DEFAULT 'assisted',
    classification_reason TEXT,
    last_inspected_at TEXT,
    last_error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);

CREATE TABLE IF NOT EXISTS application_fields (
    field_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    section TEXT NOT NULL,
    field_key TEXT NOT NULL,
    label TEXT NOT NULL,
    field_type TEXT NOT NULL DEFAULT 'text',
    required INTEGER NOT NULL DEFAULT 0,
    options_json TEXT,
    value TEXT,
    status TEXT NOT NULL DEFAULT 'missing',
    disposition TEXT NOT NULL DEFAULT 'pending',
    validation_error TEXT,
    last_observed_at TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, field_key),
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);

CREATE INDEX IF NOT EXISTS idx_application_fields_job
    ON application_fields (job_id, section, position);

CREATE TABLE IF NOT EXISTS application_facts (
    fact_key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'text',
    source TEXT NOT NULL DEFAULT 'user_confirmed',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS application_audit_events (
    event_id INTEGER PRIMARY KEY,
    job_id INTEGER,
    provider TEXT,
    event_type TEXT NOT NULL,
    target_key TEXT,
    outcome TEXT NOT NULL DEFAULT 'success',
    details_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);

CREATE INDEX IF NOT EXISTS idx_application_audit_job
    ON application_audit_events (job_id, created_at);

CREATE TABLE IF NOT EXISTS application_submissions (
    submission_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    provider TEXT,
    application_url TEXT,
    method TEXT NOT NULL DEFAULT 'user_confirmed_external',
    snapshot_json TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);

CREATE INDEX IF NOT EXISTS idx_application_submissions_job
    ON application_submissions (job_id, submitted_at DESC);

CREATE TABLE IF NOT EXISTS job_evaluation_queue (
    queue_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('queued','deferred','claimed','completed','failed','cancelled')),
    priority INTEGER NOT NULL DEFAULT 100,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    requested_model TEXT NOT NULL DEFAULT 'gpt-5.6-terra',
    requested_reasoning_effort TEXT NOT NULL DEFAULT 'low',
    defer_reason TEXT,
    lease_owner TEXT,
    lease_expires_at TEXT,
    last_error TEXT,
    eligible_at TEXT,
    claimed_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(job_id) REFERENCES job_postings(job_id)
);
CREATE INDEX IF NOT EXISTS idx_job_evaluation_queue_status
    ON job_evaluation_queue(status, priority, eligible_at);
CREATE INDEX IF NOT EXISTS idx_job_evaluation_queue_lease
    ON job_evaluation_queue(lease_expires_at);

CREATE TABLE IF NOT EXISTS job_evaluation_runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('running','completed','budget_exhausted','failed','cancelled')),
    trigger TEXT NOT NULL DEFAULT 'manual',
    model TEXT NOT NULL DEFAULT 'gpt-5.6-terra',
    reasoning_effort TEXT NOT NULL DEFAULT 'low',
    max_jobs INTEGER,
    estimated_token_limit INTEGER,
    jobs_attempted INTEGER NOT NULL DEFAULT 0,
    jobs_completed INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER,
    output_tokens INTEGER,
    usage_provenance TEXT NOT NULL DEFAULT 'unavailable'
        CHECK (usage_provenance IN ('measured','estimated','unavailable','mixed')),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_job_evaluation_runs_started
    ON job_evaluation_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS job_evaluation_attempts (
    attempt_id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    queue_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    reasoning_effort TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running','completed','failed','escalated')),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    duration_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    usage_provenance TEXT NOT NULL DEFAULT 'unavailable'
        CHECK (usage_provenance IN ('measured','estimated','unavailable')),
    escalation_reason TEXT,
    validation_outcome TEXT,
    error TEXT,
    FOREIGN KEY(run_id) REFERENCES job_evaluation_runs(run_id),
    FOREIGN KEY(queue_id) REFERENCES job_evaluation_queue(queue_id),
    FOREIGN KEY(job_id) REFERENCES job_postings(job_id)
);
CREATE INDEX IF NOT EXISTS idx_job_evaluation_attempts_run
    ON job_evaluation_attempts(run_id, attempt_id);
CREATE INDEX IF NOT EXISTS idx_job_evaluation_attempts_job
    ON job_evaluation_attempts(job_id, attempt_id);
