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


def _is_custom_vertical_key(session: Session, vertical: str) -> bool:
    """Added 2026-11-18, alongside custom_verticals.match_accounts_to_
    custom_verticals: `vertical` can now mean either one of Stage B's 7
    fixed classification labels (models.ClassificationRun.vertical, e.g.
    "Health Care Services") or a custom vertical's vertical_key (e.g.
    "assisted_living_dayrooms", tagged into CustomVerticalMatch by the
    separate, additive matching pass). These are two different,
    non-overlapping namespaces -- a custom vertical_key is always a
    create_custom_vertical-validated slug, never one of the 7 fixed
    labels. This one cheap lookup (not a per-row check) decides which
    table _filtered_accounts_query should actually filter against,
    without touching the existing ClassificationRun path at all when the
    answer is no."""
    return session.execute(
        select(models.CustomVertical.vertical_key).where(models.CustomVertical.vertical_key == vertical)
    ).first() is not None


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
    is_custom_vertical: bool = False,
):
    """Shared join + filter logic behind both the paginated triage table
    (list_accounts) and the select-all-filtered id resolver
    (resolve_filtered_account_ids) — kept in one place so the two can never
    drift into filtering accounts differently.

    is_custom_vertical (2026-11-18): when True, `vertical` is filtered
    against CustomVerticalMatch instead of ClassificationRun -- see
    _is_custom_vertical_key's docstring. The CustomVerticalMatch join is
    added ONLY in this branch (not unconditionally alongside
    ClassificationRun/SegmentationRun above), and its ON clause already
    restricts to this specific vertical_key + run_date, so it can never
    fan an account out into duplicate rows the way an unconditional join
    (matching every vertical_key an account happens to satisfy) would —
    an account matches at most one row for one specific vertical_key per
    run_date, per CustomVerticalMatch's own unique constraint."""
    conditions = [models.EligibilityRun.run_date == elig_date]
    if vertical and not is_custom_vertical:
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

    query = (
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
    )

    if vertical and is_custom_vertical:
        # INNER join, added ONLY in this branch -- deliberately not an
        # outerjoin alongside ClassificationRun/SegmentationRun above,
        # since those two exist for every safe account regardless of
        # filter, while this one should only ever narrow the result to
        # accounts that actually matched THIS vertical_key. The ON
        # clause already pins both vertical_key and run_date, so this
        # can't fan an account out into duplicate rows (see
        # _filtered_accounts_query's docstring).
        query = query.join(models.CustomVerticalMatch, and_(
            models.CustomVerticalMatch.account_id == models.Account.account_id,
            models.CustomVerticalMatch.vertical_key == vertical,
            models.CustomVerticalMatch.run_date == elig_date,
        ))

    return query.where(and_(*conditions))


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

    is_custom_vertical = bool(vertical) and _is_custom_vertical_key(session, vertical)
    base_query = _filtered_accounts_query(
        elig_date, vertical, segment, excluded,
        country=country, operating_market=operating_market,
        capacity_type=capacity_type, capacity_min=capacity_min, capacity_max=capacity_max,
        is_custom_vertical=is_custom_vertical,
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

    is_custom_vertical = bool(vertical) and _is_custom_vertical_key(session, vertical)
    query = _filtered_accounts_query(
        elig_date, vertical, segment, excluded,
        country=country, operating_market=operating_market,
        capacity_type=capacity_type, capacity_min=capacity_min, capacity_max=capacity_max,
        columns=[models.Account.account_id],
        is_custom_vertical=is_custom_vertical,
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
    """Human-review queue for Clay dedupe rows: either >1 Salesforce
    candidate (can't safely auto-pick between equally-plausible matches),
    or a POSSIBLE_MATCH_BRAND row (clay_dedupe.py's brand-root fuzzy
    tier, added 2026-11-16 -- Jeff: "Exact match is useless for me").
    A brand-root hit belongs here even with exactly one candidate, since
    fuzzy matching is never auto-trusted the way an exact domain/name
    match is -- same review discipline, just a different reason for
    needing it. matched_account_id/name included (not just classification/
    match_method) since a reviewer needs to see WHICH Salesforce account
    is being proposed as the match, not just that one exists."""
    conditions = [
        (models.ClayMatch.num_candidates > 1)
        | (models.ClayMatch.classification == "POSSIBLE_MATCH_BRAND")
    ]
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
                "match_method": r.match_method, "match_confidence": r.match_confidence,
                "matched_account_id": r.matched_account_id,
                "matched_account_name": r.matched_account_name,
                "num_candidates": r.num_candidates,
                "ai_verdict": r.ai_verdict,
                "ai_reasoning": r.ai_reasoning,
                "ai_verified_at": r.ai_verified_at.isoformat() if r.ai_verified_at else None,
                "ai_check_cost": r.ai_check_cost,
            }
            for r in rows
        ],
    }


