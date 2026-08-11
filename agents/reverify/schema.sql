-- Audit log of every re-verification check. Own database, independent of
-- leads.db, same reasoning as the other audit stores in this project: a
-- record of what was checked and when shouldn't be at risk if lead data
-- ever gets rebuilt. leads.db itself IS updated in place by this agent
-- (unlike suppression/replies/sends, which never touch it) -- this log is
-- the audit trail of those updates, not a substitute for them.

CREATE TABLE IF NOT EXISTS reverify_log (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id              TEXT NOT NULL,
    business_name         TEXT NOT NULL,
    previous_status       TEXT NOT NULL,
    new_status            TEXT NOT NULL,
    previous_website_url  TEXT,
    new_website_url       TEXT,
    changed               INTEGER NOT NULL,  -- 0/1
    checked_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reverify_place ON reverify_log (place_id);
