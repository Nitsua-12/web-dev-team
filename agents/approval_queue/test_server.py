import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import server

SENDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sends (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_slug       TEXT NOT NULL,
    business_name   TEXT NOT NULL,
    channel         TEXT NOT NULL CHECK(channel IN ('email', 'sms')),
    followup_index  INTEGER NOT NULL,
    sent_at         TEXT NOT NULL,
    UNIQUE(lead_slug, followup_index)
);
"""

# Matches the columns server.py's load_leads_by_slug()/build_queue()/
# get_lead_detail() actually read (agents/discovery/schema.sql), trimmed to
# what's needed here.
LEADS_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    business_name        TEXT NOT NULL,
    city                 TEXT,
    state                TEXT,
    phone                TEXT,
    qualification_status TEXT
);
"""


class AlreadySentTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = Path(tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_false_when_sends_db_file_does_not_exist(self):
        missing_path = self.db_path.parent / "does-not-exist.db"
        with patch("server.SENDS_DB", missing_path):
            self.assertFalse(server.already_sent("some-lead"))

    def test_false_when_file_exists_but_sends_table_does_not(self):
        # Exactly the real-world bug: scheduler_cli.py has never been run,
        # so sends.db exists (SQLite creates it on connect) but has no
        # schema applied yet. This must not raise.
        conn = sqlite3.connect(self.db_path)
        conn.close()
        with patch("server.SENDS_DB", self.db_path):
            self.assertFalse(server.already_sent("some-lead"))

    def test_false_when_table_exists_but_no_matching_row(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SENDS_SCHEMA)
        conn.commit()
        conn.close()
        with patch("server.SENDS_DB", self.db_path):
            self.assertFalse(server.already_sent("some-lead"))

    def test_true_when_initial_send_is_logged(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SENDS_SCHEMA)
        conn.execute(
            "INSERT INTO sends (lead_slug, business_name, channel, followup_index, sent_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("some-lead", "Some Shop", "email", 0, "2026-08-01T00:00:00Z"),
        )
        conn.commit()
        conn.close()
        with patch("server.SENDS_DB", self.db_path):
            self.assertTrue(server.already_sent("some-lead"))

    def test_false_when_only_a_followup_is_logged_not_the_initial_send(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SENDS_SCHEMA)
        conn.execute(
            "INSERT INTO sends (lead_slug, business_name, channel, followup_index, sent_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("some-lead", "Some Shop", "email", 1, "2026-08-05T00:00:00Z"),
        )
        conn.commit()
        conn.close()
        with patch("server.SENDS_DB", self.db_path):
            self.assertFalse(server.already_sent("some-lead"))


class SlugifyTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(server.slugify("Ink & Iron Tattoo", "Austin"), "ink-iron-tattoo-austin")

    def test_empty_inputs_fall_back_to_lead(self):
        self.assertEqual(server.slugify("", ""), "lead")


class LoadLeadsBySlugTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = Path(tmp.name)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(LEADS_SCHEMA)
        conn.execute(
            "INSERT INTO leads (business_name, city, state, phone, qualification_status) VALUES (?, ?, ?, ?, ?)",
            ("Ink & Iron Tattoo", "Austin", "TX", "512-555-0100", "qualified_no_website"),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_keys_dict_by_computed_slug(self):
        with patch("server.LEADS_DB", self.db_path):
            leads = server.load_leads_by_slug()
        self.assertIn("ink-iron-tattoo-austin", leads)
        self.assertEqual(leads["ink-iron-tattoo-austin"]["business_name"], "Ink & Iron Tattoo")


class IsSuppressedTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = Path(tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_false_when_no_phone(self):
        self.assertFalse(server.is_suppressed(None))

    def test_false_when_suppression_db_file_does_not_exist(self):
        missing_path = self.db_path.parent / "does-not-exist.db"
        with patch("server.SUPPRESSION_DB", missing_path):
            self.assertFalse(server.is_suppressed("212-555-0100"))

    def test_true_when_phone_is_suppressed(self):
        server.suppression_db.init_db(str(self.db_path))
        conn = server.suppression_db.get_connection(str(self.db_path))
        server.suppression_db.add_suppression(conn, "phone", "212-555-0100", "manual")
        conn.close()
        with patch("server.SUPPRESSION_DB", self.db_path):
            self.assertTrue(server.is_suppressed("212-555-0100"))

    def test_false_when_phone_not_suppressed(self):
        server.suppression_db.init_db(str(self.db_path))
        with patch("server.SUPPRESSION_DB", self.db_path):
            self.assertFalse(server.is_suppressed("212-555-0100"))


class QueueEnvironmentTestCase(unittest.TestCase):
    """Shared fixture: a full temp environment standing in for ROOT's
    leads.db, drafts/, approvals.db, suppression.db, sends.db, demo output,
    and dossier dirs, with every server.py module constant patched to it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)

        self.leads_db = root / "leads.db"
        conn = sqlite3.connect(self.leads_db)
        conn.executescript(LEADS_SCHEMA)
        conn.commit()
        conn.close()

        self.drafts_dir = root / "drafts"
        self.drafts_dir.mkdir()
        self.approvals_db = root / "approvals.db"
        self.suppression_db_path = root / "suppression.db"
        self.sends_db_path = root / "sends.db"
        self.demo_dir = root / "demo_output"
        self.demo_dir.mkdir()
        self.dossier_dir = root / "dossiers"
        self.dossier_dir.mkdir()

        server.db.init_db(str(self.approvals_db))

        for target, value in [
            ("server.LEADS_DB", self.leads_db),
            ("server.DRAFTS_DIR", self.drafts_dir),
            ("server.APPROVALS_DB", self.approvals_db),
            ("server.SUPPRESSION_DB", self.suppression_db_path),
            ("server.SENDS_DB", self.sends_db_path),
            ("server.DEMO_DIR", self.demo_dir),
            ("server.DOSSIER_DIR", self.dossier_dir),
        ]:
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)

    def add_lead(self, business_name, city="Austin", state="TX", phone="512-555-0100",
                 qualification_status="qualified_no_website"):
        conn = sqlite3.connect(self.leads_db)
        conn.execute(
            "INSERT INTO leads (business_name, city, state, phone, qualification_status) VALUES (?, ?, ?, ?, ?)",
            (business_name, city, state, phone, qualification_status),
        )
        conn.commit()
        conn.close()

    def add_draft(self, slug, subject_line="A modern website concept for your shop"):
        slug_dir = self.drafts_dir / slug
        slug_dir.mkdir()
        (slug_dir / "draft.json").write_text(
            json.dumps({"subject_line": subject_line, "email_body": "Hi there"}), encoding="utf-8"
        )


class BuildQueueTests(QueueEnvironmentTestCase):
    def test_empty_when_drafts_dir_does_not_exist(self):
        missing = Path(self.tmp.name) / "no-drafts-here"
        with patch("server.DRAFTS_DIR", missing):
            self.assertEqual(server.build_queue(), [])

    def test_skips_slug_without_draft_json(self):
        (self.drafts_dir / "no-draft-yet").mkdir()
        self.assertEqual(server.build_queue(), [])

    def test_skips_draft_with_no_matching_lead(self):
        self.add_draft("ghost-lead-austin")
        self.assertEqual(server.build_queue(), [])

    def test_pending_lead_included_with_defaults(self):
        self.add_lead("Ink & Iron Tattoo")
        self.add_draft("ink-iron-tattoo-austin")
        queue = server.build_queue()
        self.assertEqual(len(queue), 1)
        item = queue[0]
        self.assertEqual(item["business_name"], "Ink & Iron Tattoo")
        self.assertEqual(item["status"], "pending")
        self.assertIsNone(item["notes"])
        self.assertFalse(item["suppressed"])
        self.assertFalse(item["already_sent"])

    def test_reflects_recorded_decision(self):
        self.add_lead("Ink & Iron Tattoo")
        self.add_draft("ink-iron-tattoo-austin")
        conn = server.db.get_connection(str(self.approvals_db))
        server.db.record_decision(conn, "ink-iron-tattoo-austin", "Ink & Iron Tattoo", "approved", notes="looks good")
        conn.close()
        item = server.build_queue()[0]
        self.assertEqual(item["status"], "approved")
        self.assertEqual(item["notes"], "looks good")


class GetLeadDetailTests(QueueEnvironmentTestCase):
    def test_missing_draft_returns_error(self):
        self.assertEqual(server.get_lead_detail("nonexistent-slug"), {"error": "not found"})

    def test_full_detail_for_known_lead(self):
        self.add_lead("Ink & Iron Tattoo", phone="512-555-0100", qualification_status="qualified_no_website")
        self.add_draft("ink-iron-tattoo-austin")
        (self.demo_dir / "ink-iron-tattoo-austin").mkdir()
        dossier_slug_dir = self.dossier_dir / "ink-iron-tattoo-austin"
        dossier_slug_dir.mkdir()
        (dossier_slug_dir / "dossier.md").write_text("# Dossier", encoding="utf-8")

        detail = server.get_lead_detail("ink-iron-tattoo-austin")
        self.assertEqual(detail["business_name"], "Ink & Iron Tattoo")
        self.assertEqual(detail["qualification_status"], "qualified_no_website")
        self.assertEqual(detail["status"], "pending")
        self.assertTrue(detail["demo_exists"])
        self.assertTrue(detail["dossier_exists"])

    def test_draft_exists_but_lead_missing_from_leads_db(self):
        self.add_draft("orphan-slug")
        detail = server.get_lead_detail("orphan-slug")
        self.assertEqual(detail["business_name"], "orphan-slug")
        self.assertIsNone(detail["qualification_status"])
        self.assertFalse(detail["suppressed"])
        self.assertFalse(detail["demo_exists"])
        self.assertFalse(detail["dossier_exists"])


class HandlerHTTPTests(QueueEnvironmentTestCase):
    """Live-server tests -- the actual HTTP routing in do_GET/do_POST was
    entirely untested before this. Binds Handler to a real ephemeral port
    and drives it with real HTTP requests rather than calling methods
    directly, since BaseHTTPRequestHandler's request-line/header parsing is
    part of what's being verified."""

    def setUp(self):
        super().setUp()
        static_dir = Path(self.tmp.name) / "static"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("<html>queue</html>", encoding="utf-8")
        (static_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")
        (static_dir / "style.css").write_text("body { color: black; }", encoding="utf-8")
        p = patch("server.STATIC_DIR", static_dir)
        p.start()
        self.addCleanup(p.stop)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown_server)

    def _shutdown_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def _post(self, path, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(payload).encode("utf-8")
        conn.request("POST", path, body=body, headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        })
        resp = conn.getresponse()
        resp_body = resp.read()
        conn.close()
        return resp.status, resp_body

    def test_get_root_serves_index_html(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"queue", body)

    def test_get_index_html_explicit_path(self):
        status, body = self._get("/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"queue", body)

    def test_get_app_js(self):
        status, body = self._get("/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b"console.log", body)

    def test_get_style_css(self):
        status, _ = self._get("/style.css")
        self.assertEqual(status, 200)

    def test_get_root_404_when_index_html_missing(self):
        empty_static = Path(self.tmp.name) / "empty_static"
        empty_static.mkdir()
        with patch("server.STATIC_DIR", empty_static):
            status, _ = self._get("/")
        self.assertEqual(status, 404)

    def test_get_unknown_path_404(self):
        status, _ = self._get("/nonexistent")
        self.assertEqual(status, 404)

    def test_get_api_queue_returns_json_list(self):
        self.add_lead("Ink & Iron Tattoo")
        self.add_draft("ink-iron-tattoo-austin")
        status, body = self._get("/api/queue")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["business_name"], "Ink & Iron Tattoo")

    def test_get_api_lead_detail(self):
        self.add_lead("Ink & Iron Tattoo")
        self.add_draft("ink-iron-tattoo-austin")
        status, body = self._get("/api/lead/ink-iron-tattoo-austin")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["business_name"], "Ink & Iron Tattoo")

    def test_get_api_lead_detail_not_found_is_200_with_error_body(self):
        status, body = self._get("/api/lead/nonexistent")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"error": "not found"})

    def test_post_decide_records_approval(self):
        self.add_lead("Ink & Iron Tattoo")
        self.add_draft("ink-iron-tattoo-austin")
        status, body = self._post("/api/decide", {
            "slug": "ink-iron-tattoo-austin",
            "business_name": "Ink & Iron Tattoo",
            "status": "approved",
            "notes": "go ahead",
        })
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})

        conn = server.db.get_connection(str(self.approvals_db))
        decision = server.db.get_decision(conn, "ink-iron-tattoo-austin")
        conn.close()
        self.assertEqual(decision["status"], "approved")
        self.assertEqual(decision["notes"], "go ahead")

    def test_post_reset_removes_existing_decision(self):
        conn = server.db.get_connection(str(self.approvals_db))
        server.db.record_decision(conn, "ink-iron-tattoo-austin", "Ink & Iron Tattoo", "rejected")
        conn.close()

        status, body = self._post("/api/reset", {"slug": "ink-iron-tattoo-austin"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True, "removed": True})

    def test_post_reset_no_matching_decision(self):
        status, body = self._post("/api/reset", {"slug": "no-such-slug"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True, "removed": False})

    def test_post_unknown_path_404(self):
        status, _ = self._post("/api/nonexistent", {})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
