"""
Vertical Pipeline Orchestrator

Usage:
  python run_verticals.py <accounts.csv> [options]

Options:
  --verticals  Comma-separated list of verticals to run
               (religious,education,corporate,auto,healthcare,mdu)
               Default: religious,education
  --limit N    Max accounts per vertical (default: 5 for live testing)
  --all        Run without account-per-vertical limit
  --output     Output CSV path (default: output/verticals_<timestamp>.csv)
  --verbose    Show per-account progress

Input CSV must have these columns (or their CSV originals):
  account_id, account_name, city, state, industry, website (optional)

The standardized CSV from the batch processor already has these columns.
"""

import csv
import json
import sys
import argparse
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mplc_pop_engine.MPLC.pipeline.industry_router import route_accounts, print_routing_summary
from step3_vertical_router.industry_reclassifier import VerticalReclassifier


# ---------------------------------------------------------------------------
# Vertical pipeline registry
# ---------------------------------------------------------------------------

def _load_religious():
    from verticals.religious_institutions.pipeline import run_batch
    return run_batch

def _load_education():
    from verticals.education.pipeline import run_batch
    return run_batch

PIPELINE_REGISTRY = {
    "religious": _load_religious,
    "education": _load_education,
    # corporate / auto / healthcare / mdu: existing batch_processor handles these
    # Add loaders here as more verticals are built
}


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def load_csv(path: str) -> list[dict]:
    """Load CSV, returning list of dicts with normalized keys."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            # Normalize column names to lowercase with underscores
            normalized = {k.strip().lower().replace(" ", "_"): v for k, v in row.items()}
            # Support both 'account name' and 'account_name' variants
            if "account name" in normalized and "account_name" not in normalized:
                normalized["account_name"] = normalized.pop("account name")

            # Map Salesforce column names to expected pipeline columns
            if "account_state" in normalized and "state" not in normalized:
                normalized["state"] = normalized["account_state"]
            if "account_street" in normalized and "city" not in normalized:
                # City not in CSV - leave empty, text miner will use state only
                normalized["city"] = ""

            # Fix website URLs - add http:// if missing
            if "website" in normalized and normalized["website"]:
                website = normalized["website"].strip()
                if website and not website.startswith(("http://", "https://")):
                    normalized["website"] = f"http://{website}"

            rows.append(normalized)
    return rows


def save_results(records: list[dict], output_path: str) -> None:
    if not records:
        print("No results to save.")
        return

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Flatten additional_metadata for CSV
    flat_records = []
    for r in records:
        flat = {k: v for k, v in r.items() if k != "additional_metadata"}
        meta = r.get("additional_metadata", {})
        flat["keywords_matched"]   = "; ".join(meta.get("keywords_matched", []))
        flat["rejection_keywords"] = "; ".join(meta.get("rejection_keywords", []))
        flat["pages_scraped"]      = meta.get("pages_scraped", 0)
        flat["sub_segment"]        = meta.get("sub_segment", "")
        flat["error"]              = meta.get("error", "")
        flat["processed_at"]       = meta.get("processed_at", "")
        flat_records.append(flat)

    fieldnames = [
        "account_id", "account_name", "vertical", "channel", "tier",
        "evidence_description", "source_url", "space_type", "tv_powered_on",
        "cost", "yolo_confidence", "vlm_confidence",
        "keywords_matched", "rejection_keywords", "pages_scraped",
        "sub_segment", "error", "processed_at",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat_records)

    print(f"\nResults saved → {output_path}")


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_results_summary(records: list[dict]) -> None:
    from collections import Counter
    by_vertical: dict[str, list] = {}
    for r in records:
        by_vertical.setdefault(r.get("vertical", "?"), []).append(r)

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    total_cost = 0.0

    for vertical, recs in sorted(by_vertical.items()):
        tier_counts = Counter(r["tier"] for r in recs)
        cost = sum(r.get("cost", 0) for r in recs)
        total_cost += cost
        n = len(recs)
        prospects = tier_counts.get("PROSPECT", 0)
        suspects  = tier_counts.get("SUSPECT", 0)
        rejected  = tier_counts.get("REJECTED", 0)
        coverage  = (prospects + suspects) / n * 100 if n else 0
        print(f"\n{vertical} (n={n})")
        print(f"  PROSPECT: {prospects}  SUSPECT: {suspects}  REJECTED: {rejected}")
        print(f"  Coverage (P+S): {coverage:.0f}%   Cost: ${cost:.4f}   $/account: ${cost/n:.4f}" if n else "")

        # Show PROSPECT details
        for r in recs:
            if r["tier"] in ("PROSPECT", "SUSPECT"):
                print(f"  {'✓' if r['tier']=='PROSPECT' else '?'} {r['account_name']}")
                print(f"      {r['evidence_description'][:90]}")
                if r.get("source_url"):
                    print(f"      {r['source_url'][:80]}")

    print(f"\nTotal cost: ${total_cost:.4f}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run vertical detection pipelines")
    parser.add_argument("csv_path", help="Path to standardized accounts CSV")
    parser.add_argument("--verticals", default="religious,education",
                        help="Comma-separated verticals to run (default: religious,education)")
    parser.add_argument("--limit", type=int, default=5,
                        help="Max accounts per vertical for live testing (default: 5)")
    parser.add_argument("--all", dest="run_all", action="store_true",
                        help="Remove per-vertical account limit")
    parser.add_argument("--output", default="",
                        help="Output CSV path (auto-generated if not set)")
    parser.add_argument("--verbose", action="store_true", default=True,
                        help="Show per-account progress")
    parser.add_argument("--use-llm", dest="use_llm", action="store_true",
                        help="Enable Tier-2 LLM re-classification for ambiguous account names")
    parser.add_argument("--force-reclassify", dest="force_reclassify", action="store_true",
                        help="Re-classify all accounts even if already in cache")
    parser.add_argument("--reclassifier-db", default="vertical_corrections.db",
                        help="Path to the vertical corrections SQLite cache")
    args = parser.parse_args()

    target_verticals = [v.strip() for v in args.verticals.split(",")]
    limit = None if args.run_all else args.limit

    # --- Load accounts ---
    print(f"\nLoading: {args.csv_path}")
    accounts = load_csv(args.csv_path)
    print(f"Loaded {len(accounts):,} accounts")

    # --- Phase 0: Industry re-classification ---
    rc = VerticalReclassifier(db_path=args.reclassifier_db)
    rc_stats = rc.reclassify_batch(
        accounts,
        use_llm=args.use_llm,
        force=args.force_reclassify,
    )
    rc.close()

    if rc_stats["corrected"]:
        print(f"\nIndustry re-classifier: {rc_stats['corrected']} correction(s) "
              f"| {rc_stats['from_cache']} from cache | {rc_stats['total']} total")
        for a in accounts:
            if a.get("_industry_corrected"):
                print(f"  ✎ {a['account_name']}: "
                      f"{a['_original_industry']!r} → {a['industry']!r}  "
                      f"[{a['_industry_reason']}]")
    else:
        print(f"\nIndustry re-classifier: all {rc_stats['total']} labels confirmed "
              f"({rc_stats['from_cache']} from cache)")

    # --- Route ---
    buckets = route_accounts(accounts)
    print_routing_summary(buckets)

    # --- Dispatch to pipelines ---
    all_results = []

    for vertical in target_verticals:
        bucket = buckets.get(vertical, [])
        if not bucket:
            print(f"[{vertical}] No accounts routed to this vertical — skipping")
            continue

        loader = PIPELINE_REGISTRY.get(vertical)
        if not loader:
            print(f"[{vertical}] Pipeline not yet built — skipping")
            continue

        run_batch = loader()
        sample = bucket[:limit] if limit else bucket
        print(f"\n[{vertical}] Running {len(sample)} of {len(bucket)} accounts...")

        try:
            results = run_batch(sample, verbose=args.verbose)
            all_results.extend(results)
        except Exception as e:
            print(f"  ERROR running {vertical} pipeline: {e}")
            import traceback; traceback.print_exc()

    # --- Output ---
    if not all_results:
        print("\nNo results produced.")
        return

    print_results_summary(all_results)

    output_path = args.output or (
        f"output/verticals_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.csv"
    )
    save_results(all_results, output_path)


if __name__ == "__main__":
    main()
