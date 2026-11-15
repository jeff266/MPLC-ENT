"""
Backend wiring for internal Salesforce duplicate/sibling detection.

Jeff (2026-11-14): "there's quite a few accounts with exact same names or
website and should be identified as either a duplicate or a sibling
account... export a file with the findings in a CSV which I can send to
support at MPLC."

Mirrors clay_import.py's pattern: the real matching logic lives in
production/workers/internal_duplicate_detection.py (DataFrame-in,
DataFrame-out, independently tested), this module just sources the
account universe from the app's own `accounts` table and exposes it to
the API/CSV layer.
"""

import csv
import io
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models

_WORKERS_DIR = Path(__file__).resolve().parent.parent.parent / "MPLC" / "production" / "workers"
if str(_WORKERS_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKERS_DIR))

import internal_duplicate_detection  # noqa: E402


class DuplicateDetectionError(Exception):
    pass


def _build_accounts_df(db: Session) -> pd.DataFrame:
    rows = db.execute(
        select(
            models.Account.account_id,
            models.Account.account_name,
            models.Account.website,
            models.Account.phone,
            models.Account.state,
            models.Account.industry,
            models.Account.parent_account_id,
        )
    ).all()
    if not rows:
        raise DuplicateDetectionError(
            "No Salesforce accounts found in this app's local database -- "
            "run the weekly pipeline's Stage 1 upload first so the "
            "`accounts` table is populated."
        )
    return pd.DataFrame(
        rows,
        columns=["account_id", "account_name", "website", "phone", "state",
                 "industry", "parent_account_id"],
    )


def find_duplicates(db: Session, max_group_size: int = 50) -> pd.DataFrame:
    accounts_df = _build_accounts_df(db)
    return internal_duplicate_detection.find_internal_duplicates(
        accounts_df,
        max_group_size=max_group_size,
        exclude_already_parented=True,  # Filter out child accounts - only show orphaned duplicates
    )


def summarize(db: Session, max_group_size: int = 50) -> dict:
    """JSON-friendly summary for the UI: counts + a capped preview, not the
    full (potentially large) row set -- the CSV export is the full dump."""
    accounts_df = _build_accounts_df(db)

    # Jeff (2026-11-14): after adding exclude_already_parented, the result
    # was byte-for-byte unchanged even for an account he could show had a
    # real parent in Salesforce's own UI. Root cause (confirmed against
    # the real weekly export CSV): 0 of 86,300 accounts in that file had a
    # non-empty "Parent Account ID" -- the export itself wasn't carrying
    # the field, not a bug in the exclusion logic. Surface that distinction
    # up front so "no duplicates found because everything's organized" and
    # "no duplicates excluded because there's no parent data to exclude by"
    # are never silently indistinguishable again.
    has_any_parent_data = bool(
        (accounts_df["parent_account_id"].notna() & (accounts_df["parent_account_id"] != "")).any()
    )

    result_df = internal_duplicate_detection.find_internal_duplicates(
        accounts_df, max_group_size=max_group_size,
    )
    n_groups = int(result_df["group_id"].nunique()) if len(result_df) else 0
    n_already_hierarchical = int(
        result_df.loc[result_df["already_hierarchical"], "group_id"].nunique()
    ) if len(result_df) else 0
    counts = (
        result_df.drop_duplicates("group_id")["match_type"].value_counts().to_dict()
        if len(result_df) else {}
    )
    preview = result_df.head(200).fillna("").to_dict("records")
    return {
        "total_groups": n_groups,
        "total_accounts_flagged": int(result_df["account_id"].nunique()) if len(result_df) else 0,
        "groups_already_hierarchical": n_already_hierarchical,
        "counts_by_type": counts,
        "preview_rows": preview,
        "preview_truncated": len(result_df) > len(preview),
        "has_any_parent_data": has_any_parent_data,
    }


def export_csv(db: Session, max_group_size: int = 50) -> str:
    result_df = find_duplicates(db, max_group_size=max_group_size)
    buf = io.StringIO()
    if len(result_df):
        result_df.to_csv(buf, index=False, quoting=csv.QUOTE_MINIMAL)
    else:
        buf.write(
            "group_id,match_type,account_id,account_name,website,phone,state,"
            "industry,parent_account_id,already_hierarchical,group_size\n"
        )
    return buf.getvalue()
