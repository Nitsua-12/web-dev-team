"""Funnel aggregation across sends -> replies -> outcomes. Shared by
outcomes_cli.py's `report` command and the Dossier agent, so there is one
computation, not two that could drift apart.

Every source is optional -- if a sibling agent has never been run, its
database file won't exist yet, and that source just contributes zero
rather than erroring. A fresh install of this whole pipeline should be
able to call compute_funnel() safely on day one.
"""

import sqlite3
from pathlib import Path

MEANINGFUL_SAMPLE_SIZE = 5  # below this, treat any rate as directional at best, not a real number


def _query_count(db_path: Path, sql: str, params: tuple = ()) -> int:
    if not Path(db_path).exists():
        return 0
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _query_all(db_path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    if not Path(db_path).exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def compute_funnel(sends_db: Path, replies_db: Path, outcomes_db: Path) -> dict:
    total_sent = _query_count(sends_db, "SELECT COUNT(DISTINCT lead_slug) FROM sends WHERE followup_index = 0")
    total_replied = _query_count(replies_db, "SELECT COUNT(DISTINCT lead_slug) FROM replies")

    reply_breakdown = {
        row[0]: row[1]
        for row in _query_all(replies_db, "SELECT classification, COUNT(DISTINCT lead_slug) FROM replies GROUP BY classification")
    }

    outcome_breakdown = {
        row[0]: row[1]
        for row in _query_all(outcomes_db, "SELECT outcome, COUNT(*) FROM outcomes GROUP BY outcome")
    }
    total_outcomes = sum(outcome_breakdown.values())
    won = outcome_breakdown.get("won", 0)

    avg_won_rows = _query_all(outcomes_db, "SELECT AVG(closed_value) FROM outcomes WHERE outcome = 'won' AND closed_value IS NOT NULL")
    avg_won_value = avg_won_rows[0][0] if avg_won_rows and avg_won_rows[0][0] is not None else None

    return {
        "total_sent": total_sent,
        "total_replied": total_replied,
        "reply_breakdown": reply_breakdown,
        "total_outcomes_recorded": total_outcomes,
        "outcome_breakdown": outcome_breakdown,
        "won_count": won,
        "avg_won_value": avg_won_value,
        "reply_sample_meaningful": total_sent >= MEANINGFUL_SAMPLE_SIZE,
        "outcome_sample_meaningful": total_outcomes >= MEANINGFUL_SAMPLE_SIZE,
    }
