"""
Query helpers for the triage table and review queues. Kept separate from
main.py so the "latest run per account" logic (the one non-trivial part of
querying an append-only, run-versioned schema) lives in one place.
"""

from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from . import models


def _latest_run_date(session: Session, model, run_date: Optional[str]) -> Optional[str]:
    """If run_date wasn't given, use the most recent one present for this
    table, so the UI doesn't have to know the latest run_date up front."""
    if run_date:
        return run_date
    return session.execute(select(func.max(model.run_date))).scalar_one_or_none()


def _filtered_accounts_query(
    elig_date: str,
    vertical: Optional[str] = None,
    segment: Optional[str] = None,
    excluded: Optional[bool] = None,
    country: Optional[str] = None,
    operating_market: Optional[str] = None,
    capacity_type: Optional[str] = None,
    capacity_min: Optional[int] = None,
    capacity_max: Optional[int] = None,
    columns: Optional[list] = None,
):
    """Shared join + filter logic behind both the paginated triage table
    (list_accounts) and the select-all-filtered id resolver
    (resolve_filtered_account_ids) — kept in one place so the two can never
    drift into filtering accounts differently."""
    conditions = [models.EligibilityRun.run_date == elig_date]
    if vertical:
        conditions.append(models.ClassificationRun.vertical == vertical)
    if segment:
        conditions.append(models.SegmentationRun.segment == segment)
    if excluded is not None:
        conditions.append(models.EligibilityRun.excluded == excluded)
    if country:
        conditions.append(models.Account.country == country)
    if operating_market:
        conditions.append(models.Account.operating_market == operating_market)
    if capacity_type:
        conditions.append(models.Account.capacity_type == capacity_type)
    if capacity_min is not None:
        conditions.append(models.Account.capacity >= capacity_min)
    if capacity_max is not None:
        conditions.append(models.Account.capacity <= capacity_max)

    cols = columns or [
        models.Account.account_id,
        models.Account.account_name,
        models.Account.website,
        models.Account.state,
        models.Account.country,
        models.Account.operating_market,
        models.Account.capacity,
        models.Account.capacity_type,
        models.Account.industry,
        models.EligibilityRun.excluded,
        models.EligibilityRun.exclusion_reasons,
        models.ClassificationRun.vertical,
        models.SegmentationRun.segment,
        models.SegmentationRun.confidence,
        models.SegmentationRun.reason,
        models.SegmentationRun.edge_case,
    ]

    return (
        select(*cols)
        .join(models.EligibilityRun, models.EligibilityRun.account_id == models.Account.account_id)
        # LEFT OUTER, not inner: Stage B/C only ever run on the "safe"
        # (non-excluded) subset, so an excluded account has no
        # classification_runs/segmentation_runs row at all for this
        # run_date. An inner join here silently drops every excluded
        # account from the result regardless of the `excluded` filter —
        # caught this via a real smoke test against the populated DB
        # (excluded=true returned 0 rows when it should return 343,944).
        .outerjoin(models.ClassificationRun, and_(
            models.ClassificationRun.account_id == models.Account.account_id,
            models.ClassificationRun.run_date == elig_date,
        ))
        .outerjoin(models.SegmentationRun, and_(
            models.SegmentationRun.account_id == models.Account.account_id,
            models.SegmentationRun.run_date == elig_date,
        ))
        .where(and_(*conditions))
    )


