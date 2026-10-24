"""
Education Vertical Pipeline

Sub-segments (detected from account name):
  A. University / College / Institute / Seminary / Academy
     → Website text mining + (future) Google Places for on-campus venues
     Expected coverage: 25-40%

  B. K-12 (Elementary / Middle / High School / ISD / USD / School District)
     → Text mining only; REJECT if nothing found (no image channels)
     Expected coverage: <10%

Evidence standard:
  - Student-facing communal area: student union, dining hall, rec center lobby,
    dormitory common room, library lounge
  - NOT: classroom projectors, faculty monitors, scoreboards, digital signage

Note: CWRU appeared as PROSPECT in Oct 2026 batch run via corporate pipeline —
validate that result manually before using as ground truth.
"""

import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from channels.text_miner import mine_website, TextMineResult

VERTICAL_NAME = "Education"

# Sub-segment classification patterns
_UNIVERSITY_PATTERNS = re.compile(
    r"\b(university|college|institute|seminary|school of|academy|"
    r"polytechnic|conservatory|graduate school)\b",
    re.IGNORECASE,
)
_K12_PATTERNS = re.compile(
    r"\b(elementary|middle school|high school|isd|usd|unified school|"
    r"school district|primary school|k-12|preparatory|prep school)\b",
    re.IGNORECASE,
)


def classify_sub_segment(account_name: str) -> str:
    """Return 'university' or 'k12' based on account name keywords."""
    if _UNIVERSITY_PATTERNS.search(account_name):
        return "university"
    if _K12_PATTERNS.search(account_name):
        return "k12"
    # Default: treat ambiguous names (e.g. "Academy for Arts") as university for higher coverage
    return "university"


def run_account(account: dict, verbose: bool = False) -> dict:
    """
    Run the education detection pipeline for one account.

    Args:
        account: Dict with keys: account_id, account_name, city, state,
                 website (optional), industry
        verbose: Print progress to stdout

    Returns:
        Evidence record dict conforming to the project evidence persistence schema.
    """
    name       = account.get("account_name", "")
    city       = account.get("city", "")
    state      = account.get("state", "")
    website    = account.get("website", "") or ""
    sub_segment = classify_sub_segment(name)

    if verbose:
        print(f"  [education/{sub_segment}] {name} | {city}, {state}")

    # --- Channel 1: Website text mining (both sub-segments) ---
    result: TextMineResult = mine_website(
        account_name=name,
        website_url=website if website.startswith("http") else None,
        city=city,
        state=state,
        vertical="education",
        serper_fallback=True,
    )

    # K-12: stop here — don't escalate to image channels
    # University: text mining result is enough for now; Google Places added later

    if verbose:
        marker = {"PROSPECT": "✓", "SUSPECT": "?", "REJECTED": "✗"}[result.tier]
        print(f"    {marker} {result.tier} | {result.evidence_description[:80]}")

    return _build_record(account, result, sub_segment)


def _build_record(account: dict, result: TextMineResult, sub_segment: str) -> dict:
    return {
        "account_id":              account.get("account_id", ""),
        "account_name":            account.get("account_name", ""),
        "vertical":                VERTICAL_NAME,
        "channel":                 result.channel,
        "tier":                    result.tier,
        "evidence_photo_location": "",
        "evidence_description":    result.evidence_description,
        "yolo_confidence":         0.0,
        "vlm_confidence":          "",
        "source_url":              result.source_url,
        "space_type":              _infer_space_type(result, sub_segment),
        "tv_powered_on":           result.tier == "PROSPECT",
        "cost":                    result.cost_usd,
        "additional_metadata": {
            "sub_segment":        sub_segment,
            "keywords_matched":   result.keywords_matched,
            "rejection_keywords": result.rejection_keywords,
            "pages_scraped":      result.pages_scraped,
            "error":              result.error,
            "processed_at":       datetime.utcnow().isoformat(),
        },
    }


def _infer_space_type(result: TextMineResult, sub_segment: str) -> str:
    keywords_text = " ".join(result.keywords_matched).lower()
    if "dining" in keywords_text or "cafeteria" in keywords_text:
        return "dining_hall"
    if "student union" in keywords_text or "campus center" in keywords_text:
        return "student_union"
    if "rec" in keywords_text or "recreation" in keywords_text:
        return "recreation_center"
    if "library" in keywords_text or "lounge" in keywords_text:
        return "library_lounge"
    if "dorm" in keywords_text or "residence" in keywords_text:
        return "dormitory_common"
    if result.tier != "REJECTED":
        return "campus_communal_area"
    return ""


def run_batch(accounts: list[dict], verbose: bool = True) -> list[dict]:
    """Run pipeline for a list of accounts. Returns list of evidence records."""
    results = []
    total = len(accounts)
    for i, account in enumerate(accounts, 1):
        if verbose:
            print(f"[{i}/{total}] {account.get('account_name', '?')}")
        record = run_account(account, verbose=verbose)
        results.append(record)
    return results
