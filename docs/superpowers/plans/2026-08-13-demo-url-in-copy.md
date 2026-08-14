# Real Demo URL in Outreach & Dossier Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `agents/outreach` and `agents/dossier` awareness of a lead's real, live demo URL (once hosting exists for that lead) and use it in generated copy/rendered output instead of vague or stale "not yet hosted" language.

**Architecture:** Both agents independently gain the same small pure helper (`demo_url_for()`) that returns a real URL only when a lead's demo folder exists locally AND hosting is configured (`DEMO_SITE_BASE_URL` set) — folder-exists alone is not enough, since a demo can be generated without ever being deployed. That URL (or its absence) flows into each agent's Claude prompt as a known fact, and into dossier's rendered markdown directly.

**Tech Stack:** Python 3 (stdlib `unittest`), no new dependencies.

## Global Constraints

- No new Python dependency in either agent.
- `demo_url_for(business_name: str, city: str, demo_dir: Path, site_base_url: str | None) -> str | None` — identical signature and behavior in both `agents/outreach/generate_drafts.py` and `agents/dossier/generate_dossier.py`, each its own copy (no cross-agent import — every agent in this project is self-contained, own `venv`/`.env`/`README`, see `ARCHITECTURE.md` §15).
- URL construction: `f"{site_base_url.rstrip('/')}/{slug}/"` — the identical scheme `agents/website_demo/generate_demo.py`'s `page_url()` already uses.
- The SMS body must never include the demo link, regardless of whether one exists (confirmed with the user: 320-character budget including the mandatory opt-out line, and a bare link in a cold text reads more like spam/phishing than in a cold email).
- Never fabricate or imply a link exists when `demo_url_for()` returns `None` — this applies whether no demo exists yet, or one exists but isn't hosted.
- Tests use Python's stdlib `unittest`, matching every other agent in this project. Run via that agent's own venv: `agents/outreach/.venv/Scripts/python.exe` / `agents/dossier/.venv/Scripts/python.exe`.
- Full design context: [docs/superpowers/specs/2026-08-13-demo-url-in-copy-design.md](../specs/2026-08-13-demo-url-in-copy-design.md).

---

## Task 1: `demo_url_for()` + `demo_status_line()` in outreach

**Files:**
- Modify: `agents/outreach/generate_drafts.py`
- Test: `agents/outreach/test_generate_drafts.py` (new file)

**Interfaces:**
- Produces: `demo_url_for(business_name: str, city: str, demo_dir: Path, site_base_url: str | None) -> str | None`, `demo_status_line(demo_exists: bool, demo_url: str | None) -> str` (both module-level functions in `generate_drafts.py`), `DEFAULT_DEMO_DIR: Path` (module-level constant, value `Path(__file__).parent.parent / "website_demo" / "output"`)

- [ ] **Step 1: Write the failing tests**

Create `agents/outreach/test_generate_drafts.py`:

```python
import tempfile
import unittest
from pathlib import Path

from generate_drafts import demo_url_for, demo_status_line


class DemoUrlForTests(unittest.TestCase):
    def test_no_folder_no_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo_dir = Path(tmp)
            result = demo_url_for("Ink & Iron Tattoo", "Austin", demo_dir, "https://example.pages.dev")
            self.assertIsNone(result)

    def test_folder_exists_no_base_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo_dir = Path(tmp)
            (demo_dir / "ink-iron-tattoo-austin").mkdir()
            result = demo_url_for("Ink & Iron Tattoo", "Austin", demo_dir, None)
            self.assertIsNone(result)

    def test_folder_exists_and_base_url_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo_dir = Path(tmp)
            (demo_dir / "ink-iron-tattoo-austin").mkdir()
            result = demo_url_for("Ink & Iron Tattoo", "Austin", demo_dir, "https://example.pages.dev")
            self.assertEqual(result, "https://example.pages.dev/ink-iron-tattoo-austin/")

    def test_base_url_trailing_slash_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo_dir = Path(tmp)
            (demo_dir / "ink-iron-tattoo-austin").mkdir()
            result = demo_url_for("Ink & Iron Tattoo", "Austin", demo_dir, "https://example.pages.dev/")
            self.assertEqual(result, "https://example.pages.dev/ink-iron-tattoo-austin/")


class DemoStatusLineTests(unittest.TestCase):
    def test_no_demo_at_all(self):
        result = demo_status_line(demo_exists=False, demo_url=None)
        self.assertEqual(result, "No concept demo has been built for this shop yet.")

    def test_demo_exists_not_hosted(self):
        result = demo_status_line(demo_exists=True, demo_url=None)
        self.assertEqual(
            result,
            "A concept demo has been built for this shop but isn't hosted/live yet -- do not include a link.",
        )

    def test_demo_live(self):
        result = demo_status_line(demo_exists=True, demo_url="https://example.pages.dev/ink-iron-tattoo-austin/")
        self.assertEqual(
            result,
            "A concept demo is live for this shop at https://example.pages.dev/ink-iron-tattoo-austin/ "
            "-- reference this exact URL in the email (and follow-ups) when inviting them to look.",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd agents/outreach && ./.venv/Scripts/python.exe -m unittest test_generate_drafts.py -v
```
Expected: FAIL/ERROR — `ImportError: cannot import name 'demo_url_for' from 'generate_drafts'`

