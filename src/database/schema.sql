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
    source_board TEXT,
    discovery_run_id TEXT,
    keyword_score REAL,
    matched_keywords TEXT,
    evaluated_at TEXT,
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
