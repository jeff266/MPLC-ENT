"""
Clay/ZoomInfo-export-to-Salesforce dedupe, wired into the actual app.

Jeff (2026-11-14): "So one of the core use cases I have is to export data
from ZoomInfo or Clay, and I need to be able to cross-reference against
what's in Salesforce and what's not. Does our application already do
this?" -- it did not: clay_dedupe.py (production/workers/) was a real,
working, well-tested standalone CLI tool, and the UI already had a
"Clay Ambiguous" review tab (queries.clay_ambiguous_queue /
ClayAmbiguousQueue.tsx) reading from models.ClayMatch -- but nothing in
the app ever WROTE a ClayMatch row. The tab was permanently empty because
no code path existed between "upload a Clay/ZoomInfo export" and "see it
in the review queue."

This module is that missing path. It does NOT reimplement the matching
logic -- it imports clay_dedupe.py's real run_clay_dedupe_df() /
detect_column_mapping() (same functions, same tests already run against
them) and just supplies the two things the CLI version expected as
separate file uploads:
  - the Salesforce universe -> sourced from this app's own `accounts`
    table (populated weekly by Stage 1's CSV upload), so Jeff doesn't
    have to re-export/re-upload Salesforce data just to run a dedupe.
  - the protected/available signal -> sourced from the latest
    eligibility_runs.excluded per account, same "latest run per account"
    pattern queries.py already uses elsewhere (_latest_run_date).

Also answers Jeff's follow-up ("naming of the columns may be
inconsistent... how do I account for that?"): detect_column_mapping()
(exact-candidate + fuzzy-token fallback, already built and tested in
clay_dedupe.py) is used here ONLY to pre-fill a suggested mapping --
detect_columns() below returns it to the UI as a suggestion, and
run_import() takes an optional human-confirmed column_mapping that
always overrides the guess. Auto-detection is never trusted blind, per
this engagement's entity-attribution QA bar (CLAUDE.md): a column
mis-mapped to the wrong field is a worse, silent error than a column
correctly flagged "couldn't detect, please specify."
"""

import io
import sys
import uuid
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from . import queries

# Reuse the real, already-tested matching logic rather than reimplementing
# it here -- same import pattern fireworks_vlm_pilot.py already uses to
# reach into production/ from a sibling tree.
_WORKERS_DIR = Path(__file__).resolve().parent.parent.parent / "MPLC" / "production" / "workers"
if str(_WORKERS_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKERS_DIR))

import clay_dedupe  # noqa: E402


class ClayImportError(Exception):
    """Raised for a bad upload (unreadable file, missing required columns
    even after an explicit mapping) -- caught by main.py and turned into a
    400, same convention as enrichment.DispatchError."""
    pass


def _read_export_file(filename: str, file_bytes: bytes) -> pd.DataFrame:
    """Clay/ZoomInfo exports are usually CSV; be tolerant of the encoding
    quirks clay_dedupe.py's own CLI already works around (latin-1, not
    strictly utf-8 -- real exports have hit this before per that file's
    `encoding='latin-1'` reads)."""
    name = (filename or "").lower()
    try:
        if name.endswith((".xlsx", ".xls")):
            return pd.read_excel(io.BytesIO(file_bytes), dtype=str)
        try:
            return pd.read_csv(io.BytesIO(file_bytes), dtype=str, low_memory=False,
                                keep_default_na=True, encoding="utf-8")
        except UnicodeDecodeError:
            return pd.read_csv(io.BytesIO(file_bytes), dtype=str, low_memory=False,
                                keep_default_na=True, encoding="latin-1")
    except Exception as e:
        raise ClayImportError(f"Could not read '{filename}' as a CSV/Excel export: {e}")


def detect_columns(filename: str, file_bytes: bytes) -> dict:
    """Best-guess column mapping for an uploaded Clay/ZoomInfo/other export,
    for the UI to show as an editable pre-filled form -- never applied
    without the human confirming (or overriding) it first."""
    df = _read_export_file(filename, file_bytes)
    mapping = clay_dedupe.detect_column_mapping(df)
    return {
        "columns": list(df.columns),
        "detected_mapping": mapping,
        "row_count": len(df),
        "preview_rows": df.head(5).fillna("").to_dict("records"),
    }


