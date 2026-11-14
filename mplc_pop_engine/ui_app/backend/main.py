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
from . import auth
from . import settings as settings_module
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


# Whole-app auth, added 2026-11-14 (see auth.py's module docstring for why
# and the scope decision). A middleware, not per-route Depends, so every
# existing endpoint (accounts, cost-tracker, enrichment dispatch, etc.) is
# covered without touching each one individually. CORS preflight (OPTIONS)
# and the exempt paths (login/signup/health) pass through unauthenticated;
# everything else needs a valid Authorization: Bearer <token> header or
# gets a 401 before the real handler ever runs.
@app.middleware("http")
async def require_auth(request, call_next):
    if request.method == "OPTIONS" or request.url.path in auth.EXEMPT_PATHS:
        return await call_next(request)

    from .db import SessionLocal  # local import: avoid a module-load-order issue with db.py's engine setup

    db = SessionLocal()
    try:
        user = auth.authenticate_request(request.headers.get("authorization"), db)
    finally:
        db.close()

    if user is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    return await call_next(request)


@app.on_event("startup")
def on_startup():
    init_db()


# ---- Auth -----------------------------------------------------------------

class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@app.post("/auth/signup", response_model=TokenResponse)
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    existing = db.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail="An account with that email already exists.")

    user = models.User(id=auth.new_user_id(), email=email, password_hash=auth.hash_password(req.password))
    db.add(user)
    db.commit()

    return TokenResponse(access_token=auth.create_access_token(user.id, user.email))