- [ ] **Step 3: Add `DEFAULT_DEMO_DIR` constant**

In `agents/outreach/generate_drafts.py`, find:
```python
MODEL = "claude-sonnet-5"
DEFAULT_DB = Path(__file__).parent.parent / "discovery" / "leads.db"
DEFAULT_SUPPRESSION_DB = Path(__file__).parent.parent / "suppression" / "suppression.db"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "drafts"
QUALIFYING_STATUSES = ("qualified_no_website", "qualified_outdated")
```

Replace with:
```python
MODEL = "claude-sonnet-5"
DEFAULT_DB = Path(__file__).parent.parent / "discovery" / "leads.db"
DEFAULT_SUPPRESSION_DB = Path(__file__).parent.parent / "suppression" / "suppression.db"
DEFAULT_DEMO_DIR = Path(__file__).parent.parent / "website_demo" / "output"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "drafts"
QUALIFYING_STATUSES = ("qualified_no_website", "qualified_outdated")
```

- [ ] **Step 4: Implement `demo_url_for()` and `demo_status_line()`**

In `agents/outreach/generate_drafts.py`, find the `slugify()` function:
```python
def slugify(business_name: str, city: str) -> str:
    raw = f"{business_name}-{city}"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or "lead"
```

Insert these two new functions immediately **after** it (before `OUTPUT_SCHEMA`):
```python
def demo_url_for(business_name: str, city: str, demo_dir: Path, site_base_url: str | None) -> str | None:
    """Real, live URL for a lead's demo, or None if it isn't actually live.
    Both conditions must hold: the demo was generated locally (demo_dir/<slug>
    exists) AND hosting is configured (site_base_url set) -- folder-exists
    alone isn't enough, since a demo can be generated without ever being
    deployed. See agents/website_demo/deploy.py for the actual hosting step."""
    if not site_base_url:
        return None
    slug = slugify(business_name, city)
    if not (demo_dir / slug).exists():
        return None
    return f"{site_base_url.rstrip('/')}/{slug}/"


def demo_status_line(demo_exists: bool, demo_url: str | None) -> str:
    """Demo status: three real states, not a bool -- see demo_url_for()."""
    if demo_url:
        return (
            f"A concept demo is live for this shop at {demo_url} -- reference "
            "this exact URL in the email (and follow-ups) when inviting them to look."
        )
    if demo_exists:
        return "A concept demo has been built for this shop but isn't hosted/live yet -- do not include a link."
    return "No concept demo has been built for this shop yet."
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd agents/outreach && ./.venv/Scripts/python.exe -m unittest test_generate_drafts.py -v
```
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add agents/outreach/generate_drafts.py agents/outreach/test_generate_drafts.py
git commit -m "Add demo_url_for()/demo_status_line() helpers to outreach"
```

---

## Task 2: Wire the demo URL into outreach's prompt and CLI

**Files:**
- Modify: `agents/outreach/generate_drafts.py`
- Modify: `agents/outreach/.env.example`

**Interfaces:**
- Consumes: `demo_url_for()`, `demo_status_line()`, `DEFAULT_DEMO_DIR` (Task 1)
- Produces: `build_user_prompt(lead: sqlite3.Row, demo_exists: bool, demo_url: str | None) -> str` (signature gains two params), `generate_draft(client: Anthropic, lead: sqlite3.Row, demo_exists: bool, demo_url: str | None) -> dict` (signature gains two params)

This task has no new automated tests of its own — the remaining changes are prompt text and CLI/main() wiring that need a real Claude call to meaningfully verify (see Task 5). Run the existing suite to confirm no regressions.

- [ ] **Step 1: Update `SYSTEM_PROMPT`**

In `agents/outreach/generate_drafts.py`, find:
```python
The pitch: a modern website concept has already been put together for this \
specific shop, and the message invites them to take a look. Do NOT claim the \
site is live or already fully built with their real photos/content -- it's a \
concept/demo, and overclaiming here is a real problem, not a nitpick. Frame \
it as "here's what we put together for you" / "want to see it" rather than \
"your new site is ready."