def _build_sf_universe_df(db: Session) -> pd.DataFrame:
    """The Salesforce side of the dedupe, sourced from this app's own
    `accounts` table instead of requiring a fresh CSV each time. Columns
    named to match what clay_dedupe.SFIndex's own candidate lists expect
    (SF_ACCOUNT_ID_COL_CANDIDATES etc. -- 'account_id' and 'Account Name'
    style names are already in those candidate lists)."""
    rows = db.execute(
        select(
            models.Account.account_id,
            models.Account.account_name,
            models.Account.website,
            models.Account.phone,
            models.Account.state,
        )
    ).all()
    if not rows:
        raise ClayImportError(
            "No Salesforce accounts found in this app's local database -- "
            "run the weekly pipeline's Stage 1 upload first so the "
            "`accounts` table is populated."
        )
    return pd.DataFrame(
        rows, columns=["account_id", "account_name", "website", "phone", "state"]
    )


def _build_eligibility_map(db: Session) -> Dict[str, bool]:
    """Protected/available signal from the latest eligibility_runs.excluded
    per account -- same "most recent run_date present" convention
    queries.py's _latest_run_date already uses for every other review
    queue in this app, so this isn't a new concept, just reused."""
    latest_date = queries._latest_run_date(db, models.EligibilityRun, None)
    if not latest_date:
        return {}  # no eligibility run has been recorded yet -- fine, just
                   # means every match classifies as MATCHED_UNKNOWN instead
                   # of MATCHED_PROTECTED/AVAILABLE (clay_dedupe.py's own
                   # documented behavior when no eligibility_map is given).
    rows = db.execute(
        select(models.EligibilityRun.account_id, models.EligibilityRun.excluded)
        .where(models.EligibilityRun.run_date == latest_date)
    ).all()
    return {account_id: bool(excluded) for account_id, excluded in rows}


def run_import(
    db: Session,
    filename: str,
    file_bytes: bytes,
    column_mapping: Optional[Dict[str, Optional[str]]] = None,
    max_group_size: int = 50,
) -> dict:
    """Runs the real clay_dedupe.run_clay_dedupe_df() against this app's
    own Salesforce universe + eligibility data, persists every result row
    as a models.ClayMatch under a new batch_id, and returns a summary.
    Ambiguous rows (num_candidates > 1) immediately show up in the
    existing "Clay Ambiguous" tab -- no change needed there, it already
    reads ClayMatch; it just never had rows to show before."""
    clay_df = _read_export_file(filename, file_bytes)
    sf_df = _build_sf_universe_df(db)
    eligibility_map = _build_eligibility_map(db)

    try:
        result_df = clay_dedupe.run_clay_dedupe_df(
            clay_df, sf_df,
            column_mapping=column_mapping,
            eligibility_map=eligibility_map,
            max_group_size=max_group_size,
            verbose=False,
        )
    except ValueError as e:
        # run_clay_dedupe_df raises ValueError when required fields
        # (company_name/website) don't resolve to a real column, even
        # after applying column_mapping -- surface that as-is, it already
        # names the resolved mapping and the real columns present.
        raise ClayImportError(str(e))

    batch_id = str(uuid.uuid4())
    for _, row in result_df.iterrows():
        db.add(models.ClayMatch(
            batch_id=batch_id,
            clay_company_name=row.get("clay_company_name"),
            clay_website=row.get("clay_website"),
            classification=row["classification"],
            match_method=row.get("match_method"),
            match_confidence=row.get("match_confidence"),
            matched_account_id=row.get("matched_account_id"),
            matched_account_name=row.get("matched_account_name"),
            num_candidates=int(row["num_candidates"]),
        ))
    db.commit()

    counts = result_df["classification"].value_counts().to_dict()
    ambiguous_count = int((result_df["num_candidates"] > 1).sum())
    return {
        "batch_id": batch_id,
        "rows_processed": len(result_df),
        "classification_counts": counts,
        "ambiguous_count": ambiguous_count,
        "eligibility_data_available": bool(eligibility_map),
    }
