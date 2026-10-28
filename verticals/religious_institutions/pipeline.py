"""
Religious Institutions Vertical Pipeline

Channel order (cheapest first):
  1. Website text mining  — $0.001/account (Serper) + free scraping
  2. [Future] Google Places photos — same Apify approach as corporate

Root cause note: this vertical was silently misrouted through the Yelp-first
corporate pipeline (Oct 2026 batch), producing near-zero PROSPECTs. Text
mining is the correct primary channel for religious institutions.

Evidence standard:
  - TV/display in communal space (sanctuary, fellowship hall, overflow room, lobby)
  - NOT sermon projection screens / PowerPoint / whiteboard
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from channels.text_miner import mine_website, TextMineResult

VERTICAL_NAME = "Religious Institutions"


def run_account(account: dict, verbose: bool = False) -> dict:
    """
    Run the religious institutions detection pipeline for one account.

    Args:
        account: Dict with keys: account_id, account_name, city, state,
                 website (optional), industry
        verbose: Print progress to stdout

    Returns:
        Evidence record dict conforming to the project evidence persistence schema.
    """
    name    = account.get("account_name", "")
    city    = account.get("city", "")
    state   = account.get("state", "")
    website = account.get("website", "") or ""

    if verbose:
        print(f"  [religious] {name} | {city}, {state}")

    # --- Channel 1: Website text mining ---
    result: TextMineResult = mine_website(
        account_name=name,
        website_url=website if website.startswith("http") else None,
        city=city,
        state=state,
        vertical="religious",
        serper_fallback=True,
    )

    if verbose:
        marker = {"PROSPECT": "✓", "SUSPECT": "?", "REJECTED": "✗"}[result.tier]
        print(f"    {marker} {result.tier} | {result.evidence_description[:80]}")

    return _build_record(account, result)


def _build_record(account: dict, result: TextMineResult) -> dict:
    """Map TextMineResult → project evidence schema."""
    return {
        "account_id":              account.get("account_id", ""),
        "account_name":            account.get("account_name", ""),
        "vertical":                VERTICAL_NAME,
        "channel":                 result.channel,
        "tier":                    result.tier,
        "evidence_photo_location": "",  # text mining: no image
        "evidence_description":    result.evidence_description,
        "yolo_confidence":         0.0,
        "vlm_confidence":          "",
        "source_url":              result.source_url,
        "space_type":              _infer_space_type(result),
        "tv_powered_on":           result.tier == "PROSPECT",
        "cost":                    result.cost_usd,
        "additional_metadata": {
            "keywords_matched":   result.keywords_matched,
            "rejection_keywords": result.rejection_keywords,
            "pages_scraped":      result.pages_scraped,
            "error":              result.error,
            "processed_at":       datetime.utcnow().isoformat(),
        },
    }


def _infer_space_type(result: TextMineResult) -> str:
    keywords_text = " ".join(result.keywords_matched).lower()
    if "overflow" in keywords_text or "cry room" in keywords_text:
        return "overflow_room"
    if "fellowship" in keywords_text:
        return "fellowship_hall"
    if "lobby" in keywords_text or "narthex" in keywords_text:
        return "lobby"
    if "sanctuary" in keywords_text:
        return "sanctuary"
    if result.tier != "REJECTED":
        return "communal_area"
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
