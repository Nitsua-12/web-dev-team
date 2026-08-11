-- Send tracking. Own database, independent of leads.db and drafts/, for
-- the same reason suppression.db and replies.db are independent: this is
-- a record of what actually happened and shouldn't be at risk if lead or
-- draft data ever gets rebuilt.
--
-- followup_index 0 = the initial email/SMS; 1, 2, ... = each follow-up in
-- the order Outreach generated them. day_offset (in draft.json) is always
-- relative to the followup_index=0 send, per the Outreach agent's schema.

CREATE TABLE IF NOT EXISTS sends (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_slug       TEXT NOT NULL,
    business_name   TEXT NOT NULL,
    channel         TEXT NOT NULL CHECK(channel IN ('email', 'sms')),
    followup_index  INTEGER NOT NULL,  -- 0 = initial, 1+ = follow-up N
    sent_at         TEXT NOT NULL,     -- ISO date this was actually sent
    UNIQUE(lead_slug, followup_index)
);

CREATE INDEX IF NOT EXISTS idx_sends_lead ON sends (lead_slug);
