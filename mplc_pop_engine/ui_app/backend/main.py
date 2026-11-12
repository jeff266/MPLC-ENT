"""
FastAPI app — PoP Detection Engine UI backend.

Run locally with:
    uvicorn backend.main:app --reload --port 8000
(from mplc_pop_engine/ui_app/)
"""

from datetime import date
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from .db import init_db, get_db
from . import models
from . import queries
from .pipeline_runner import run_and_persist

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
# Dispatch — the actual "select rows -> act on them" triage action.
# Records an Action row (audit trail); does not yet call the vertical
# enrichers themselves (verticals/ are a separate, not-yet-wired stage).
# ---------------------------------------------------------------------------

class DispatchRequest(BaseModel):
    account_ids: list[str]
    action_type: str  # e.g. "dispatch_to_enrichment" | "export_clay" | "mark_reviewed"
    created_by: Optional[str] = None


@app.post("/accounts/dispatch")
def dispatch_accounts(req: DispatchRequest, db: Session = Depends(get_db)):
    if not req.account_ids:
        raise HTTPException(status_code=400, detail="account_ids must be non-empty")
    actions = [
        models.Action(account_id=aid, action_type=req.action_type,
                      status="pending", created_by=req.created_by)
        for aid in req.account_ids
    ]
    db.add_all(actions)
    db.commit()
    return {"dispatched": len(actions), "action_type": req.action_type}
