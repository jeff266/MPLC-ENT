"""
FastAPI app — PoP Detection Engine UI backend.

Run locally with:
    uvicorn backend.main:app --reload --port 8000
(from mplc_pop_engine/ui_app/)
"""

import csv
import io
from datetime import date
from pathlib import Path
from typing import Optional

# FIX (2026-11-13): this app never actually loaded a .env file -- python-dotenv
# was in requirements.txt but unused, so DATABASE_URL/SUPABASE_PASSWORD only
# ever worked if exported in the shell by hand. supabase_client.py's own error
# message says to "reuse whatever .env Jeff already has configured for the
# workers" -- so look there (production/workers/.env), same contract
# unified_worker.py itself uses, falling back to a backend-local .env if one
# exists (e.g. if Jeff prefers to keep the UI's own secrets separate).
try:
    from dotenv import load_dotenv
    _workers_env = Path(__file__).parent.parent.parent / "MPLC" / "production" / "workers" / ".env"
    _local_env = Path(__file__).parent / ".env"
    for _env_path in (_local_env, _workers_env):
        if _env_path.exists():
            load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv not installed; rely on system environment only

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from .db import init_db, get_db
from . import models
from . import queries
from . import enrichment
from . import supabase_client
from .pipeline_runner import run_and_persist
from .file_discovery import (
    discover_weekly_files, archive_files, DiscoveryError, OUTPUT_DIR,
    INCOMING_DIR, ensure_dirs,
)

app = FastAPI(title="PoP Detection Engine")

# Local-only tool today; wide-open CORS is fine for a React dev server on
# localhost. Tighten this before this is ever reachable off-machine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


class PipelineRunRequest(BaseModel):
    salesforce_export_path: str
    open_deals_path: str
    activity_90_days_path: Optional[str] = None
    lost_deals_9_months_path: Optional[str] = None
    output_dir: str = "output"
    run_date: Optional[str] = None  # defaults to today
    max_identity_cluster_size: int = 50


@app.post("/pipeline/run")
def trigger_pipeline_run(req: PipelineRunRequest, db: Session = Depends(get_db)):
    """Runs Stage A/B/C synchronously and persists results. For the real
    ~703K-account universe this takes well under a minute (validated this
    session), so synchronous is fine for a local, single-user tool —
    revisit with a background task queue if that stops being true."""
    run_date = req.run_date or date.today().isoformat()
    try:
        summary = run_and_persist(
            session=db,
            salesforce_export_path=req.salesforce_export_path,
            output_dir=req.output_dir,
            run_date=run_date,
            open_deals_path=req.open_deals_path,
            activity_90_days_path=req.activity_90_days_path,
            lost_deals_9_months_path=req.lost_deals_9_months_path,
            max_identity_cluster_size=req.max_identity_cluster_size,
            verbose=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"run_date": run_date, "summary": summary}


@app.post("/pipeline/upload")
async def upload_weekly_files(files: list[UploadFile] = File(...)):
    """Jeff (2026-11-12): "wouldn't it be better to add a drop the files
    feature and it is stored in that directory" — replaces the
    Finder-navigation workflow with drag-and-drop in the browser. Writes
    each uploaded file straight into the same incoming/ directory
    discover_weekly_files() already reads from, under its original
    filename (so a re-upload of this week's export just overwrites last
    week's, which is what you want — discovery picks the most recently
    modified match anyway). No parsing or validation here: the pipeline
    run is what actually checks these are real, matching files."""
    ensure_dirs()
    saved = []
    for f in files:
        if not f.filename:
            continue
        dest = INCOMING_DIR / f.filename
        contents = await f.read()
        dest.write_bytes(contents)
        saved.append(f.filename)
    return {"saved": saved, "incoming_dir": str(INCOMING_DIR)}


