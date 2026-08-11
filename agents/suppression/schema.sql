-- Suppression list. Deliberately its own database, not a table in
-- discovery/leads.db -- opt-outs must persist independently of the lead
-- lifecycle (a lead record could be pruned/rebuilt; a suppression must not
-- disappear when that happens). See README.md for the legal basis.

CREATE TABLE IF NOT EXISTS suppressions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_type  TEXT NOT NULL CHECK(contact_type IN ('phone', 'email')),
    contact_value TEXT NOT NULL,   -- normalized: E.164 for phone, lowercase/trimmed for email
    reason        TEXT NOT NULL,   -- e.g. unsubscribe | stop_reply | manual | bounce | legal_request
    source        TEXT,            -- e.g. sms_reply | email_reply | phone_call | manual_entry
    notes         TEXT,
    added_at      TEXT NOT NULL,
    UNIQUE(contact_type, contact_value)
);

CREATE INDEX IF NOT EXISTS idx_suppressions_lookup ON suppressions (contact_type, contact_value);