Tone: direct, low-pressure, plainly written -- like a local business owner \
reaching out, not a marketing agency. No exclamation-point energy, no fake \
urgency, no "act now" language.
```

Replace with:
```python
The pitch: a modern website concept has already been put together for this \
specific shop, and the message invites them to take a look. Do NOT claim the \
site is live or already fully built with their real photos/content -- it's a \
concept/demo, and overclaiming here is a real problem, not a nitpick. Frame \
it as "here's what we put together for you" / "want to see it" rather than \
"your new site is ready."

When you're told a concept demo is live at a specific URL, invite them to \
look at it using that exact URL, reproduced exactly as given -- do not \
alter, shorten, retype, or paraphrase it. Use it in the initial email body \
and in both follow-up emails. Never include a link, or imply one exists, \
in the SMS -- keep the SMS pitch link-free regardless of whether a demo is \
live, mentioning only that a concept has been put together and inviting a \
reply.

If no demo is live yet (either none has been built, or it exists but isn't \
hosted), do not include a link or imply one exists anywhere -- keep the \
"take a look" language general (e.g. inviting them to reply to see it) \
rather than pointing at something that doesn't exist yet.

Tone: direct, low-pressure, plainly written -- like a local business owner \
reaching out, not a marketing agency. No exclamation-point energy, no fake \
urgency, no "act now" language.
```

- [ ] **Step 2: Update `build_user_prompt()`**

In `agents/outreach/generate_drafts.py`, find:
```python
def build_user_prompt(lead: sqlite3.Row) -> str:
    qualification = lead["qualification_status"]
    if qualification == "qualified_no_website":
        situation = "This shop has no website at all listed on Google."
    else:
        issues = describe_website_issues(lead["website_signals"])
        if issues:
            situation = f"This shop has a website ({lead['website_url']}). An automated check found: {'; '.join(issues)}."
        else:
            situation = f"This shop has a website ({lead['website_url']}), but it's outdated."

    return f"""Shop name: {lead['business_name']}
City/State: {lead['city']}, {lead['state']}
Phone (from Google listing, public): {lead['phone']}
Situation: {situation}

Write the outreach copy now."""
```

Replace with:
```python
def build_user_prompt(lead: sqlite3.Row, demo_exists: bool, demo_url: str | None) -> str:
    qualification = lead["qualification_status"]
    if qualification == "qualified_no_website":
        situation = "This shop has no website at all listed on Google."
    else:
        issues = describe_website_issues(lead["website_signals"])
        if issues:
            situation = f"This shop has a website ({lead['website_url']}). An automated check found: {'; '.join(issues)}."
        else:
            situation = f"This shop has a website ({lead['website_url']}), but it's outdated."

    return f"""Shop name: {lead['business_name']}
City/State: {lead['city']}, {lead['state']}
Phone (from Google listing, public): {lead['phone']}
Situation: {situation}
Demo status: {demo_status_line(demo_exists, demo_url)}

Write the outreach copy now."""
```

- [ ] **Step 3: Update `generate_draft()`**

In `agents/outreach/generate_drafts.py`, find:
```python
def generate_draft(client: Anthropic, lead: sqlite3.Row) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        # effort=medium: verified via a live medium-vs-high comparison (no tools
        # involved here, so lower effort just means less output, no downside
        # found) -- ~20% fewer output tokens, no quality loss observed. See
        # ARCHITECTURE.md Section 12. Do NOT copy this to the Dossier agent --
        # its web_search tool made medium effort MORE expensive there, not less.
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}, "effort": "medium"},
        messages=[{"role": "user", "content": build_user_prompt(lead)}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
```

Replace with:
```python
def generate_draft(client: Anthropic, lead: sqlite3.Row, demo_exists: bool, demo_url: str | None) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        # effort=medium: verified via a live medium-vs-high comparison (no tools
        # involved here, so lower effort just means less output, no downside
        # found) -- ~20% fewer output tokens, no quality loss observed. See
        # ARCHITECTURE.md Section 12. Do NOT copy this to the Dossier agent --
        # its web_search tool made medium effort MORE expensive there, not less.
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}, "effort": "medium"},
        messages=[{"role": "user", "content": build_user_prompt(lead, demo_exists, demo_url)}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
```

- [ ] **Step 4: Read `DEMO_SITE_BASE_URL` and compute per-lead values in `main()`**

In `agents/outreach/generate_drafts.py`, find:
```python
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY not set -- add it to .env")

    client = Anthropic(api_key=api_key)
    args.output_dir.mkdir(parents=True, exist_ok=True)
```

Replace with:
```python
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY not set -- add it to .env")

    site_base_url = os.environ.get("DEMO_SITE_BASE_URL", "").strip() or None

    client = Anthropic(api_key=api_key)
    args.output_dir.mkdir(parents=True, exist_ok=True)
```

Then find:
```python
        if lead["phone"] and suppression_db.is_suppressed(suppression_conn, "phone", lead["phone"]):
            suppressed += 1
            print(f"  {lead['business_name']} -> SKIPPED (phone is on the suppression list)")
            continue

        draft = generate_draft(client, lead)
```

Replace with:
```python
        if lead["phone"] and suppression_db.is_suppressed(suppression_conn, "phone", lead["phone"]):
            suppressed += 1
            print(f"  {lead['business_name']} -> SKIPPED (phone is on the suppression list)")
            continue

        demo_exists = (args.demo_dir / slug).exists()
        demo_url = demo_url_for(lead["business_name"], lead["city"] or "", args.demo_dir, site_base_url)

        draft = generate_draft(client, lead, demo_exists, demo_url)
```

- [ ] **Step 5: Add the `--demo-dir` CLI argument**

In `agents/outreach/generate_drafts.py`, find:
```python
    parser.add_argument("--suppression-db", type=Path, default=DEFAULT_SUPPRESSION_DB, help="Path to the suppression list db")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Where to write drafts")
```

Replace with:
```python
    parser.add_argument("--suppression-db", type=Path, default=DEFAULT_SUPPRESSION_DB, help="Path to the suppression list db")
    parser.add_argument("--demo-dir", type=Path, default=DEFAULT_DEMO_DIR, help="Path to Website Demo Generation Agent's output directory")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Where to write drafts")
```

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run:
```bash
cd agents/outreach && ./.venv/Scripts/python.exe -m unittest discover -v
```
Expected: PASS (all 7 tests from Task 1)

- [ ] **Step 7: Add `DEMO_SITE_BASE_URL` to `.env.example`**

In `agents/outreach/.env.example`, find:
```
ANTHROPIC_API_KEY=
```

Replace with:
```
ANTHROPIC_API_KEY=
# Optional. Same value as agents/website_demo/.env's DEMO_SITE_BASE_URL --
# e.g. https://tattoo-outreach-demos.pages.dev. Leave blank if demo hosting
# isn't set up yet; the generated copy simply won't include a link.
DEMO_SITE_BASE_URL=
```

- [ ] **Step 8: Commit**

```bash
git add agents/outreach/generate_drafts.py agents/outreach/.env.example
git commit -m "Wire the real demo URL into outreach's prompt and CLI"
```

---

## Task 3: `demo_url_for()` + `demo_status_line()` in dossier

**Files:**
- Modify: `agents/dossier/generate_dossier.py`
- Test: `agents/dossier/test_generate_dossier.py` (new file)

**Interfaces:**
- Produces: `demo_url_for(business_name: str, city: str, demo_dir: Path, site_base_url: str | None) -> str | None`, `demo_status_line(demo_exists: bool, demo_url: str | None) -> str` (both module-level functions in `generate_dossier.py`)

Note: `generate_dossier.py` already has `DEFAULT_DEMO_DIR` (see line 55) -- no new constant needed here, unlike outreach's Task 1.

- [ ] **Step 1: Write the failing tests**

Create `agents/dossier/test_generate_dossier.py`:

```python
import tempfile
import unittest
from pathlib import Path

from generate_dossier import demo_url_for, demo_status_line


class DemoUrlForTests(unittest.TestCase):
    def test_no_folder_no_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo_dir = Path(tmp)
            result = demo_url_for("Ink & Iron Tattoo", "Austin", demo_dir, "https://example.pages.dev")
            self.assertIsNone(result)

    def test_folder_exists_no_base_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo_dir = Path(tmp)
            (demo_dir / "ink-iron-tattoo-austin").mkdir()
            result = demo_url_for("Ink & Iron Tattoo", "Austin", demo_dir, None)
            self.assertIsNone(result)

    def test_folder_exists_and_base_url_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo_dir = Path(tmp)
            (demo_dir / "ink-iron-tattoo-austin").mkdir()
            result = demo_url_for("Ink & Iron Tattoo", "Austin", demo_dir, "https://example.pages.dev")
            self.assertEqual(result, "https://example.pages.dev/ink-iron-tattoo-austin/")

    def test_base_url_trailing_slash_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo_dir = Path(tmp)
            (demo_dir / "ink-iron-tattoo-austin").mkdir()
            result = demo_url_for("Ink & Iron Tattoo", "Austin", demo_dir, "https://example.pages.dev/")
            self.assertEqual(result, "https://example.pages.dev/ink-iron-tattoo-austin/")


class DemoStatusLineTests(unittest.TestCase):
    def test_no_demo_at_all(self):
        result = demo_status_line(demo_exists=False, demo_url=None)
        self.assertEqual(result, "no demo built yet")

    def test_demo_exists_not_hosted(self):
        result = demo_status_line(demo_exists=True, demo_url=None)
        self.assertEqual(result, "a concept demo has been built (not yet hosted/live)")

    def test_demo_live(self):
        result = demo_status_line(demo_exists=True, demo_url="https://example.pages.dev/ink-iron-tattoo-austin/")
        self.assertEqual(result, "a concept demo is live at https://example.pages.dev/ink-iron-tattoo-austin/")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd agents/dossier && ./.venv/Scripts/python.exe -m unittest test_generate_dossier.py -v
```
Expected: FAIL/ERROR — `ImportError: cannot import name 'demo_url_for' from 'generate_dossier'`

- [ ] **Step 3: Implement `demo_url_for()` and `demo_status_line()`**

In `agents/dossier/generate_dossier.py`, find the `slugify()` function:
```python
def slugify(business_name: str, city: str) -> str:
    raw = f"{business_name}-{city}"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or "lead"
```

Insert these two new functions immediately **after** it (before `build_funnel_context`):
```python
def demo_url_for(business_name: str, city: str, demo_dir: Path, site_base_url: str | None) -> str | None:
    """Real, live URL for a lead's demo, or None if it isn't actually live.
    Both conditions must hold: the demo was generated locally (demo_dir/<slug>
    exists) AND hosting is configured (site_base_url set) -- folder-exists
    alone isn't enough, since a demo can be generated without ever being
    deployed. See agents/website_demo/deploy.py for the actual hosting step."""
    if not site_base_url:
        return None
    slug = slugify(business_name, city)
    if not (demo_dir / slug).exists():
        return None
    return f"{site_base_url.rstrip('/')}/{slug}/"


def demo_status_line(demo_exists: bool, demo_url: str | None) -> str:
    """Demo site status: three real states, not a bool -- see demo_url_for()."""
    if demo_url:
        return f"a concept demo is live at {demo_url}"
    if demo_exists:
        return "a concept demo has been built (not yet hosted/live)"
    return "no demo built yet"
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd agents/dossier && ./.venv/Scripts/python.exe -m unittest test_generate_dossier.py -v
```
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/dossier/generate_dossier.py agents/dossier/test_generate_dossier.py
git commit -m "Add demo_url_for()/demo_status_line() helpers to dossier"
```

---

## Task 4: Wire the demo URL into dossier's prompt, rendered output, and CLI

**Files:**
- Modify: `agents/dossier/generate_dossier.py`
- Modify: `agents/dossier/.env.example`

**Interfaces:**
- Consumes: `demo_url_for()`, `demo_status_line()` (Task 3)
- Produces: `build_user_prompt(lead: sqlite3.Row, demo_exists: bool, demo_url: str | None, draft_exists: bool, funnel: dict) -> str` (signature gains `demo_url`, inserted after `demo_exists`), `query_claude(client: Anthropic, lead: sqlite3.Row, demo_exists: bool, demo_url: str | None, draft_exists: bool, funnel: dict) -> dict` (same insertion), `render_markdown(lead: sqlite3.Row, dossier: dict, demo_path: Path | None, demo_url: str | None, draft_path: Path | None) -> str` (signature gains `demo_url`, inserted after `demo_path`)

This task has no new automated tests of its own -- same reasoning as Task 2. Run the existing suite to confirm no regressions.

- [ ] **Step 1: Update `SYSTEM_PROMPT`**

In `agents/dossier/generate_dossier.py`, find:
```python
You may also be given automated site audit findings -- real checks run \
against the shop's actual existing homepage (PageSpeed/Core Web Vitals, \
missing schema markup, no phone number found on the page, etc.), not \
guesses. When present, cite them concretely in your talking points instead \
of generic phrasing like "your website looks outdated" -- a specific, \
real finding is more credible to a salesperson on a call than a vague \
claim."""
```

Replace with:
```python
You may also be given automated site audit findings -- real checks run \
against the shop's actual existing homepage (PageSpeed/Core Web Vitals, \
missing schema markup, no phone number found on the page, etc.), not \
guesses. When present, cite them concretely in your talking points instead \
of generic phrasing like "your website looks outdated" -- a specific, \
real finding is more credible to a salesperson on a call than a vague \
claim.

When the shop has a live, hosted demo (you'll be told the exact URL if \
so), you may mention in your talking points that a live concept site \
exists and can be shared with the shop directly -- a real, useful fact for \
the salesperson. Don't claim it's live if you weren't given a URL."""
```

- [ ] **Step 2: Update `build_user_prompt()`**

In `agents/dossier/generate_dossier.py`, find:
```python
def build_user_prompt(lead: sqlite3.Row, demo_exists: bool, draft_exists: bool, funnel: dict) -> str:
    qualification = lead["qualification_status"]
    if qualification == "qualified_no_website":
        situation = "No website listed on Google."
    else:
        situation = f"Has a website ({lead['website_url']}) but it's outdated.{format_audit_findings(lead)}"

    return f"""Shop name: {lead['business_name']}
City/State: {lead['city']}, {lead['state']}
Phone (public, from Google listing): {lead['phone']}
Address: {lead['formatted_address']}
Situation: {situation}
Demo site status: {"a concept demo has been built (not yet hosted/live)" if demo_exists else "no demo built yet"}
Outreach status: {"a draft outreach email/SMS exists but nothing has been sent" if draft_exists else "no outreach drafted yet"}
{build_funnel_context(funnel)}

Search for public context on this shop if you can find anything real, then prepare the handoff brief."""
```

Replace with:
```python
def build_user_prompt(lead: sqlite3.Row, demo_exists: bool, demo_url: str | None, draft_exists: bool, funnel: dict) -> str:
    qualification = lead["qualification_status"]
    if qualification == "qualified_no_website":
        situation = "No website listed on Google."
    else:
        situation = f"Has a website ({lead['website_url']}) but it's outdated.{format_audit_findings(lead)}"

    return f"""Shop name: {lead['business_name']}
City/State: {lead['city']}, {lead['state']}
Phone (public, from Google listing): {lead['phone']}
Address: {lead['formatted_address']}
Situation: {situation}
Demo site status: {demo_status_line(demo_exists, demo_url)}
Outreach status: {"a draft outreach email/SMS exists but nothing has been sent" if draft_exists else "no outreach drafted yet"}
{build_funnel_context(funnel)}

Search for public context on this shop if you can find anything real, then prepare the handoff brief."""
```

- [ ] **Step 3: Update `query_claude()`**

In `agents/dossier/generate_dossier.py`, find:
```python
def query_claude(client: Anthropic, lead: sqlite3.Row, demo_exists: bool, draft_exists: bool, funnel: dict) -> dict:
    messages = [{"role": "user", "content": build_user_prompt(lead, demo_exists, draft_exists, funnel)}]
```

Replace with:
```python
def query_claude(client: Anthropic, lead: sqlite3.Row, demo_exists: bool, demo_url: str | None, draft_exists: bool, funnel: dict) -> dict:
    messages = [{"role": "user", "content": build_user_prompt(lead, demo_exists, demo_url, draft_exists, funnel)}]
```

(Leave the rest of `query_claude()`'s body -- the `response = client.messages.create(...)` calls and retry-on-`pause_turn` logic -- exactly as it is; only the signature and the `build_user_prompt(...)` call change.)

- [ ] **Step 4: Update `render_markdown()`**

In `agents/dossier/generate_dossier.py`, find:
```python
def render_markdown(lead: sqlite3.Row, dossier: dict, demo_path: Path | None, draft_path: Path | None) -> str:
    lines = [
        f"# Sales Handoff Dossier: {lead['business_name']}",
        "",
        "**For internal use by the human salesperson only.** Estimates below are rough, not authoritative.",
        "",
        "## Lead History",
        "",
        f"- **Business:** {lead['business_name']}",
        f"- **Address:** {lead['formatted_address']}",
        f"- **City/State:** {lead['city']}, {lead['state']}",
        f"- **Phone:** {lead['phone']}",
        f"- **Discovered:** {lead['discovered_at']} (via {lead['discovery_source']}, search cell: {lead['search_cell']})",
        f"- **Qualification:** {lead['qualification_status']}"
        + (f" -- existing site: {lead['website_url']}" if lead["website_url"] else ""),
        "",
        "## Research Summary",
        "",
        dossier["research_summary"],
        "",
        "## Website Demo",
        "",
        f"Demo exists locally at `{demo_path}`." if demo_path else "No demo has been generated for this lead yet.",
        "This is a concept/mockup, not a hosted live site -- see the website_demo agent's README before referencing it as more than that.",
        "",
        "## Communication History",
        "",
        f"Outreach draft exists at `{draft_path}` -- status: **drafted, not reviewed, not sent**." if draft_path else "No outreach has been drafted for this lead yet.",
        "",
        "## Recommended Talking Points",
        "",
    ]
```

Replace with:
```python
def render_markdown(lead: sqlite3.Row, dossier: dict, demo_path: Path | None, demo_url: str | None, draft_path: Path | None) -> str:
    if demo_url:
        demo_lines = [
            f"**Live demo:** {demo_url}",
            "This is a real, hosted concept site -- not the shop's final production "
            "site, and not indexed by search engines unless this lead has already "
            "responded (see the website_demo agent's README's Hosting section).",
        ]
    elif demo_path:
        demo_lines = [
            f"Demo exists locally at `{demo_path}`, not yet hosted/live.",
            "This is a concept/mockup, not a hosted live site -- see the website_demo agent's README before referencing it as more than that.",
        ]
    else:
        demo_lines = ["No demo has been generated for this lead yet."]

    lines = [
        f"# Sales Handoff Dossier: {lead['business_name']}",
        "",
        "**For internal use by the human salesperson only.** Estimates below are rough, not authoritative.",
        "",
        "## Lead History",
        "",
        f"- **Business:** {lead['business_name']}",
        f"- **Address:** {lead['formatted_address']}",
        f"- **City/State:** {lead['city']}, {lead['state']}",
        f"- **Phone:** {lead['phone']}",
        f"- **Discovered:** {lead['discovered_at']} (via {lead['discovery_source']}, search cell: {lead['search_cell']})",
        f"- **Qualification:** {lead['qualification_status']}"
        + (f" -- existing site: {lead['website_url']}" if lead["website_url"] else ""),
        "",
        "## Research Summary",
        "",
        dossier["research_summary"],
        "",
        "## Website Demo",
        "",
        *demo_lines,
        "",
        "## Communication History",
        "",
        f"Outreach draft exists at `{draft_path}` -- status: **drafted, not reviewed, not sent**." if draft_path else "No outreach has been drafted for this lead yet.",
        "",
        "## Recommended Talking Points",
        "",
    ]
```

(The rest of `render_markdown()` -- from the `for point in dossier["talking_points"]:` loop onward -- is unchanged.)

- [ ] **Step 5: Read `DEMO_SITE_BASE_URL` and thread `demo_url` through `main()`**

In `agents/dossier/generate_dossier.py`, find:
```python
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY not set -- add it to .env")

    client = Anthropic(api_key=api_key)
    args.output_dir.mkdir(parents=True, exist_ok=True)
```

Replace with:
```python
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY not set -- add it to .env")

    site_base_url = os.environ.get("DEMO_SITE_BASE_URL", "").strip() or None

    client = Anthropic(api_key=api_key)
    args.output_dir.mkdir(parents=True, exist_ok=True)
```

Then find:
```python
        demo_path = args.demo_dir / slug
        demo_path = demo_path if demo_path.exists() else None
        draft_path = args.drafts_dir / slug / "draft.md"
        draft_path = draft_path if draft_path.exists() else None

        dossier = query_claude(client, lead, demo_path is not None, draft_path is not None, funnel)

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_markdown(lead, dossier, demo_path, draft_path), encoding="utf-8")
```

Replace with:
```python
        demo_path = args.demo_dir / slug
        demo_path = demo_path if demo_path.exists() else None
        demo_url = demo_url_for(lead["business_name"], lead["city"] or "", args.demo_dir, site_base_url)
        draft_path = args.drafts_dir / slug / "draft.md"
        draft_path = draft_path if draft_path.exists() else None

        dossier = query_claude(client, lead, demo_path is not None, demo_url, draft_path is not None, funnel)

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_markdown(lead, dossier, demo_path, demo_url, draft_path), encoding="utf-8")
```

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run:
```bash
cd agents/dossier && ./.venv/Scripts/python.exe -m unittest discover -v
```
Expected: PASS (all 7 tests from Task 3)

- [ ] **Step 7: Add `DEMO_SITE_BASE_URL` to `.env.example`**

In `agents/dossier/.env.example`, find:
```
ANTHROPIC_API_KEY=
```

Replace with:
```
ANTHROPIC_API_KEY=
# Optional. Same value as agents/website_demo/.env's DEMO_SITE_BASE_URL --
# e.g. https://tattoo-outreach-demos.pages.dev. Leave blank if demo hosting
# isn't set up yet; the dossier simply won't show a live link.
DEMO_SITE_BASE_URL=
```

- [ ] **Step 8: Commit**

```bash
git add agents/dossier/generate_dossier.py agents/dossier/.env.example
git commit -m "Wire the real demo URL into dossier's prompt, output, and CLI"
```

---

## Task 5: Real verification against a live demo URL

**This task makes real, billed Anthropic API calls** -- keep it to exactly the two calls described below, both targeted at a single already-known lead, not a batch. `DEMO_SITE_BASE_URL` is a public URL (not a secret), safe to write directly into both `.env` files as part of this task.

**Files:** none (verification only)

- [ ] **Step 1: Set `DEMO_SITE_BASE_URL` in both agents' `.env`**

In `agents/outreach/.env`, add a new line:
```
DEMO_SITE_BASE_URL=https://tattoo-outreach-demos.pages.dev
```

In `agents/dossier/.env`, add the same line.

(If either `.env` file doesn't exist yet, check that agent's `.env.example` from Tasks 2/4 for the full expected format -- both need `ANTHROPIC_API_KEY` set already for the rest of this task to work.)

- [ ] **Step 2: Generate real outreach drafts and inspect the one with a live demo**

Run:
```bash
cd agents/outreach && ./.venv/Scripts/python.exe generate_drafts.py --force
```

This regenerates drafts for all currently-qualified leads (small batch, cheap -- see `ARCHITECTURE.md` §12 for real per-lead token costs). Find the output for the lead with an already-hosted demo (check `agents/website_demo/output/` for which slugs exist, e.g. `addiction-nyc-new-york` if that lead is still qualified) and read its generated `drafts/<slug>/draft.md`.

Confirm:
- The initial email body includes the real URL (`https://tattoo-outreach-demos.pages.dev/<slug>/`), reproduced exactly, not garbled or altered
- Both follow-up emails also include it
- The SMS body does **not** include any URL

For any qualified lead with no demo folder in `agents/website_demo/output/`, confirm its draft does NOT claim or imply a link exists.

- [ ] **Step 3: Generate a real dossier and inspect it**

Run:
```bash
cd agents/dossier && ./.venv/Scripts/python.exe generate_dossier.py --business "<business name from Step 2 with a live demo>" --force
```

Read the generated `dossiers/<slug>/dossier.md`.

Confirm:
- The "## Website Demo" section shows `**Live demo:** https://tattoo-outreach-demos.pages.dev/<slug>/` (not the old "Demo exists locally at" text, not "not yet hosted/live")
- The section's second line no longer says "not a hosted live site" (that would now be false)
- If the research summary or talking points mention the demo, they describe it as live/shareable, not as a mockup-in-progress

- [ ] **Step 4: Report findings**

If either agent's output doesn't match the confirmations in Step 2/3, that's a real bug in Task 2 or Task 4's prompt wiring -- do not mark this task complete until both check out. Note the exact URL, slug, and file paths inspected in your report so the evidence is verifiable.
