"""
Runs the already-validated weekly_pipeline.py (Stage A/B/C) and persists
its results into the DB tables in models.py — instead of leaving the UI to
re-parse the ~190 per-vertical CSVs the pipeline also writes to disk.

Does NOT change weekly_pipeline.py / stage_a_protection.py / etc. at all —
this is a persistence layer on top of their existing, validated return
values and output files, so none of that validated logic is touched.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, UTC
from typing import Optional

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

_ORCHESTRATOR_DIR = Path(__file__).parent.parent.parent / "orchestrator"
sys.path.insert(0, str(_ORCHESTRATOR_DIR))

from weekly_pipeline import run_weekly_pipeline  # noqa: E402

from . import models

_CHUNK = 5000


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _upsert_accounts(session: Session, audit_df: pd.DataFrame):
    """Upsert into accounts — refreshed in place, never re-inserted for an
    existing account_id (per the models.py design note)."""
    col_map = {
        '18 Digit Account ID': 'account_id',
        'Account Name': 'account_name',
        'Website': 'website',
        'Account Status': 'account_status',
        'Parent Account ID': 'parent_account_id',
        'Industry': 'industry',
        'Account Sub Industry': 'account_sub_industry',
        'Account State/Province (text only)': 'state',
        'Phone': 'phone',
        'Created Date': 'created_date',
        'Last Modified Date': 'last_modified_date',
        'Last Activity': 'last_activity',
    }
    present = {k: v for k, v in col_map.items() if k in audit_df.columns}
    sub = audit_df[list(present.keys())].rename(columns=present)
    sub = sub.where(pd.notna(sub), None)
    records = sub.to_dict('records')

    table = models.Account.__table__
    for chunk in _chunks(records, _CHUNK):
        stmt = sqlite_insert(table).values(chunk)
        update_cols = {c: stmt.excluded[c] for c in present.values() if c != 'account_id'}
        stmt = stmt.on_conflict_do_update(index_elements=['account_id'], set_=update_cols)
        session.execute(stmt)


def _insert_eligibility_runs(session: Session, audit_df: pd.DataFrame, run_date: str):
    sub = audit_df[['18 Digit Account ID', 'excluded', 'exclusion_reasons']].rename(
        columns={'18 Digit Account ID': 'account_id'}
    )
    sub['run_date'] = run_date
    sub = sub.where(pd.notna(sub), None)
    records = sub.to_dict('records')

    table = models.EligibilityRun.__table__
    for chunk in _chunks(records, _CHUNK):
        stmt = sqlite_insert(table).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=['account_id', 'run_date'],
            set_={'excluded': stmt.excluded.excluded, 'exclusion_reasons': stmt.excluded.exclusion_reasons},
        )
        session.execute(stmt)


def _insert_classification_runs(session: Session, vertical_dataframes: dict, run_date: str):
    table = models.ClassificationRun.__table__
    id_col_candidates = ['18 Digit Account ID', 'Account ID']

    for vertical, df in vertical_dataframes.items():
        id_col = next((c for c in id_col_candidates if c in df.columns), None)
        if id_col is None:
            continue
        records = [
            {'account_id': aid, 'run_date': run_date, 'vertical': vertical}
            for aid in df[id_col].tolist()
        ]
        for chunk in _chunks(records, _CHUNK):
            stmt = sqlite_insert(table).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=['account_id', 'run_date'],
                set_={'vertical': stmt.excluded.vertical},
            )
            session.execute(stmt)


def _insert_segmentation_runs_from_audit_log(session: Session, roe_audit_log_path: Path, run_date: str):
    """Stage C's run_roe_segmentation() doesn't return the per-account audit
    fields (Confidence/Reason/Missing Data/Edge Case) in-memory — it writes
    them to <run_date>_roe_audit_log.csv. Read that back rather than
    modifying the validated stage_c_segmentation.py to also return it."""
    if not roe_audit_log_path.exists():
        return
    audit = pd.read_csv(roe_audit_log_path, dtype=str)
    audit = audit.rename(columns={
        '18 Digit Account ID': 'account_id',
        'Vertical': 'vertical',
        'Segment': 'segment',
        'Confidence': 'confidence',
        'Reason': 'reason',
        'Missing Data': 'missing_data',
        'Edge Case': 'edge_case',
    })
    audit['run_date'] = run_date
    keep = ['account_id', 'run_date', 'vertical', 'segment', 'confidence', 'reason',
            'missing_data', 'edge_case']
    audit = audit[[c for c in keep if c in audit.columns]]
    audit = audit.where(pd.notna(audit), None)
    records = audit.to_dict('records')

    table = models.SegmentationRun.__table__
    for chunk in _chunks(records, _CHUNK):
        stmt = sqlite_insert(table).values(chunk)
        update_cols = {c: stmt.excluded[c] for c in keep if c not in ('account_id', 'run_date')}
        stmt = stmt.on_conflict_do_update(
            index_elements=['account_id', 'run_date'], set_=update_cols
        )
        session.execute(stmt)


def run_and_persist(
    session: Session,
    salesforce_export_path: str,
    output_dir: str,
    run_date: str,
    open_deals_path: str,
    activity_90_days_path: Optional[str] = None,
    lost_deals_9_months_path: Optional[str] = None,
    max_identity_cluster_size: int = 50,
    verbose: bool = True,
) -> dict:
    """Runs weekly_pipeline.run_weekly_pipeline() and persists Stage A/B/C
    results into the DB. Returns a summary dict (also stored as counts_json
    on the PipelineRun row)."""

    run_id = f"{run_date}_full"
    run_row = models.PipelineRun(
        run_id=run_id, run_date=run_date, stage="ALL", status="running",
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.merge(run_row)
    session.commit()

    try:
        results = run_weekly_pipeline(
            salesforce_export_path=salesforce_export_path,
            protected_accounts_path=None,
            output_dir=output_dir,
            run_date=run_date,
            open_deals_path=open_deals_path,
            activity_90_days_path=activity_90_days_path,
            lost_deals_9_months_path=lost_deals_9_months_path,
            max_identity_cluster_size=max_identity_cluster_size,
            verbose=verbose,
        )

        audit_df = results['stage_a']['audit_df']
        if verbose:
            print("Persisting Stage A (accounts + eligibility_runs)...")
        _upsert_accounts(session, audit_df)
        session.commit()
        _insert_eligibility_runs(session, audit_df, run_date)
        session.commit()

        if verbose:
            print("Persisting Stage B (classification_runs)...")
        _insert_classification_runs(session, results['stage_b']['dataframes'], run_date)
        session.commit()

        if verbose:
            print("Persisting Stage C (segmentation_runs)...")
        roe_audit_log_path = Path(output_dir) / f"{run_date}_roe_audit_log.csv"
        _insert_segmentation_runs_from_audit_log(session, roe_audit_log_path, run_date)
        session.commit()

        summary = {
            'stage_a': {'safe_count': results['stage_a']['safe_count'],
                        'excluded_count': results['stage_a']['excluded_count']},
            'stage_b': {'verticals': results['stage_b']['verticals']},
            'stage_c': {'segments': results['stage_c']['segments']},
        }

        run_row.status = "completed"
        run_row.counts_json = json.dumps(summary)
        run_row.finished_at = datetime.now(UTC).replace(tzinfo=None)
        session.merge(run_row)
        session.commit()

        return summary

    except Exception as e:
        run_row.status = "failed"
        run_row.error_message = str(e)
        run_row.finished_at = datetime.now(UTC).replace(tzinfo=None)
        session.merge(run_row)
        session.commit()
        raise
