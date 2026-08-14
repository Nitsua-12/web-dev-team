"""Demo Site Deploy Script.

Uploads agents/website_demo/output/ to Cloudflare Pages via the `wrangler`
CLI (invoked through `npx` -- no global install needed, just Node/npm).
Also writes a real root-level robots.txt reflecting indexable_slugs.txt
(see README.md's Hosting section). The per-slug robots.txt generate_demo.py
used to write never had any effect once hosted -- crawlers only ever read
robots.txt at a site's actual root, not inside a subdirectory -- see
build_root_robots_txt() below.

Usage:
    python deploy.py

Requires CLOUDFLARE_PROJECT_NAME, CLOUDFLARE_API_TOKEN, and
CLOUDFLARE_ACCOUNT_ID in .env -- see README.md's Hosting section for setup.
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from generate_demo import DEFAULT_INDEXABLE_SLUGS_FILE, DEFAULT_OUTPUT_DIR, read_indexable_slugs

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_root_robots_txt(indexable_slugs: set[str]) -> str:
    """Real root-level robots.txt content -- Disallow everything by
    default (these are unsolicited mockups, see README.md), Allow only
    slugs a lead has actually responded to. Sorted for a deterministic,
    diffable file across repeated deploys."""
    lines = ["User-agent: *", "Disallow: /"]
    lines += [f"Allow: /{slug}/" for slug in sorted(indexable_slugs)]
    return "\n".join(lines) + "\n"


def find_indexable_html_outside_allowlist(output_dir: Path, indexable_slugs: set[str]) -> list[Path]:
    """Scans output_dir/<slug>/**/*.html for pages claiming index,follow
    whose slug isn't in indexable_slugs -- the deploy-time safety net for
    the noindex-by-default guarantee. Catches a demo that wasn't
    regenerated after its clearance changed (e.g. a lead dropped out of
    qualification and generate_demo.py --force no longer touches it, but
    its stale HTML still ships on every deploy)."""
    violations = []
    for html_file in sorted(output_dir.glob("*/**/*.html")):
        slug = html_file.relative_to(output_dir).parts[0]
        if slug in indexable_slugs:
            continue
        if 'content="index, follow"' in html_file.read_text(encoding="utf-8"):
            violations.append(html_file)
    return violations


def main() -> None:
    load_dotenv()

    if not DEFAULT_OUTPUT_DIR.exists() or not any(DEFAULT_OUTPUT_DIR.iterdir()):
        raise SystemExit(f"{DEFAULT_OUTPUT_DIR} is empty -- run generate_demo.py first")

    project_name = os.environ.get("CLOUDFLARE_PROJECT_NAME", "").strip()
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    missing = [
        name
        for name, value in (
            ("CLOUDFLARE_PROJECT_NAME", project_name),
            ("CLOUDFLARE_API_TOKEN", api_token),
            ("CLOUDFLARE_ACCOUNT_ID", account_id),
        )
        if not value
    ]
    if missing:
        raise SystemExit(f"{', '.join(missing)} not set -- add to .env, see README.md's Hosting section")

    indexable_slugs = read_indexable_slugs(DEFAULT_INDEXABLE_SLUGS_FILE)

    violations = find_indexable_html_outside_allowlist(DEFAULT_OUTPUT_DIR, indexable_slugs)
    if violations:
        listed = "\n".join(f"  - {path}" for path in violations)
        raise SystemExit(
            "Refusing to deploy: found page(s) with content=\"index, follow\" whose slug "
            "isn't in indexable_slugs.txt:\n"
            f"{listed}\n\n"
            "This usually means a demo's content is stale -- either the lead was cleared "
            "and then un-cleared without regenerating, or (more likely) the lead dropped "
            "out of qualification so `generate_demo.py --force` no longer touches its "
            "output/<slug>/ directory, leaving old index,follow HTML in place. Fix by "
            "either re-qualifying the lead and re-running `generate_demo.py --force`, or "
            "deleting the stale output/<slug>/ directory before deploying."
        )

    (DEFAULT_OUTPUT_DIR / "robots.txt").write_text(build_root_robots_txt(indexable_slugs), encoding="utf-8")
    print(
        f"robots.txt written -- {len(indexable_slugs)} indexable slug(s): "
        f"{', '.join(sorted(indexable_slugs)) or '(none)'}"
    )

    result = subprocess.run(
        ["npx", "wrangler", "pages", "deploy", str(DEFAULT_OUTPUT_DIR), "--project-name", project_name],
        shell=(os.name == "nt"),
    )
    if result.returncode != 0:
        raise SystemExit(f"wrangler deploy failed (exit code {result.returncode}) -- see output above")

    print(f"\nDeployed. Live at https://{project_name}.pages.dev")
    print(
        "Note: this reflects whatever was last generated -- re-run "
        "generate_demo.py --force first if a demo's content changed."
    )


if __name__ == "__main__":
    main()
