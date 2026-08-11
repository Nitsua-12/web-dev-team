-- Final deal outcomes, recorded by the human after they take over from
-- the Sales Handoff Dossier. Own database, independent of leads.db, same
-- reasoning as every other audit store in this project.

CREATE TABLE IF NOT EXISTS outcomes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_slug     TEXT NOT NULL,
    business_name TEXT NOT NULL,
    outcome       TEXT NOT NULL CHECK(outcome IN ('won', 'lost', 'no_response', 'ongoing')),
    closed_value  REAL,   -- actual deal size in dollars, if won -- the real number the
                          -- Dossier agent's budget estimate should eventually calibrate against
    notes         TEXT,
    recorded_at   TEXT NOT NULL,
    UNIQUE(lead_slug)
);
