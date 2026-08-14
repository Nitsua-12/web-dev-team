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


def build_root_robots_txt(indexable_slugs: set[str]) -> str:
    """Real root-level robots.txt content -- Disallow everything by
    default (these are unsolicited mockups, see README.md), Allow only
    slugs a lead has actually responded to. Sorted for a deterministic,
    diffable file across repeated deploys."""
    lines = ["User-agent: *", "Disallow: /"]
    lines += [f"Allow: /{slug}/" for slug in sorted(indexable_slugs)]
    return "\n".join(lines) + "\n"
