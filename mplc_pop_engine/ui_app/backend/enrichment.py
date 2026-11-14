"""
Step 2 ("take selected accounts and run it through vertical pipelines +
check already enriched accounts to not burn credits") — local dispatch of
production/workers/unified_worker.py against a selected set of accounts,
plus the job bookkeeping Step 3's Pipeline Monitor reads back.

Scope, per Jeff's answers to the three clarifying questions (2026-11-13):
  - "Run locally for now"      -> subprocess.Popen, no droplet/SSH involved.
  - "Connect Supabase now"     -> supabase_client.check_already_enriched()
                                  is a real pre-dispatch filter, not a stub.
  - Vertical is a USER CHOICE for this job (a dropdown: Healthcare /
    Corporate / MDU), not auto-routed per account from the raw Salesforce
    industry string. Step 1's own `vertical` filter (queries.py,
    ClassificationRun.vertical) is how Jeff narrows the selection down to
    "accounts Stage B/C already called Corporate" etc. before landing
    here — this module does not re-classify anything.

Explicitly NOT supported: 'hotels' — unified_worker.py's own CLI accepts
it, but process_hotel()'s target module doesn't exist anywhere in this
repo checkout (verified 2026-11-13), so dispatching it would just produce
every account as an error result.
"""

import csv
import os
import subprocess
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from . import models
from . import queries
from . import supabase_client

# vertical key (unified_worker.py's CLI arg, and what it writes back to
# Supabase's account_enrichment_results.vertical) -> display label for the
# UI's vertical picker.
DISPATCHABLE_VERTICALS: dict[str, str] = {
    "healthcare": "Health Care Services",
    "corporate": "Corporations",
    "mdu": "Multi-Dwelling Units",
}

# Where the UI stores its own batch files / worker logs for each job, kept
# out of the repo (mirrors ~/mplc_pop_engine_data/incoming used by
# file_discovery.py for the same "don't litter the repo" reason).
JOBS_DIR = Path(os.path.expanduser("~/mplc_pop_engine_data/enrichment_jobs"))


