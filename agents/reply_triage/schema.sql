-- Communication log. Own database, independent of leads.db, for the same
-- reason suppression.db is independent: this is a record of what actually
-- happened, and shouldn't be at risk if lead data ever gets rebuilt.

CREATE TABLE IF NOT EXISTS replies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_slug       TEXT NOT NULL,
    business_name   TEXT NOT NULL,
    channel         TEXT NOT NULL CHECK(channel IN ('email', 'sms', 'phone_call')),
    raw_text        TEXT NOT NULL,
    classification  TEXT NOT NULL,  -- opt_out | interested | not_interested | question | unclear
    summary         TEXT,
    action_taken    TEXT,
    received_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_replies_lead ON replies (lead_slug);
