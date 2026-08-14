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