def list_accounts(
    session: Session,
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
):
    """Paginated, server-side-filtered account list — joins the latest
    eligibility/classification/segmentation run for run_date onto accounts.
    This is the backing query for the core triage table."""
    elig_date = _latest_run_date(session, models.EligibilityRun, run_date)
    if elig_date is None:
        return {"run_date": None, "total": 0, "page": page, "page_size": page_size, "rows": []}

    base_query = _filtered_accounts_query(
        elig_date, vertical, segment, excluded,
        country=country, operating_market=operating_market,
        capacity_type=capacity_type, capacity_min=capacity_min, capacity_max=capacity_max,
    )

    total = session.execute(
        select(func.count()).select_from(base_query.subquery())
    ).scalar_one()

    rows = session.execute(
        base_query.order_by(models.Account.account_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return {
        "run_date": elig_date,
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [dict(r._mapping) for r in rows],
    }


def resolve_filtered_account_ids(
    session: Session,
    run_date: Optional[str] = None,
    vertical: Optional[str] = None,
    segment: Optional[str] = None,
    excluded: Optional[bool] = None,
    country: Optional[str] = None,
    operating_market: Optional[str] = None,
    capacity_type: Optional[str] = None,
    capacity_min: Optional[int] = None,
    capacity_max: Optional[int] = None,
    exclude_account_ids: Optional[list[str]] = None,
) -> list[str]:
    """"Select all N filtered rows" resolved server-side — the frontend
    never has to pull thousands of ids into the browser just to submit a
    batch action. exclude_account_ids covers "select all, then manually
    uncheck a couple" without needing a separate code path."""
    elig_date = _latest_run_date(session, models.EligibilityRun, run_date)
    if elig_date is None:
        return []

    query = _filtered_accounts_query(
        elig_date, vertical, segment, excluded,
        country=country, operating_market=operating_market,
        capacity_type=capacity_type, capacity_min=capacity_min, capacity_max=capacity_max,
        columns=[models.Account.account_id],
    )
    ids = [row[0] for row in session.execute(query).all()]
    if exclude_account_ids:
        exclude_set = set(exclude_account_ids)
        ids = [i for i in ids if i not in exclude_set]
    return ids


def accounts_by_ids(session: Session, account_ids: list[str], run_date: Optional[str] = None):
    """Full triage-row detail for a specific, already-selected set of
    account_ids — used by the "Find Enrichable Accounts" export, not the
    main paginated table. Same outer-join shape as list_accounts (an
    excluded account has no classification/segmentation row, so this must
    not inner-join those away either)."""
    elig_date = _latest_run_date(session, models.EligibilityRun, run_date)
    if elig_date is None or not account_ids:
        return []

    base_query = (
        select(
            models.Account.account_id,
            models.Account.account_name,
            models.Account.website,
            models.Account.state,
            models.Account.country,
            models.Account.operating_market,
            models.Account.capacity,
            models.Account.capacity_type,
            models.Account.industry,
            models.EligibilityRun.excluded,
            models.ClassificationRun.vertical,
            models.SegmentationRun.segment,
        )
        .join(models.EligibilityRun, and_(
            models.EligibilityRun.account_id == models.Account.account_id,
            models.EligibilityRun.run_date == elig_date,
        ))
        .outerjoin(models.ClassificationRun, and_(
            models.ClassificationRun.account_id == models.Account.account_id,
            models.ClassificationRun.run_date == elig_date,
        ))
        .outerjoin(models.SegmentationRun, and_(
            models.SegmentationRun.account_id == models.Account.account_id,
            models.SegmentationRun.run_date == elig_date,
        ))
        .where(models.Account.account_id.in_(account_ids))
    )
    rows = session.execute(base_query).all()
    return [dict(r._mapping) for r in rows]


def unresolved_queue(session: Session, run_date: Optional[str] = None,
                      vertical: Optional[str] = None, page: int = 1, page_size: int = 100):
    """Stage C's UNRESOLVED pile — currently 100% of Corporate/Healthcare/
    MDU (see roe_rules/*.py docstrings: missing breakroom_documented /
    facility_type / location_count sources, not a bug)."""
    seg_date = _latest_run_date(session, models.SegmentationRun, run_date)
    if seg_date is None:
        return {"run_date": None, "total": 0, "page": page, "page_size": page_size, "rows": []}

    conditions = [
        models.SegmentationRun.run_date == seg_date,
        models.SegmentationRun.segment == "UNRESOLVED",
    ]
    if vertical:
        conditions.append(models.SegmentationRun.vertical == vertical)

    base_query = (
        select(
            models.Account.account_id, models.Account.account_name,
            models.SegmentationRun.vertical, models.SegmentationRun.reason,
            models.SegmentationRun.missing_data, models.SegmentationRun.edge_case,
        )
        .join(models.SegmentationRun, models.SegmentationRun.account_id == models.Account.account_id)
        .where(and_(*conditions))
    )

    total = session.execute(select(func.count()).select_from(base_query.subquery())).scalar_one()
    rows = session.execute(
        base_query.order_by(models.SegmentationRun.vertical)
        .offset((page - 1) * page_size).limit(page_size)
    ).all()

    return {
        "run_date": seg_date, "total": total, "page": page, "page_size": page_size,
        "rows": [dict(r._mapping) for r in rows],
    }


def clay_ambiguous_queue(session: Session, batch_id: Optional[str] = None,
                          page: int = 1, page_size: int = 100):
    """Clay dedupe rows with >1 Salesforce candidate — needs a human pick."""
    conditions = [models.ClayMatch.num_candidates > 1]
    if batch_id:
        conditions.append(models.ClayMatch.batch_id == batch_id)

    base_query = select(models.ClayMatch).where(and_(*conditions))
    total = session.execute(select(func.count()).select_from(base_query.subquery())).scalar_one()
    rows = session.execute(
        base_query.order_by(models.ClayMatch.id)
        .offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()

    return {
        "total": total, "page": page, "page_size": page_size,
        "rows": [
            {
                "id": r.id, "clay_company_name": r.clay_company_name,
                "clay_website": r.clay_website, "classification": r.classification,
                "match_method": r.match_method, "num_candidates": r.num_candidates,
            }
            for r in rows
        ],
    }
