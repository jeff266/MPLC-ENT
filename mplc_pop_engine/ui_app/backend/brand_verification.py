"""
Backend wiring for AI brand-match verification (2026-11-16).

Jeff, after seeing brand-fuzzy POSSIBLE_MATCH_BRAND hits for Cortland,
Knightvest and Pantzer that he could confirm by eye are real Salesforce
matches under a different domain: "is there a way for the low confidence
to have claude api open up both websites and do a comparison?"

Mirrors clay_import.py's pattern: the real logic lives in
production/workers/brand_verify.py (DataFrame/dict-in-dict-out, tested in
isolation with mocks since it hits the live web + Anthropic API), this
module just sources the two pieces that core function needs from the
app's own DB -- the Clay row itself, and the matched Salesforce account's
website (ClayMatch only stores matched_account_id/name, not website) --
and persists the verdict back onto the row.
"""

import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models

_WORKERS_DIR = Path(__file__).resolve().parent.parent.parent / "MPLC" / "production" / "workers"
if str(_WORKERS_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKERS_DIR))

import brand_verify  # noqa: E402


class BrandVerificationError(Exception):
    """A bad request (row not found, or nothing to compare against) --
    caught by main.py and turned into a 400/404, same convention as
    DuplicateDetectionError/ClayImportError elsewhere in this app."""
    pass


def verify_row(db: Session, batch_id: str, row_id: int) -> dict:
    row = db.execute(
        select(models.ClayMatch).where(
            models.ClayMatch.id == row_id, models.ClayMatch.batch_id == batch_id
        )
    ).scalar_one_or_none()
    if row is None:
        raise BrandVerificationError(
            f"No Clay dedupe row with id {row_id} in batch {batch_id!r}."
        )
    if not row.matched_account_id:
        raise BrandVerificationError(
            "This row has no matched Salesforce account to compare against "
            "(it's NET_NEW) -- there's nothing to verify."
        )

    sf_account = db.execute(
        select(models.Account.website, models.Account.account_name)
        .where(models.Account.account_id == row.matched_account_id)
    ).first()
    sf_website = sf_account.website if sf_account else None

    result = brand_verify.verify_brand_match(
        clay_company_name=row.clay_company_name,
        clay_website=row.clay_website,
        sf_account_name=row.matched_account_name,
        sf_website=sf_website,
    )

    row.ai_verdict = result["verdict"]
    row.ai_reasoning = result["reasoning"]
    row.ai_verified_at = datetime.utcnow()
    db.commit()

    return {
        "id": row.id,
        "ai_verdict": row.ai_verdict,
        "ai_reasoning": row.ai_reasoning,
        "ai_verified_at": row.ai_verified_at.isoformat(),
        "fetch_errors": result.get("fetch_errors") or {},
    }
