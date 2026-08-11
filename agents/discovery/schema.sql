CREATE TABLE IF NOT EXISTS search_cells (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    label         TEXT UNIQUE NOT NULL,   -- e.g. "Austin, TX"
    state         TEXT NOT NULL,
    lat           REAL NOT NULL,
    lng           REAL NOT NULL,
    radius_m      INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | done | error
    result_count  INTEGER,
    run_at        TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    google_place_id     TEXT UNIQUE NOT NULL,
    business_name       TEXT NOT NULL,
    formatted_address    TEXT,
    city                TEXT,
    state               TEXT,
    zip                 TEXT,
    phone               TEXT,
    website_url         TEXT,
    has_website         INTEGER NOT NULL DEFAULT 0,   -- 0/1
    website_status      TEXT NOT NULL DEFAULT 'unknown', -- none | outdated | modern | unknown | error
    website_signals     TEXT,                          -- JSON blob of heuristic findings
    qualification_status TEXT NOT NULL DEFAULT 'needs_review',
        -- qualified_no_website | qualified_outdated | disqualified_modern | needs_review | error
    discovery_source    TEXT NOT NULL DEFAULT 'google_places',
    search_cell         TEXT,                          -- FK-ish, references search_cells.label
    discovered_at       TEXT NOT NULL,
    raw_places_json     TEXT,
    audit_status        TEXT NOT NULL DEFAULT 'not_run',
    audit_score         INTEGER,
    audit_signals       TEXT,
    audit_run_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_qualification ON leads (qualification_status);
CREATE INDEX IF NOT EXISTS idx_leads_state ON leads (state);
