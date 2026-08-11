-- Approval decisions. Own database, independent of leads.db and drafts/,
-- same reasoning as every other audit store in this project.
--
-- "Pending" is not a stored state -- it's the absence of a row. Only
-- approved/rejected get recorded here, so a lead with no decision yet is
-- simply not present in this table.

CREATE TABLE IF NOT EXISTS approvals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_slug     TEXT NOT NULL,
    business_name TEXT NOT NULL,
    status        TEXT NOT NULL CHECK(status IN ('approved', 'rejected')),
    notes         TEXT,
    decided_at    TEXT NOT NULL,
    UNIQUE(lead_slug)
);
