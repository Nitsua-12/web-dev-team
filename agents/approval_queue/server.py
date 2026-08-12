"""Approval Queue -- local web UI for reviewing and approving/rejecting
outreach drafts before anything is ever sent. This is the literal
review-and-approval step required by the original project brief; before
this, "review" meant a human opening markdown files by hand.

Binds to 127.0.0.1 only -- this is a local, single-user tool and is never
meant to be reachable from the network.

No pip dependencies. Python's built-in http.server, matching every other
stdlib-only agent in this project (suppression, scheduler, outcomes).

Usage:
    python server.py
    (opens http://127.0.0.1:8420 automatically)
"""

import importlib.util
import json
import re
import sqlite3
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).parent.parent
db = _load_module("approval_db_module", Path(__file__).parent / "db.py")
suppression_db = _load_module("suppression_db_module", ROOT / "suppression" / "db.py")

LEADS_DB = ROOT / "discovery" / "leads.db"
DRAFTS_DIR = ROOT / "outreach" / "drafts"
SUPPRESSION_DB = ROOT / "suppression" / "suppression.db"
SENDS_DB = ROOT / "scheduler" / "sends.db"
DEMO_DIR = ROOT / "website_demo" / "output"
DOSSIER_DIR = ROOT / "dossier" / "dossiers"
APPROVALS_DB = Path(__file__).parent / "approvals.db"
STATIC_DIR = Path(__file__).parent / "static"

HOST = "127.0.0.1"
PORT = 8420


def slugify(business_name: str, city: str) -> str:
    raw = f"{business_name}-{city}"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or "lead"


def load_leads_by_slug() -> dict:
    conn = sqlite3.connect(LEADS_DB)
    conn.row_factory = sqlite3.Row
    leads = {}
    for row in conn.execute("SELECT * FROM leads"):
        leads[slugify(row["business_name"], row["city"] or "")] = row
    conn.close()
    return leads


def is_suppressed(phone: str | None) -> bool:
    if not phone or not SUPPRESSION_DB.exists():
        return False
    conn = suppression_db.get_connection(str(SUPPRESSION_DB))
    result = suppression_db.is_suppressed(conn, "phone", phone)
    conn.close()
    return result


def already_sent(slug: str) -> bool:
    if not SENDS_DB.exists():
        return False
    conn = sqlite3.connect(SENDS_DB)
    try:
        row = conn.execute("SELECT 1 FROM sends WHERE lead_slug = ? AND followup_index = 0", (slug,)).fetchone()
    except sqlite3.OperationalError:
        # sends.db exists as a file but scheduler_cli.py has never actually
        # been run yet, so its schema was never applied -- same as "no
        # sends have happened," not an error (matches how outcomes/stats.py
        # treats a sibling agent's not-yet-initialized database: it
        # contributes zero, it doesn't crash the caller).
        row = None
    finally:
        conn.close()
    return row is not None


def build_queue() -> list[dict]:
    if not DRAFTS_DIR.exists():
        return []
    leads_by_slug = load_leads_by_slug()
    approvals_conn = db.get_connection(str(APPROVALS_DB))
    items = []
    for slug_dir in sorted(DRAFTS_DIR.iterdir()):
        draft_json = slug_dir / "draft.json"
        if not draft_json.exists():
            continue
        slug = slug_dir.name
        lead = leads_by_slug.get(slug)
        if lead is None:
            continue
        draft = json.loads(draft_json.read_text(encoding="utf-8"))
        decision = db.get_decision(approvals_conn, slug)
        items.append({
            "slug": slug,
            "business_name": lead["business_name"],
            "city": lead["city"],
            "state": lead["state"],
            "subject": draft["subject_line"],
            "status": decision["status"] if decision else "pending",
            "notes": decision["notes"] if decision else None,
            "suppressed": is_suppressed(lead["phone"]),
            "already_sent": already_sent(slug),
        })
    approvals_conn.close()
    return items


def get_lead_detail(slug: str) -> dict:
    slug_dir = DRAFTS_DIR / slug
    draft_json = slug_dir / "draft.json"
    if not draft_json.exists():
        return {"error": "not found"}

    draft = json.loads(draft_json.read_text(encoding="utf-8"))
    approvals_conn = db.get_connection(str(APPROVALS_DB))
    decision = db.get_decision(approvals_conn, slug)
    approvals_conn.close()

    lead = load_leads_by_slug().get(slug)

    return {
        "slug": slug,
        "business_name": lead["business_name"] if lead else slug,
        "city": lead["city"] if lead else None,
        "state": lead["state"] if lead else None,
        "phone": lead["phone"] if lead else None,
        "qualification_status": lead["qualification_status"] if lead else None,
        "draft": draft,
        "status": decision["status"] if decision else "pending",
        "notes": decision["notes"] if decision else None,
        "suppressed": is_suppressed(lead["phone"]) if lead else False,
        "already_sent": already_sent(slug),
        "demo_exists": (DEMO_DIR / slug).exists(),
        "dossier_exists": (DOSSIER_DIR / slug / "dossier.md").exists(),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # quiet console; real errors still propagate as 500s

    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_response(404)
            self.end_headers()
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/app.js":
            self._send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
        elif path == "/style.css":
            self._send_file(STATIC_DIR / "style.css", "text/css; charset=utf-8")
        elif path == "/api/queue":
            self._send_json(build_queue())
        elif path.startswith("/api/lead/"):
            self._send_json(get_lead_detail(path[len("/api/lead/"):]))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/decide":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            conn = db.get_connection(str(APPROVALS_DB))
            db.record_decision(conn, body["slug"], body.get("business_name", ""), body["status"], body.get("notes"))
            conn.close()
            self._send_json({"ok": True})
        elif path == "/api/reset":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            conn = db.get_connection(str(APPROVALS_DB))
            removed = db.reset_decision(conn, body["slug"])
            conn.close()
            self._send_json({"ok": True, "removed": removed})
        else:
            self.send_response(404)
            self.end_headers()


def main() -> None:
    db.init_db(str(APPROVALS_DB))
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Approval Queue running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
