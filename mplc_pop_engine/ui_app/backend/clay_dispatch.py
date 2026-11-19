"""
Dispatch selected Clay-import rows directly into a vertical pipeline,
without needing a Salesforce account first.

Jeff (2026-11-18), after the Clay Import review table: "After I dedupe
the list and find the net new, and select accounts, how do I route them
to a vertical? or store in them in a future run?" Traced before writing
anything: there was no path. enrichment.dispatch_job() only accepts
account_ids that already exist in this app's local `accounts` table
(Salesforce-sourced -- models.Account.account_id is a real 18-char SF
id), and a NET_NEW Clay row has no Salesforce account at all by
definition -- that's what NET_NEW means.

Scoped with Jeff before building (his own words): "what i want is, when
i import the file, i decide which ones should run thru the pipeline.
the check against salesforce data is very useful in showing me which
ones i should try to run thru." So the dedupe status is a DECISION AID,
never a gate -- any selected row, any classification, can be dispatched.
Three follow-up scoping answers (2026-11-18, all "recommended"):
  1. Stable pseudo account_id across re-imports, so processing the same
     export again next month skips companies already run -- see
     compute_pseudo_account_id() below.
  2. Reuse the existing Step 3 Pipeline Monitor (EnrichmentJob /
     EnrichmentJobAccount) rather than a separate Clay-only view.
  3. A MATCHED_PROTECTED row can still be dispatched, but needs an
     explicit confirm first (Jeff might have a real reason -- a
     different division, a reassigned territory) -- never a silent
     send, never a hard block either.

Reuses enrichment.py's worker-script resolution, channel toggles, and
EnrichmentJob bookkeeping rather than duplicating them -- this module
only adds the one genuinely new piece: turning a ClayMatch row (company
name + website, no Salesforce account) into something unified_worker.py
/ run_custom_vertical_worker.py can process.
"""

import csv
import hashlib
import os
import subprocess
import sys
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from . import models
from . import enrichment
from . import clay_import
from . import supabase_client


class ClayDispatchError(Exception):
    """A problem with the dispatch request itself -- caught by main.py and
    turned into a 400, same convention as enrichment.DispatchError."""
    pass


def compute_pseudo_account_id(company_name: Optional[str], website: Optional[str]) -> str:
    """A stable, deterministic stand-in for a Salesforce account_id, for a
    company that has no Salesforce account. Deliberately NOT a random
    uuid -- the whole point (Jeff, 2026-11-18, scoping answer #1) is that
    importing the SAME export again next month and selecting the SAME
    company produces the SAME id, so
    supabase_client.check_already_enriched() (the exact "any run_date"
    check enrichment.dispatch_job() already relies on) correctly
    recognizes it as already-processed instead of burning credits
    re-running it.

    Built from norm_domain()/norm_name() -- reused from
    account_eligibility.py via clay_dedupe.py's own import of them (not
    reimplemented here), so "the same company" means exactly what it
    already means everywhere else in this codebase's identity matching.
    Domain preferred over name (same preference order clay_dedupe.py's
    own matching tiers use) since two companies are far more likely to
    coincidentally share a normalized name than a normalized domain.

    Format: "CLAY" + 14 hex chars of a sha1 digest = 18 characters total,
    matching the real Salesforce id's width (so this would still fit a
    String(18) column if this app ever moves to Postgres, per db.py's own
    "nothing else needs to change" migration note) and visually
    distinguishable from a real SF id (which starts with '001') at a
    glance.
    """
    domain = clay_import.clay_dedupe.norm_domain(website)
    name = clay_import.clay_dedupe.norm_name(company_name) if company_name else ""
    key = domain or name
    if not key:
        # Degenerate case: no usable name or website at all. Falling back
        # to a random id (rather than, say, a constant) avoids silently
        # merging every blank-identity row onto one shared pseudo-account
        # -- an unstable id for this one edge case is the lesser error.
        key = uuid.uuid4().hex
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return f"CLAY{digest[:14]}"