@app.post("/auth/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    user = db.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()
    # Same error for "no such user" and "wrong password" -- don't let a login
    # form be used to enumerate which emails have accounts.
    if user is None or not auth.verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    return TokenResponse(access_token=auth.create_access_token(user.id, user.email))


@app.get("/auth/me")
def me(user: models.User = Depends(auth.get_current_user)):
    return {"id": user.id, "email": user.email}


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
    Finder-navigation workflow with drag-and-drop in the browser.

    FIX (2026-11-13, Jeff: "I'd prefer we delete the old files and only
    work with the new ones"): the old comment here claimed a re-upload
    "just overwrites last week's" file, but that's only true if the
    filename is identical -- Salesforce exports embed a timestamp in the
    filename (e.g. "All_Open_Deals-2026-11-11-19-28-26.csv"), so a new
    weekly export never collides with the old one by name. It would
    previously just sit alongside it in incoming/, relying on
    discover_weekly_files()'s most-recent-mtime tiebreak to pick the right
    one. Now: before saving each upload, delete any existing incoming/
    file that matches the SAME role (by the same pattern matching
    discovery itself uses), so incoming/ only ever holds the current
    file for each of the 4 roles -- no stale exports, no mtime-dependent
    tiebreak, no "WARNING: N files matched role" ambiguity."""
    from .file_discovery import role_for_filename

    ensure_dirs()
    saved = []
    deleted = []
    for f in files:
        if not f.filename:
            continue

        role = role_for_filename(f.filename)
        if role:
            for existing in INCOMING_DIR.glob("*.csv"):
                if existing.name != f.filename and role_for_filename(existing.name) == role:
                    existing.unlink()
                    deleted.append(existing.name)

        dest = INCOMING_DIR / f.filename
        contents = await f.read()
        dest.write_bytes(contents)
        saved.append(f.filename)
    return {"saved": saved, "deleted": deleted, "incoming_dir": str(INCOMING_DIR)}


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

CHANNEL_LABELS: dict[str, str] = {
    "youtube": "YouTube video search",
    "image_search": "Image search",
}


@app.get("/enrichment/verticals")
def list_dispatchable_verticals():
    """What the Step 2 vertical picker should offer — deliberately NOT
    {'hotels'}, since unified_worker.py's own CLI accepts it but its
    target module (process_hotel's import) doesn't exist in this repo
    checkout (verified 2026-11-13).

    toggleable_channels (2026-11-13): the paid channels this vertical has
    that can be turned off for a given dispatch via disabled_channels —
    single source of truth is enrichment.CHANNEL_ENV_VARS, so the frontend
    never has its own copy to drift out of sync."""
    return [
        {
            "key": k,
            "label": v,
            "toggleable_channels": [
                {"key": ck, "label": CHANNEL_LABELS.get(ck, ck)}
                for ck in enrichment.CHANNEL_ENV_VARS.get(k, {})
            ],
        }
        for k, v in enrichment.DISPATCHABLE_VERTICALS.items()
    ]


@app.get("/enrichment/cost-estimate")
def get_enrichment_cost_estimate(
    vertical: str,
    account_count: int,
    disabled_channels: Optional[str] = None,
):
    """Pre-dispatch cost preview for Step 2 (Jeff, 2026-11-14: "are we
    showing an estimate of how much each run and total will cost?" --
    previously no). `disabled_channels` is a comma-separated list of
    toggle keys, matching DispatchBar's existing disabled_channels shape."""
    toggles = [c for c in disabled_channels.split(",") if c] if disabled_channels else None
    try:
        return enrichment.estimate_dispatch_cost(
            vertical=vertical, account_count=account_count, disabled_channels=toggles,
        )
    except enrichment.DispatchError as e:
        raise HTTPException(status_code=400, detail=str(e))


class DispatchEnrichmentRequest(BaseModel):
    account_ids: Optional[list[str]] = None
    filter: Optional[AccountFilter] = None
    exclude_account_ids: Optional[list[str]] = None
    vertical: str
    created_by: Optional[str] = None
    # Which paid channels to turn OFF for this run, e.g. ["youtube"]
    # (2026-11-13) -- see enrichment.CHANNEL_ENV_VARS for which keys are
    # valid per vertical. Unset/empty means "run everything" (unchanged
    # default behavior).
    disabled_channels: Optional[list[str]] = None


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
            disabled_channels=req.disabled_channels,
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


@app.get("/cost-tracker")
def get_cost_tracker(vertical: Optional[str] = None):
    """Cumulative, on-demand cost rollup (vertical x channel), plus a
    standing is_prospect data-integrity check, per claude/Cost_Tracker_
    Design.md. No separate rollup table or scheduler -- computed fresh
    from account_enrichment_results every call, per Jeff's 2026-11-14
    decision. `summary` gives the per-vertical North Star numbers
    ($/account, $/prospect, $/lead) aggregated across that vertical's
    channels; `by_channel` is the full breakdown rows from Supabase.
    `data_integrity_warnings` is only non-empty if is_prospect has drifted
    from lead_status/tier again since the 2026-11-14 backfill -- silent
    the rest of the time, so it reads as a real alert, not routine noise."""
    try:
        rows = supabase_client.get_cost_tracker_rollup(vertical=vertical)
    except supabase_client.SupabaseUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    summary: dict[str, dict] = {}
    for row in rows:
        v = row["vertical"]
        s = summary.setdefault(v, {
            "vertical": v,
            "accounts_processed": 0,
            "prospect_count": 0,
            "suspect_count": 0,
            "rows_with_cost": 0,
            "total_cost": 0.0,
            "is_prospect_mismatches": 0,
        })
        s["accounts_processed"] += row["accounts_processed"]
        s["prospect_count"] += row["prospect_count"]
        s["suspect_count"] += row["suspect_count"]
        s["rows_with_cost"] += row["rows_with_cost"]
        s["total_cost"] += row["total_cost"]
        s["is_prospect_mismatches"] += row["is_prospect_mismatches"]

    for s in summary.values():
        lead_count = s["prospect_count"] + s["suspect_count"]
        s["cost_per_account"] = (s["total_cost"] / s["rows_with_cost"]) if s["rows_with_cost"] else None
        s["cost_per_prospect"] = (s["total_cost"] / s["prospect_count"]) if s["prospect_count"] else None
        s["cost_per_lead"] = (s["total_cost"] / lead_count) if lead_count else None

    warnings = [
        f"{row['vertical']}/{row['channel'] or '(no channel)'}: "
        f"{row['is_prospect_mismatches']} rows where is_prospect disagrees with "
        f"lead_status/tier -- re-run the 2026-11-14 backfill query"
        for row in rows if row["is_prospect_mismatches"] > 0
    ]

    return {
        "summary": sorted(summary.values(), key=lambda s: s["vertical"]),
        "by_channel": rows,
        "data_integrity_warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Settings (added 2026-11-14) -- store the production path's API keys /
# connection strings in .env and verify each one against a real provider
# call. See settings.py's module docstring for the full scope decision
# (which vars are managed, which are deliberately excluded) and exactly
# which real call each verify() makes and what it costs.
# ---------------------------------------------------------------------------

@app.get("/settings")
def list_settings():
    return {"settings": settings_module.list_settings()}


class UpdateSettingRequest(BaseModel):
    value: str


@app.put("/settings/{key}")
def update_setting(key: str, req: UpdateSettingRequest):
    try:
        return settings_module.set_setting(key, req.value)
    except settings_module.UnknownSetting as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/settings/{key}/verify")
def verify_setting(key: str):
    try:
        return settings_module.verify_setting(key)
    except settings_module.UnknownSetting as e:
        raise HTTPException(status_code=400, detail=str(e))


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
