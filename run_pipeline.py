"""Pipeline orchestrator: runs Discovery -> Website Demo -> Outreach -> Dossier
in sequence, each via its own agent's venv, with structured logging and a
JSON run summary.

This is the lightweight interim orchestrator described in ARCHITECTURE.md
Section 6 -- not a workflow-engine adoption (Temporal etc.), just the glue
that replaces "run four scripts by hand in order."

Discovery is skipped by default because it spends real money against the
Google Places API -- pass --run-discovery to include it.

Dossier is ALSO skipped by default, for the same reason: it's the most
expensive Claude call in this pipeline (tokens + a web_search call per
lead), and there's no reason to generate one for every qualified lead
when only a few are ever about to actually be contacted. Pass
--run-dossier to include it for the whole batch, or (better) run
../agents/dossier/generate_dossier.py --business "..." directly for just
the one lead you're about to pursue.

Website Demo and Outreach stay on by default -- they're free or
near-free (no LLM call for demos; Outreach is cheap per-lead) and every
downstream agent's own idempotent skip-if-exists behavior means running
this with no flags is safe to re-run any time.

Usage:
    python run_pipeline.py                        # demo -> outreach, safe + cheap defaults
    python run_pipeline.py --run-discovery         # include Discovery (costs money)
    python run_pipeline.py --run-dossier           # include Dossier for the WHOLE batch (costs money)
    python run_pipeline.py --limit 3               # cap every stage at 3 leads
    python run_pipeline.py --force                 # regenerate existing output everywhere
    python run_pipeline.py --continue-on-error      # don't stop the pipeline on a stage failure
"""

import argparse
import datetime
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
LOG_DIR = ROOT / "logs"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def venv_python(agent: str) -> Path:
    return ROOT / "agents" / agent / ".venv" / "Scripts" / "python.exe"


def build_stages(args: argparse.Namespace) -> list[dict]:
    common_limit = ["--limit", str(args.limit)] if args.limit else []
    common_force = ["--force"] if args.force else []

    stages = []

    if args.run_discovery:
        stages.append({
            "name": "discovery",
            "cwd": ROOT / "agents" / "discovery",
            "cmd": [str(venv_python("discovery")), "discovery_agent.py"] + common_limit,
        })

    stages.append({
        "name": "website_demo",
        "cwd": ROOT / "agents" / "website_demo",
        "cmd": [str(venv_python("website_demo")), "generate_demo.py"] + common_limit + common_force,
    })
    stages.append({
        "name": "outreach",
        "cwd": ROOT / "agents" / "outreach",
        "cmd": [str(venv_python("outreach")), "generate_drafts.py"] + common_limit + common_force,
    })

    if args.run_dossier:
        stages.append({
            "name": "dossier",
            "cwd": ROOT / "agents" / "dossier",
            "cmd": [str(venv_python("dossier")), "generate_dossier.py"] + common_limit + common_force,
        })

    return stages


def run_stage(stage: dict, logger: logging.Logger) -> dict:
    name = stage["name"]
    python_exe = Path(stage["cmd"][0])

    result = {
        "name": name,
        "command": " ".join(stage["cmd"]),
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    if not python_exe.exists():
        logger.error(f"[{name}] venv python not found at {python_exe} -- has this agent been set up?")
        result.update(status="error", exit_code=None, duration_seconds=0, error="venv missing")
        return result

    logger.info(f"[{name}] starting: {result['command']}")
    start = time.monotonic()
    try:
        proc = subprocess.run(
            stage["cmd"], cwd=stage["cwd"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800,
        )
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        logger.error(f"[{name}] timed out after {duration:.0f}s")
        result.update(status="timeout", exit_code=None, duration_seconds=round(duration, 1))
        return result

    duration = time.monotonic() - start
    for line in (proc.stdout or "").splitlines():
        logger.info(f"[{name}] {line}")
    for line in (proc.stderr or "").splitlines():
        logger.warning(f"[{name}] stderr: {line}")

    status = "success" if proc.returncode == 0 else "failed"
    log_fn = logger.info if status == "success" else logger.error
    log_fn(f"[{name}] finished with exit code {proc.returncode} in {duration:.1f}s")

    result.update(
        status=status,
        exit_code=proc.returncode,
        duration_seconds=round(duration, 1),
        stdout_tail="\n".join((proc.stdout or "").splitlines()[-20:]),
        stderr_tail="\n".join((proc.stderr or "").splitlines()[-20:]),
    )
    return result


def setup_logging(run_id: str) -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = logging.FileHandler(LOG_DIR / f"pipeline_{run_id}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the outreach pipeline end to end")
    parser.add_argument("--run-discovery", action="store_true", help="Include the Discovery stage (spends money against Google Places API)")
    parser.add_argument("--run-dossier", action="store_true", help="Include the Dossier stage for the WHOLE batch (spends money against the Claude API -- prefer running generate_dossier.py --business directly for one lead instead)")
    parser.add_argument("--limit", type=int, default=None, help="Cap every stage at N leads")
    parser.add_argument("--force", action="store_true", help="Regenerate existing demo/outreach/dossier output")
    parser.add_argument("--continue-on-error", action="store_true", help="Keep running later stages even if one fails")
    args = parser.parse_args()

    run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = setup_logging(run_id)

    logger.info(f"Pipeline run {run_id} starting (run_discovery={args.run_discovery}, run_dossier={args.run_dossier}, limit={args.limit}, force={args.force})")

    stages = build_stages(args)
    results = []

    for stage in stages:
        result = run_stage(stage, logger)
        results.append(result)
        if result["status"] != "success" and not args.continue_on_error:
            logger.error(f"Stopping pipeline: [{result['name']}] did not succeed. Pass --continue-on-error to run remaining stages anyway.")
            break

    summary = {
        "run_id": run_id,
        "started_at": results[0]["started_at"] if results else None,
        "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "stages": results,
        "overall_status": "success" if all(r["status"] == "success" for r in results) else "failed",
    }

    summary_path = LOG_DIR / f"run_{run_id}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    logger.info(f"Run summary written to {summary_path}")
    logger.info(f"Overall status: {summary['overall_status']}")
    for r in results:
        logger.info(f"  {r['name']}: {r['status']} ({r.get('duration_seconds', 0)}s)")

    sys.exit(0 if summary["overall_status"] == "success" else 1)


if __name__ == "__main__":
    main()