@app.get("/pipeline/incoming")
def list_incoming_files():
    """What's currently sitting in incoming/, so the UI can show it before
    the user clicks Run — and which required role (if any) each matches,
    so a user can tell at a glance whether they're ready to run."""
    ensure_dirs()
    from .file_discovery import ROLE_PATTERNS, _normalize

    out = []
    for p in sorted(INCOMING_DIR.iterdir()):
        if not p.is_file():
            continue
        matched_role = None
        normalized_name = _normalize(p.name)
        for role, patterns in ROLE_PATTERNS.items():
            if any(_normalize(pat) in normalized_name for pat in patterns):
                matched_role = role
                break
        out.append({
            "filename": p.name,
            "size_bytes": p.stat().st_size,
            "modified_at": p.stat().st_mtime,
            "matched_role": matched_role,
        })
    return {"files": out}


@app.post("/pipeline/run/auto")
def trigger_pipeline_run_auto(db: Session = Depends(get_db)):
    """Discovery-based run for the weekly scheduler / a one-click UI button
    — no file paths needed. Finds the weekly exports in
    ~/mplc_pop_engine_data/incoming/ by filename pattern (see
    file_discovery.py), runs the pipeline, and archives the inputs on
    success so next week's discovery can't re-pick a stale file."""
    run_date = date.today().isoformat()
    try:
        files = discover_weekly_files()
    except DiscoveryError as e:
        raise HTTPException(status_code=400, detail=str(e))

    run_output_dir = OUTPUT_DIR / run_date
    run_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        summary = run_and_persist(
            session=db,
            salesforce_export_path=str(files["salesforce_export"]),
            output_dir=str(run_output_dir),
            run_date=run_date,
            open_deals_path=str(files["open_deals"]),
            activity_90_days_path=str(files["activity_90_days"]) if "activity_90_days" in files else None,
            lost_deals_9_months_path=str(files["lost_deals_9_months"]) if "lost_deals_9_months" in files else None,
            verbose=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    archive_files(files, run_date)
    return {
        "run_date": run_date,
        "summary": summary,
        "archived_files": {k: str(v) for k, v in files.items()},
    }


@app.get("/runs")
def list_runs(db: Session = Depends(get_db)):
    rows = db.execute(
        select(models.PipelineRun).order_by(models.PipelineRun.started_at.desc())
    ).scalars().all()
    return [
        {
            "run_id": r.run_id, "run_date": r.run_date, "stage": r.stage,
            "status": r.status, "counts_json": r.counts_json,
            "started_at": r.started_at, "finished_at": r.finished_at,
            "error_message": r.error_message,
        }
        for r in rows
    ]


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Triage table — the core workflow. Server-side pagination/filtering is
# non-negotiable at ~700K accounts; the UI must never ask for "all rows".
# ---------------------------------------------------------------------------

@app.get("/accounts")
def get_accounts(
    run_date: Optional[str] = None,
    vertical: Optional[str] = None,
    segment: Optional[str] = None,
    excluded: Optional[bool] = None,
    country: Optional[str] = None,
    operating_market: Optional[str] = None,
    capacity_type: Optional[str] = None,
    capacity_min: Optional[int] = None,
    capacity_max: Optional[int] = None,
    page: int = 1,
    page_size: int = 100,
    db: Session = Depends(get_db),
):
    if page_size > 1000:
        raise HTTPException(status_code=400, detail="page_size capped at 1000")
    return queries.list_accounts(
        db, run_date=run_date, vertical=vertical, segment=segment,
        excluded=excluded, country=country, operating_market=operating_market,
        capacity_type=capacity_type, capacity_min=capacity_min, capacity_max=capacity_max,
        page=page, page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Review queues — the three known human-in-the-loop piles (per "first
# principles" design: deterministic stages run themselves, these don't).
# ---------------------------------------------------------------------------

@app.get("/review-queues/unresolved")
def get_unresolved_queue(
    run_date: Optional[str] = None, vertical: Optional[str] = None,
    page: int = 1, page_size: int = 100, db: Session = Depends(get_db),
):
    return queries.unresolved_queue(db, run_date=run_date, vertical=vertical,
                                     page=page, page_size=page_size)


@app.get("/review-queues/clay-ambiguous")
def get_clay_ambiguous_queue(
    batch_id: Optional[str] = None, page: int = 1, page_size: int = 100,
    db: Session = Depends(get_db),
):
    return queries.clay_ambiguous_queue(db, batch_id=batch_id, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# Find Enrichable Accounts — the one real row-selection action today (Jeff,
# 2026-11-12): mark the selected accounts as candidates (an Action row, for
# audit trail / "what did I already flag") and hand back a CSV to source
# Clay/ZoomInfo data for, or route to the vertical pipelines later.
#
# Deliberately NOT cross-checked against Supabase's account_enrichment_results
# (32,613 real rows of prior vertical-pipeline history) yet — Jeff: "Local
# for now. I'd have to rethink our vertical pipelines again. Meaning
# supabase itself may ultimately change too" (2026-11-12). So this can mark
# an account as enrichable even if it was already run through a vertical
# enricher before; that credit-burn protection is a deliberately deferred
# follow-on, not an oversight.
# ---------------------------------------------------------------------------

class AccountFilter(BaseModel):
    run_date: Optional[str] = None
    vertical: Optional[str] = None
    segment: Optional[str] = None
    excluded: Optional[bool] = None
    country: Optional[str] = None
    operating_market: Optional[str] = None
    capacity_type: Optional[str] = None
    capacity_min: Optional[int] = None
    capacity_max: Optional[int] = None


class FindEnrichableRequest(BaseModel):
    # Exactly one of these two selection modes:
    account_ids: Optional[list[str]] = None          # explicit checkbox selection
    filter: Optional[AccountFilter] = None           # "select all N filtered rows"
    exclude_account_ids: Optional[list[str]] = None  # with filter: manually-deselected rows
    created_by: Optional[str] = None


@app.post("/accounts/find-enrichable")
def find_enrichable_accounts(req: FindEnrichableRequest, db: Session = Depends(get_db)):
    if bool(req.account_ids) == bool(req.filter):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of account_ids (explicit selection) or filter (select-all-filtered).",
        )

    if req.filter:
        account_ids = queries.resolve_filtered_account_ids(
            db, run_date=req.filter.run_date, vertical=req.filter.vertical,
            segment=req.filter.segment, excluded=req.filter.excluded,
            country=req.filter.country, operating_market=req.filter.operating_market,
            capacity_type=req.filter.capacity_type, capacity_min=req.filter.capacity_min,
            capacity_max=req.filter.capacity_max,
            exclude_account_ids=req.exclude_account_ids,
        )
        if not account_ids:
            raise HTTPException(status_code=400, detail="No accounts matched that filter.")
    else:
        account_ids = req.account_ids

    rows = queries.accounts_by_ids(db, account_ids)
    found_ids = {r["account_id"] for r in rows}
    missing = [aid for aid in account_ids if aid not in found_ids]

    # Only mark accounts that actually exist — an account_id not found in
    # this run has nothing to flag. Caught via smoke test: this used to
    # write an Action row for every requested id including a fake one.
    actions = [
        models.Action(account_id=aid, action_type="find_enrichable_accounts",
                      status="pending", created_by=req.created_by)
        for aid in found_ids
    ]
    db.add_all(actions)
    db.commit()

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["account_id", "account_name", "website", "state", "country",
                    "operating_market", "capacity", "capacity_type", "industry",
                    "excluded", "vertical", "segment"],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    buf.seek(0)

    headers = {
        "Content-Disposition": f'attachment; filename="enrichable_accounts_{date.today().isoformat()}.csv"',
        "X-Marked-Count": str(len(actions)),
        "X-Missing-Count": str(len(missing)),
    }
    if missing:
        headers["X-Missing-Account-Ids"] = ",".join(missing[:50])  # cap header size
    return StreamingResponse(buf, media_type="text/csv", headers=headers)


# ---------------------------------------------------------------------------
# Step 2: Run Vertical Pipelines (Jeff, 2026-11-13) — "take selected
# accounts and run it through vertical pipelines + check already enriched
# accounts to not burn credits". Local-only dispatch of
# production/workers/unified_worker.py; see enrichment.py for the full
# design rationale (vertical is a user choice, not auto-routed; the
# already-enriched check is scoped per-vertical, any run_date).
# ---------------------------------------------------------------------------

@app.get("/enrichment/verticals")
def list_dispatchable_verticals():
    """What the Step 2 vertical picker should offer — deliberately NOT
    {'hotels'}, since unified_worker.py's own CLI accepts it but its
    target module (process_hotel's import) doesn't exist in this repo
    checkout (verified 2026-11-13)."""
    return [{"key": k, "label": v} for k, v in enrichment.DISPATCHABLE_VERTICALS.items()]


class DispatchEnrichmentRequest(BaseModel):
    account_ids: Optional[list[str]] = None
    filter: Optional[AccountFilter] = None
    exclude_account_ids: Optional[list[str]] = None
    vertical: str
    created_by: Optional[str] = None


@app.post("/enrichment/dispatch")
def dispatch_enrichment_job(req: DispatchEnrichmentRequest, db: Session = Depends(get_db)):
    if bool(req.account_ids) == bool(req.filter):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of account_ids (explicit selection) or filter (select-all-filtered).",
        )
    if req.filter:
        account_ids = queries.resolve_filtered_account_ids(
            db, run_date=req.filter.run_date, vertical=req.filter.vertical,
            segment=req.filter.segment, excluded=req.filter.excluded,
            country=req.filter.country, operating_market=req.filter.operating_market,
            capacity_type=req.filter.capacity_type, capacity_min=req.filter.capacity_min,
            capacity_max=req.filter.capacity_max,
            exclude_account_ids=req.exclude_account_ids,
        )
        if not account_ids:
            raise HTTPException(status_code=400, detail="No accounts matched that filter.")
    else:
        account_ids = req.account_ids

    try:
        return enrichment.dispatch_job(
            db, account_ids=account_ids, vertical=req.vertical, created_by=req.created_by,
        )
    except enrichment.DispatchError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/enrichment/jobs")
def get_enrichment_jobs(db: Session = Depends(get_db)):
    return enrichment.list_jobs(db)


@app.get("/enrichment/jobs/{job_id}/progress")
def get_enrichment_job_progress(job_id: str, db: Session = Depends(get_db)):
    try:
        return enrichment.job_progress(db, job_id)
    except enrichment.DispatchError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/accounts/check-already-enriched")
def check_already_enriched_preview(req: DispatchEnrichmentRequest, db: Session = Depends(get_db)):
    """Lets the Step 2 UI show "X of Y already enriched for this vertical"
    BEFORE the user clicks dispatch — same selection contract as
    /enrichment/dispatch, but read-only, no job created."""
    if req.vertical not in enrichment.DISPATCHABLE_VERTICALS:
        raise HTTPException(status_code=400, detail=f"Unknown vertical '{req.vertical}'")
    if bool(req.account_ids) == bool(req.filter):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of account_ids (explicit selection) or filter (select-all-filtered).",
        )
    if req.filter:
        account_ids = queries.resolve_filtered_account_ids(
            db, run_date=req.filter.run_date, vertical=req.filter.vertical,
            segment=req.filter.segment, excluded=req.filter.excluded,
            country=req.filter.country, operating_market=req.filter.operating_market,
            capacity_type=req.filter.capacity_type, capacity_min=req.filter.capacity_min,
            capacity_max=req.filter.capacity_max,
            exclude_account_ids=req.exclude_account_ids,
        )
    else:
        account_ids = req.account_ids

    try:
        already = supabase_client.check_already_enriched(account_ids, req.vertical)
    except supabase_client.SupabaseUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "vertical": req.vertical,
        "total_selected": len(account_ids),
        "already_enriched_count": len(already),
        "to_dispatch_count": len(account_ids) - len(already),
        "already_enriched_account_ids": sorted(already)[:500],  # cap response size
    }