def clay_batch_rows(
    session: Session,
    batch_id: str,
    search: Optional[str] = None,
    classification: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    """Every row from one Clay dedupe run, not just the ambiguous/brand
    subset clay_ambiguous_queue() filters to. Jeff (2026-11-16): "show a
    table of the account and the possible matches... call out which ones
    are net new" -- the classification bullet list ClayImport renders
    today tells you COUNTS but not which specific rows are NET_NEW vs. a
    brand match vs. an exact one, and there was no single place to see
    every row from a run side by side. This is that table's backend,
    same paginated/searchable/filterable shape as duplicate_detection.
    query_rows() in the Duplicates tab.

    classification_counts covers the WHOLE batch (unaffected by search/
    classification filters) so the UI's filter chips can show accurate
    counts even while a filter is narrowing what's actually displayed."""
    base_conditions = [models.ClayMatch.batch_id == batch_id]
    base_query = select(models.ClayMatch).where(and_(*base_conditions))

    total_in_batch = session.execute(
        select(func.count()).select_from(base_query.subquery())
    ).scalar_one()
    if total_in_batch == 0:
        return None  # caller turns this into a 404 -- batch_id doesn't exist

    classification_counts = dict(
        session.execute(
            select(models.ClayMatch.classification, func.count())
            .where(and_(*base_conditions))
            .group_by(models.ClayMatch.classification)
        ).all()
    )

    conditions = list(base_conditions)
    if classification:
        conditions.append(models.ClayMatch.classification == classification)
    if search and search.strip():
        needle = f"%{search.strip().lower()}%"
        conditions.append(
            func.lower(func.coalesce(models.ClayMatch.clay_company_name, ""))
            .like(needle)
            | func.lower(func.coalesce(models.ClayMatch.clay_website, ""))
            .like(needle)
            | func.lower(func.coalesce(models.ClayMatch.matched_account_name, ""))
            .like(needle)
        )

    filtered_query = select(models.ClayMatch).where(and_(*conditions))
    total_rows = session.execute(
        select(func.count()).select_from(filtered_query.subquery())
    ).scalar_one()
    page = max(page, 1)
    page_size = max(min(page_size, 500), 1)
    rows = session.execute(
        filtered_query.order_by(models.ClayMatch.id)
        .offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()

    return {
        "total_rows": total_rows,
        "classification_counts": classification_counts,
        "page": page,
        "page_size": page_size,
        "rows": [
            {
                "id": r.id, "clay_company_name": r.clay_company_name,
                "clay_website": r.clay_website, "classification": r.classification,
                "match_method": r.match_method, "match_confidence": r.match_confidence,
                "matched_account_id": r.matched_account_id,
                "matched_account_name": r.matched_account_name,
                "num_candidates": r.num_candidates,
                "ai_verdict": r.ai_verdict,
                "ai_reasoning": r.ai_reasoning,
                "ai_verified_at": r.ai_verified_at.isoformat() if r.ai_verified_at else None,
                "ai_check_cost": r.ai_check_cost,
            }
            for r in rows
        ],
    }


def clay_batch_rows_by_ids(session: Session, batch_id: str, ids: list[int]):
    """The exact rows (by ClayMatch.id) to export -- backs "export
    selected" so the export reflects exactly what was checked, not a
    filter re-applied (a filter can produce a different row set if the
    underlying data changed between viewing and exporting)."""
    rows = session.execute(
        select(models.ClayMatch).where(
            and_(models.ClayMatch.batch_id == batch_id, models.ClayMatch.id.in_(ids))
        ).order_by(models.ClayMatch.id)
    ).scalars().all()
    return [
        {
            "id": r.id, "clay_company_name": r.clay_company_name,
            "clay_website": r.clay_website, "classification": r.classification,
            "match_method": r.match_method, "match_confidence": r.match_confidence,
            "matched_account_id": r.matched_account_id,
            "matched_account_name": r.matched_account_name,
            "num_candidates": r.num_candidates,
            "ai_verdict": r.ai_verdict,
            "ai_reasoning": r.ai_reasoning,
            "ai_verified_at": r.ai_verified_at.isoformat() if r.ai_verified_at else None,
            "ai_check_cost": r.ai_check_cost,
        }
        for r in rows
    ]


def clay_ai_verification_cost_rollup(session: Session) -> dict:
    """Cost rollup for the AI brand-verification "Check with AI" button
    (2026-11-16, Jeff: "when i click on AI Check are we cost tracking
    that?" -- it wasn't; this is the fix). Lives in local SQLite
    (clay_matches), not Supabase like the vertical enrichers' cost rows,
    so this is computed separately and merged into GET /cost-tracker
    rather than coming from supabase_client.get_cost_tracker_rollup.
    Shaped to match CostTrackerChannelRow on the frontend: prospect_count/
    suspect_count/is_prospect_mismatches don't apply to a same/different/
    uncertain verdict (it's not a PROSPECT/SUSPECT pipeline), so those are
    always 0 here rather than forced into a meaning they don't have."""
    checked = session.execute(
        select(func.count(), func.coalesce(func.sum(models.ClayMatch.ai_check_cost), 0.0))
        .where(models.ClayMatch.ai_verified_at.is_not(None))
    ).one()
    checked_count, total_cost = checked
    return {
        "vertical": "clay_brand_verification",
        "channel": "ai_verify",
        "accounts_processed": checked_count,
        "prospect_count": 0,
        "suspect_count": 0,
        "rows_with_cost": checked_count,
        "total_cost": float(total_cost or 0.0),
        "is_prospect_mismatches": 0,
    }


def clay_ai_tool_cost_rollup(session: Session) -> list[dict]:
    """The Clay AI-check spend restated by TOOL instead of by channel
    (2026-11-16, Jeff: "do we have a breakdown of spend by tool used").
    Trivial here -- the "Check with AI" button only ever calls one tool
    (Claude Sonnet 4.5), so this is the same total as
    clay_ai_verification_cost_rollup, just relabeled onto the
    "anthropic_claude" bucket so it merges cleanly with the vertical
    enrichers' by-tool rollup (which also uses that exact bucket name
    for their own Claude VLM calls)."""
    channel_row = clay_ai_verification_cost_rollup(session)
    if channel_row["rows_with_cost"] == 0:
        return []
    return [{
        "vertical": "clay_brand_verification",
        "tool": "anthropic_claude",
        "rows_with_cost": channel_row["rows_with_cost"],
        "total_cost": channel_row["total_cost"],
    }]
