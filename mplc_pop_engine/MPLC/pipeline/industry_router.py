"""
Industry Pre-Router

Routes accounts to the correct vertical pipeline based on the Industry column
in the Salesforce CSV. Must run BEFORE any vertical pipeline to avoid misrouting
non-corporate accounts through the corporate (Yelp-first) channel.

Discovery: 69% of corporate_accounts CSV was non-corporate (Oct 2026 batch run).
Root cause of 2.4% vs. expected 16.7% PROSPECT rate.
"""

from typing import Literal

# ---------------------------------------------------------------------------
# Routing destinations
# ---------------------------------------------------------------------------
VerticalRoute = Literal[
    "corporate",
    "restaurants_bars",
    "healthcare",
    "mdu",
    "religious",      # NEW — designed, not yet built
    "education",      # NEW — designed, not yet built
    "auto",
    "skip",           # Known non-viable; log as REJECTED, don't process
    "manual_review",  # Unknown industry; flag for human triage
]

# ---------------------------------------------------------------------------
# Industry → route mapping
# Salesforce industry values (exact strings from the CSV Industry column)
# ---------------------------------------------------------------------------
INDUSTRY_ROUTE_MAP: dict[str, VerticalRoute] = {
    # --- Existing pipelines ---
    "Corporations":                                "corporate",
    "Bars, Restaurants":                           "restaurants_bars",
    "Restaurants, Clubs, Pubs":                    "restaurants_bars",
    "Health Care Services":                        "healthcare",
    "Hospitals":                                   "healthcare",
    "Communal Living Facilities":                  "mdu",
    "Multi-Dwelling Units":                        "mdu",
    "Auto Dealers":                                "auto",
    "Auto Dealerships":                            "auto",

    # --- New verticals (text-mining pipelines built) ---
    "Religious Institutions":                      "religious",
    "Churches":                                    "religious",
    "Education":                                   "education",
    "Schools":                                     "education",

    # --- Route to existing pipelines (additional CSV values) ---
    "Doctors":                                     "healthcare",
    "Medical":                                     "healthcare",
    "Seniors":                                     "mdu",       # Senior living = residential
    "Commercial Establishments & Waiting Areas":   "corporate", # Waiting rooms → Yelp-findable
    "Activity Centers":                            "corporate", # Rec/community centers

    # --- Skip: known non-viable or evidence-unavailable ---
    "Dentists":                                    "skip",
    "Dental":                                      "skip",
    "Hair Salons":                                 "skip",
    "Government and Similar Buildings & Services": "skip",
    "Government":                                  "skip",
    "Correctional Facilities":                     "skip",
    "Military":                                    "skip",
    "Transportation":                              "skip",      # Transit/airports — restricted
    "Electronics":                                 "skip",      # Retail electronics — staff areas
    "Child Care/Nurseries":                        "skip",      # No public evidence path

    # --- Manual review: insufficient data to route confidently ---
    "Campgrounds":                                 "manual_review",
    "Museums":                                     "manual_review",
    "Misc":                                        "manual_review",
    "Other":                                       "manual_review",
    "CHU CV":                                      "manual_review",
}

# Industries routed to skip with a specific reason logged
SKIP_REASONS: dict[str, str] = {
    "Dentists":                                    "industry_skip_dental_non_viable",
    "Dental":                                      "industry_skip_dental_non_viable",
    "Hair Salons":                                 "industry_skip_hair_salons",
    "Government and Similar Buildings & Services": "industry_skip_government",
    "Government":                                  "industry_skip_government",
    "Correctional Facilities":                     "industry_skip_government",
    "Military":                                    "industry_skip_government",
    "Transportation":                              "industry_skip_transportation",
    "Electronics":                                 "industry_skip_electronics_retail",
    "Child Care/Nurseries":                        "industry_skip_childcare_no_evidence_path",
}

# Verticals that are designed but pipeline not yet implemented
NOT_YET_BUILT: set[str] = set()  # religious + education pipelines now live in verticals/


def route_account(account: dict) -> tuple[VerticalRoute, str | None]:
    """
    Determine the vertical pipeline route for an account.

    Args:
        account: Dict with at minimum an 'industry' key (from CSV translator).

    Returns:
        (route, skip_reason)
        - route: destination vertical or "skip"/"manual_review"
        - skip_reason: populated when route == "skip", else None
    """
    industry = (account.get("industry") or "").strip()

    route = INDUSTRY_ROUTE_MAP.get(industry)

    if route is None:
        return "manual_review", None

    if route == "skip":
        reason = SKIP_REASONS.get(industry, "industry_skip_unknown")
        return "skip", reason

    return route, None


def route_accounts(accounts: list[dict]) -> dict[VerticalRoute, list[dict]]:
    """
    Partition a list of accounts into per-vertical buckets.

    Returns a dict keyed by route, each value a list of accounts.
    Adds '_route' and '_skip_reason' keys to each account dict in-place.
    """
    buckets: dict[VerticalRoute, list[dict]] = {}

    for account in accounts:
        route, skip_reason = route_account(account)
        account["_route"] = route
        if skip_reason:
            account["_skip_reason"] = skip_reason
        buckets.setdefault(route, []).append(account)

    return buckets


def print_routing_summary(buckets: dict[VerticalRoute, list[dict]]) -> None:
    """Print a human-readable routing breakdown."""
    total = sum(len(v) for v in buckets.values())
    print(f"\nIndustry Pre-Router — {total:,} accounts")
    print("-" * 50)

    order = [
        "corporate", "restaurants_bars", "healthcare", "mdu",
        "religious", "education", "auto",
        "skip", "manual_review",
    ]
    for route in order:
        if route not in buckets:
            continue
        count = len(buckets[route])
        pct = count / total * 100
        flags = []
        if route in NOT_YET_BUILT:
            flags.append("pipeline not yet built")
        if route == "skip":
            flags.append("logged as REJECTED, not processed")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        print(f"  {route:<20} {count:>5,}  ({pct:5.1f}%){flag_str}")
    print()


# ---------------------------------------------------------------------------
# CLI usage for quick validation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import csv
    import sys

    if len(sys.argv) < 2:
        print("Usage: python industry_router.py <accounts.csv>")
        sys.exit(1)

    with open(sys.argv[1], newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Normalise: look for 'Industry' column (case-insensitive)
    normalized = []
    for row in rows:
        industry_val = ""
        for k, v in row.items():
            if k.strip().lower() == "industry":
                industry_val = v
                break
        normalized.append({"industry": industry_val, "_raw": row})

    buckets = route_accounts(normalized)
    print_routing_summary(buckets)

    # Show manual_review industries for triage
    if "manual_review" in buckets:
        unknown = {}
        for acct in buckets["manual_review"]:
            ind = acct.get("industry", "(blank)")
            unknown[ind] = unknown.get(ind, 0) + 1
        print("manual_review breakdown (unknown industries):")
        for ind, cnt in sorted(unknown.items(), key=lambda x: -x[1])[:20]:
            print(f"  {ind!r:<45} {cnt:>4}")