def _worker_script_path() -> Path:
    """UNIFIED_WORKER_PATH env var if set (e.g. Jeff's Mac has the repo
    somewhere else), otherwise the relative path from this file to
    MPLC/production/workers/unified_worker.py — verified to resolve
    correctly from ui_app/backend/ in this checkout (2026-11-13)."""
    override = os.getenv("UNIFIED_WORKER_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent.parent / "MPLC" / "production" / "workers" / "unified_worker.py"


class DispatchError(Exception):
    """A problem with the dispatch request itself (bad vertical, no
    accounts, worker script missing) — surfaced as a 400, not a 500."""
    pass


#  vertical -> {toggle key -> env var} for the paid/wrong-entity-risk
# channels worth turning off for a given run (2026-11-13, Jeff: "Some steps
# in the pipeline are not always required... What makes sense?"). Scoped to
# paid channels only -- the free ones (state procurement, federal contracts,
# website images, amenity text mining) are either no-cost or entity-certain
# by construction, so there's no real reason to disable them per-run.
CHANNEL_ENV_VARS: dict[str, dict[str, str]] = {
    "healthcare": {"youtube": "ENABLE_YOUTUBE", "image_search": "ENABLE_IMAGE_SEARCH"},
    "corporate": {"image_search": "ENABLE_IMAGE_SEARCH"},
    "mdu": {"youtube": "ENABLE_YOUTUBE"},
}


def dispatch_job(
    db: Session,
    account_ids: list[str],
    vertical: str,
    created_by: Optional[str] = None,
    run_date: Optional[str] = None,
    disabled_channels: Optional[list[str]] = None,
) -> dict:
    """Resolves the selected accounts, filters out ones already enriched
    for THIS vertical (any run_date), writes the remainder to a batch CSV,
    and spawns `unified_worker.py <vertical> <batch.csv> --worker-id 1`
    as a background subprocess. Returns a summary dict; the job itself
    keeps running after this returns — Step 3 polls its progress via
    Supabase, not via this process's exit code.

    IMPORTANT (verified by reading unified_worker.py's argparse + its
    modulo work-partitioning, 2026-11-13): --worker-id is 1-indexed. A
    single-worker dispatch MUST pass --worker-id 1, not 0 — with
    --total-workers defaulting to 1, assigned_worker is always
    (index % 1) + 1 == 1, so --worker-id 0 would never match and every
    single record would silently fall into "partitioned_count" and be
    skipped. This was caught by reading the partitioning logic itself,
    not by running it — there was no real API key in this sandbox to
    actually trigger a run and observe the skip.
    """
    if vertical not in DISPATCHABLE_VERTICALS:
        raise DispatchError(
            f"Unknown or unsupported vertical '{vertical}'. "
            f"Supported: {', '.join(DISPATCHABLE_VERTICALS)}."
        )
    if not account_ids:
        raise DispatchError("No accounts selected.")

    worker_script = _worker_script_path()
    if not worker_script.exists():
        raise DispatchError(
            f"unified_worker.py not found at {worker_script}. "
            f"Set UNIFIED_WORKER_PATH if your repo layout differs."
        )

    run_date = run_date or date.today().isoformat()

    rows = queries.accounts_by_ids(db, account_ids)
    found_ids = {r["account_id"] for r in rows}
    missing = [aid for aid in account_ids if aid not in found_ids]

    try:
        already_enriched = supabase_client.check_already_enriched(list(found_ids), vertical)
    except supabase_client.SupabaseUnavailable as e:
        # Fail loud, not silent: dispatching without this check is exactly
        # the credit-burn risk Jeff asked to guard against, so don't
        # quietly proceed as if everyone were new.
        raise DispatchError(str(e))

    to_dispatch = [r for r in rows if r["account_id"] not in already_enriched]
    if not to_dispatch:
        raise DispatchError(
            f"All {len(rows)} selected account(s) already have a completed "
            f"'{vertical}' enrichment result. Nothing to dispatch."
        )

    job_id = str(uuid.uuid4())
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    batch_file = job_dir / "batch.csv"
    log_file = job_dir / "worker.log"  # unified_worker.py hardcodes logging.FileHandler('worker.log')
                                        # relative to its CWD — give it this job's own dir as cwd so
                                        # concurrent jobs never clobber each other's log.
    stdout_file = job_dir / "stdout.log"

    with open(batch_file, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["account_id", "account_name", "website", "operating_market", "segment"]
        )
        writer.writeheader()
        for r in to_dispatch:
            writer.writerow({
                "account_id": r["account_id"],
                "account_name": r["account_name"] or "",
                "website": r.get("website") or "",
                "operating_market": r.get("operating_market") or "United States",
                "segment": r.get("segment") or "",
            })

    cmd = [
        sys.executable, str(worker_script), vertical, str(batch_file.resolve()),
        "--worker-id", "1", "--run-date", run_date,
    ]

    # Channel toggles (2026-11-13): unified_worker.py's process_* functions
    # already read ENABLE_YOUTUBE/ENABLE_IMAGE_SEARCH from the environment
    # (healthcare_unified.py's process_account() originated this convention;
    # corporate_fixed.py and mdu_unified.py now honor it too) -- set them
    # explicitly here rather than leaving them to whatever this backend
    # process's own environment happens to have, so a disabled channel for
    # one dispatch can't accidentally leak into another concurrent one.
    env = {**os.environ}
    for toggle_key, env_var in CHANNEL_ENV_VARS.get(vertical, {}).items():
        env[env_var] = "false" if disabled_channels and toggle_key in disabled_channels else "true"

    with open(stdout_file, "w") as out:
        proc = subprocess.Popen(
            cmd, cwd=str(job_dir), stdout=out, stderr=subprocess.STDOUT,
            start_new_session=True,  # survives this request/response cycle
            env=env,
        )

    job = models.EnrichmentJob(
        id=job_id,
        vertical=vertical,
        display_vertical=DISPATCHABLE_VERTICALS[vertical],
        run_date=run_date,
        batch_file=str(batch_file.resolve()),
        log_file=str(log_file.resolve()),
        worker_script=str(worker_script.resolve()),
        pid=proc.pid,
        total_requested=len(account_ids),
        total_dispatched=len(to_dispatch),
        skipped_already_enriched=len(already_enriched),
        status="running",
        started_at=datetime.utcnow(),
        created_by=created_by,
    )
    db.add(job)
    db.add_all([
        models.EnrichmentJobAccount(job_id=job_id, account_id=r["account_id"])
        for r in to_dispatch
    ])
    db.commit()

    return {
        "job_id": job_id,
        "vertical": vertical,
        "run_date": run_date,
        "total_requested": len(account_ids),
        "total_dispatched": len(to_dispatch),
        "skipped_already_enriched": len(already_enriched),
        "missing_account_ids": missing,
        "pid": proc.pid,
        "batch_file": str(batch_file.resolve()),
    }


def list_jobs(db: Session) -> list[dict]:
    jobs = db.query(models.EnrichmentJob).order_by(models.EnrichmentJob.started_at.desc()).all()
    return [_job_summary(j) for j in jobs]


def _job_summary(job: models.EnrichmentJob) -> dict:
    return {
        "job_id": job.id,
        "vertical": job.vertical,
        "display_vertical": job.display_vertical,
        "run_date": job.run_date,
        "status": job.status,
        "total_requested": job.total_requested,
        "total_dispatched": job.total_dispatched,
        "skipped_already_enriched": job.skipped_already_enriched,
        "pid": job.pid,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "created_by": job.created_by,
    }


def job_progress(db: Session, job_id: str) -> dict:
    """Live progress for one job — status counts, per-account results,
    cost, and the most recent heartbeat. Pure read: never mutates the
    EnrichmentJob row's `status` itself (see note below on why)."""
    job = db.get(models.EnrichmentJob, job_id)
    if job is None:
        raise DispatchError(f"No job with id {job_id}")

    account_ids = [
        ja.account_id for ja in
        db.query(models.EnrichmentJobAccount).filter_by(job_id=job_id).all()
    ]

    try:
        status_counts = supabase_client.get_job_status_counts(account_ids, job.run_date, job.vertical)
        results = supabase_client.get_job_results(account_ids, job.run_date, job.vertical)
        cost = supabase_client.get_job_cost(account_ids, job.run_date, job.vertical)
        heartbeat = supabase_client.get_latest_heartbeat(job.batch_file)
        supabase_error = None
    except supabase_client.SupabaseUnavailable as e:
        status_counts, results, cost, heartbeat = {}, [], 0.0, None
        supabase_error = str(e)

    # Whether the OS process itself is still alive is a separate signal
    # from Supabase's row-level status — a worker can be mid-VLM-call on
    # the last account (process alive, but that account's row isn't
    # 'completed' yet) or have crashed outright (process dead, rows stuck
    # at 'pending'/'in_progress' forever). Report both; let the UI show
    # "process exited, N accounts never finished" rather than a job that
    # spins at "running" forever.
    process_alive = _pid_alive(job.pid) if job.pid else False

    return {
        "job_id": job.id,
        "vertical": job.vertical,
        "display_vertical": job.display_vertical,
        "run_date": job.run_date,
        "status": job.status,
        "process_alive": process_alive,
        "total_dispatched": job.total_dispatched,
        "skipped_already_enriched": job.skipped_already_enriched,
        "status_counts": status_counts,
        "cost_so_far": cost,
        "heartbeat": heartbeat,
        "results": results,
        "supabase_error": supabase_error,
    }


def _pid_alive(pid: int) -> bool:
    """os.kill(pid, 0) sends no signal, just checks the process exists
    and is signalable. ProcessLookupError = genuinely gone. PermissionError
    means it exists but isn't ours to signal (won't happen for our own
    subprocess, but handled correctly rather than guessed at either way)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