def dispatch_clay_rows(
    db: Session,
    clay_match_ids: list[int],
    vertical: str,
    created_by: Optional[str] = None,
    run_date: Optional[str] = None,
    disabled_channels: Optional[list[str]] = None,
    confirmed_protected: bool = False,
) -> dict:
    """Resolves the selected ClayMatch rows, computes each one's stable
    pseudo account_id, filters out companies already enriched for THIS
    vertical (any run_date, any earlier import -- same semantics
    enrichment.dispatch_job() already relies on for real accounts), writes
    the remainder to a batch CSV, and spawns the same worker subprocess
    enrichment.dispatch_job() would. Returns a summary dict shaped like
    dispatch_job()'s, OR {"requires_confirmation": True, "protected_rows":
    [...]} if any selected row is MATCHED_PROTECTED and confirmed_protected
    wasn't passed -- the caller (main.py's endpoint) surfaces that to the
    UI instead of dispatching anything; the UI re-sends with
    confirmed_protected=True once the human has seen the list and agreed.
    """
    if not clay_match_ids:
        raise ClayDispatchError("No rows selected.")

    known = enrichment._known_verticals(db)
    if vertical not in known:
        raise ClayDispatchError(
            f"Unknown or unsupported vertical '{vertical}'. Supported: {', '.join(known)}."
        )

    rows = (
        db.query(models.ClayMatch)
        .filter(models.ClayMatch.id.in_(clay_match_ids))
        .all()
    )
    found_ids = {r.id for r in rows}
    missing_ids = [cid for cid in clay_match_ids if cid not in found_ids]

    # A row with neither a company name nor a website gives every channel
    # nothing to search for and nothing for entity verification to check
    # against -- reject these explicitly rather than silently dispatching
    # a blank "account."
    usable_rows = [r for r in rows if (r.clay_company_name or r.clay_website)]
    unusable_ids = [r.id for r in rows if r not in usable_rows]

    # Scoping answer #3 (2026-11-18): protected rows are never silently
    # sent. This never hard-blocks -- Jeff might have a real reason (a
    # different division, a reassigned territory) -- it just can't
    # proceed without the human having seen exactly which rows and why.
    protected_rows = [r for r in usable_rows if r.classification == "MATCHED_PROTECTED"]
    if protected_rows and not confirmed_protected:
        return {
            "requires_confirmation": True,
            "protected_rows": [
                {
                    "id": r.id,
                    "clay_company_name": r.clay_company_name,
                    "matched_account_name": r.matched_account_name,
                    "exclusion_reasons": r.exclusion_reasons,
                }
                for r in protected_rows
            ],
        }

    pseudo_ids = {r.id: compute_pseudo_account_id(r.clay_company_name, r.clay_website) for r in usable_rows}

    try:
        already_enriched = supabase_client.check_already_enriched(
            list(set(pseudo_ids.values())), vertical
        )
    except supabase_client.SupabaseUnavailable as e:
        raise ClayDispatchError(str(e))

    to_dispatch = [r for r in usable_rows if pseudo_ids[r.id] not in already_enriched]
    if not to_dispatch:
        raise ClayDispatchError(
            f"All {len(usable_rows)} selected row(s) already have a completed "
            f"'{vertical}' enrichment result for this company (checked by company "
            "identity, across any prior import -- not just today's batch). "
            "Nothing to dispatch."
        )

    is_custom = vertical not in enrichment.DISPATCHABLE_VERTICALS
    worker_script = enrichment._custom_worker_script_path() if is_custom else enrichment._worker_script_path()
    if not worker_script.exists():
        raise ClayDispatchError(
            f"{'run_custom_vertical_worker.py' if is_custom else 'unified_worker.py'} not found at "
            f"{worker_script}. Set {'CUSTOM_VERTICAL_WORKER_PATH' if is_custom else 'UNIFIED_WORKER_PATH'} "
            f"if your repo layout differs."
        )

    run_date = run_date or date.today().isoformat()

    # Two selected rows can resolve to the same pseudo account_id (e.g. an
    # exact-match row and a brand-fuzzy row for the same real company) --
    # only send it to the worker once, but every original row still gets
    # its own ClayDispatch history entry below.
    seen: set[str] = set()
    dedup_rows = []
    for r in to_dispatch:
        pid = pseudo_ids[r.id]
        if pid in seen:
            continue
        seen.add(pid)
        dedup_rows.append(r)

    job_id = str(uuid.uuid4())
    job_dir = enrichment.JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    batch_file = job_dir / "batch.csv"
    log_file = job_dir / "worker.log"
    stdout_file = job_dir / "stdout.log"

    with open(batch_file, "w", newline="") as f:
        # Same column shape enrichment.dispatch_job() writes (and
        # run_custom_vertical_worker.py / unified_worker.py already read)
        # -- a Clay row has no state/country/industry/segment of its own
        # (clay_dedupe.py's optional City/State columns are used only for
        # match disambiguation, never persisted onto ClayMatch), so those
        # go in blank/defaulted exactly the way AccountContext already
        # handles a missing value for a real account.
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "account_id", "account_name", "website", "operating_market",
                "segment", "state", "country", "industry",
            ],
        )
        writer.writeheader()
        for r in dedup_rows:
            writer.writerow({
                "account_id": pseudo_ids[r.id],
                "account_name": r.clay_company_name or r.matched_account_name or "",
                "website": r.clay_website or "",
                "operating_market": "United States",
                "segment": "",
                "state": "",
                "country": "United States",
                "industry": "",
            })

    cmd = [
        sys.executable, str(worker_script), vertical, str(batch_file.resolve()),
        "--worker-id", "1", "--run-date", run_date,
    ]
    env = {**os.environ}
    for toggle_key, env_var in enrichment.CHANNEL_ENV_VARS.get(vertical, {}).items():
        env[env_var] = "false" if disabled_channels and toggle_key in disabled_channels else "true"

    with open(stdout_file, "w") as out:
        proc = subprocess.Popen(
            cmd, cwd=str(job_dir), stdout=out, stderr=subprocess.STDOUT,
            start_new_session=True, env=env,
        )

    job = models.EnrichmentJob(
        id=job_id,
        vertical=vertical,
        display_vertical=known[vertical],
        run_date=run_date,
        batch_file=str(batch_file.resolve()),
        log_file=str(log_file.resolve()),
        worker_script=str(worker_script.resolve()),
        pid=proc.pid,
        total_requested=len(clay_match_ids),
        total_dispatched=len(dedup_rows),
        skipped_already_enriched=len(already_enriched),
        status="running",
        started_at=datetime.utcnow(),
        created_by=created_by,
        source="clay_import",
    )
    db.add(job)
    db.add_all([
        models.EnrichmentJobAccount(job_id=job_id, account_id=pseudo_ids[r.id])
        for r in dedup_rows
    ])
    # One history row per SELECTED row (not just the deduplicated set
    # actually sent to the worker), so the Clay review table can show
    # every row's own outcome -- including a row that was skipped because
    # a prior import already fully processed that same company.
    db.add_all([
        models.ClayDispatch(
            clay_match_id=r.id,
            job_id=job_id,
            account_id=pseudo_ids[r.id],
            vertical=vertical,
            status="skipped_already_enriched" if pseudo_ids[r.id] in already_enriched else "dispatched",
        )
        for r in usable_rows
    ])
    db.commit()

    return {
        "requires_confirmation": False,
        "job_id": job_id,
        "vertical": vertical,
        "run_date": run_date,
        "total_requested": len(clay_match_ids),
        "total_dispatched": len(dedup_rows),
        "skipped_already_enriched": len(already_enriched),
        "missing_ids": missing_ids,
        "unusable_ids": unusable_ids,
        "pid": proc.pid,
    }
