"""
FastAPI app — PoP Detection Engine UI backend.

Run locally with:
    uvicorn backend.main:app --reload --port 8000
(from mplc_pop_engine/ui_app/)
"""

import csv
import io
from datetime import date
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from .db import init_db, get_db
from . import models
from . import queries
from .pipeline_runner import run_and_persist
from .file_discovery import discover_weekly_files, archive_files, DiscoveryError, OUTPUT_DIR

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
    page: int = 1,
    page_size: int = 100,
    db: Session = Depends(get_db),
):
    if page_size > 1000:
        raise HTTPException(status_code=400, detail="page_size capped at 1000")
    return queries.list_accounts(
        db, run_date=run_date, vertical=vertical, segment=segment,
        excluded=excluded, page=page, page_size=page_size,
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

class FindEnrichableRequest(BaseModel):
    account_ids: list[str]
    created_by: Optional[str] = None


@app.post("/accounts/find-enrichable")
def find_enrichable_accounts(req: FindEnrichableRequest, db: Session = Depends(get_db)):
    if not req.account_ids:
        raise HTTPException(status_code=400, detail="account_ids must be non-empty")

    rows = queries.accounts_by_ids(db, req.account_ids)
    found_ids = {r["account_id"] for r in rows}
    missing = [aid for aid in req.account_ids if aid not in found_ids]

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
        fieldnames=["account_id", "account_name", "website", "state", "industry",
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
