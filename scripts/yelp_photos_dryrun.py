#!/usr/bin/env python3
"""
Yelp Photo Fetcher — dry-run benchmarker

Runs YelpPhotoFetcher against a curated set of real Yelp URLs drawn from
existing pipeline data and prints a summary:

  * Total businesses tested
  * # fetched via HTTP tier
  * # fetched via browser fallback (Camoufox)
  * # blocked / failed
  * Average photos per successful business
  * Wall-clock time
  * Apify cost comparison

Usage:
    python scripts/yelp_photos_dryrun.py                   # default URL list
    python scripts/yelp_photos_dryrun.py --urls-csv path   # CSV with a 'url' column
    python scripts/yelp_photos_dryrun.py --max-photos 30   # cap photos per business
    python scripts/yelp_photos_dryrun.py --no-cache        # ignore existing cache
    python scripts/yelp_photos_dryrun.py --dry-run         # print URLs, don't fetch

Apify cost model (from analyze_apify_costs.py):
    $0.002 per photo result  +  $0.49/hr compute  (~$0.0011 per 8s actor startup)
    Per business average at 25 photos: ~0.051 + 0.001 = ~$0.052
"""

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from channels.yelp_photos import YelpPhotoFetcher, to_apify_format

# ---------------------------------------------------------------------------
# Curated URL set (drawn from existing pipeline data files)
# ---------------------------------------------------------------------------

# Auto dealerships — from output/runs/auto_dealership_yelp_results.json
_AUTO_DEALER_URLS = [
    "https://www.yelp.com/biz/auto-nation-usa-houston-2",
    "https://www.yelp.com/biz/autonation-toyota-cerritos",
    "https://www.yelp.com/biz/lithia-honda-of-odessa",
    "https://www.yelp.com/biz/group-1-automotive-houston",
    "https://www.yelp.com/biz/autonation-chevrolet-west-austin",
]

# Dental — from pilot_dental_yelp_photos.py
_DENTAL_URLS = [
    "https://www.yelp.com/biz/pacific-dental-group-san-francisco",
    "https://www.yelp.com/biz/dental-care-of-walnut-creek-walnut-creek",
    "https://www.yelp.com/biz/smile-generation-phoenix",
    "https://www.yelp.com/biz/kool-smiles-dallas",
    "https://www.yelp.com/biz/kool-smiles-houston",
]

# Corporate — known ground-truth accounts (public locations with Yelp presence)
_CORPORATE_URLS = [
    "https://www.yelp.com/biz/pnc-bank-pittsburgh",
    "https://www.yelp.com/biz/costco-wholesale-san-francisco-5",
    "https://www.yelp.com/biz/cigna-healthspring-phoenix",
]

# Sports bars / restaurants — positive controls (pre-existing vertical)
_RESTAURANT_URLS = [
    "https://www.yelp.com/biz/buffaloe-wild-wings-dallas",
    "https://www.yelp.com/biz/dave-and-busters-dallas",
    "https://www.yelp.com/biz/main-event-entertainment-plano",
]

# Healthcare (exploratory)
_HEALTHCARE_URLS = [
    "https://www.yelp.com/biz/hca-houston-healthcare-northwest",
    "https://www.yelp.com/biz/memorial-hermann-health-system-houston",
]

DEFAULT_URLS = (
    _AUTO_DEALER_URLS
    + _DENTAL_URLS
    + _CORPORATE_URLS
    + _RESTAURANT_URLS
    + _HEALTHCARE_URLS
)

# ---------------------------------------------------------------------------
# Apify cost model
# ---------------------------------------------------------------------------

APIFY_COST_PER_PHOTO    = 0.002   # $2 per 1,000 results
APIFY_COMPUTE_PER_HR    = 0.49
APIFY_ACTOR_STARTUP_S   = 8       # avg seconds per actor run from logs

def apify_cost_for_photos(n_photos: int, n_actors: int) -> float:
    compute_hours = (n_actors * APIFY_ACTOR_STARTUP_S) / 3600
    return (n_photos * APIFY_COST_PER_PHOTO) + (compute_hours * APIFY_COMPUTE_PER_HR)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Yelp photo fetcher dry-run benchmarker")
    p.add_argument("--urls-csv", help="CSV file with a 'url' column")
    p.add_argument("--max-photos", type=int, default=60,
                   help="Max photos to fetch per business (default 60)")
    p.add_argument("--no-cache", action="store_true",
                   help="Ignore existing cache (force live fetches)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print URL list and exit without fetching")
    p.add_argument("--output-json", help="Write full results to this JSON file")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def load_urls_from_csv(path: str) -> list[str]:
    urls = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key in ("url", "URL", "yelp_url", "business_url"):
                if key in row and row[key].strip():
                    urls.append(row[key].strip())
                    break
    return urls


def print_separator(char="=", width=70):
    print(char * width)


def run(args):
    # ------------------------------------------------------------------
    # Build URL list
    # ------------------------------------------------------------------
    if args.urls_csv:
        urls = load_urls_from_csv(args.urls_csv)
        print(f"Loaded {len(urls)} URLs from {args.urls_csv}")
    else:
        urls = list(DEFAULT_URLS)
        print(f"Using built-in URL set ({len(urls)} businesses)")

    if args.dry_run:
        print_separator()
        print("DRY RUN — URLs that would be fetched:")
        for u in urls:
            print(f"  {u}")
        print_separator()
        return

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    print_separator()
    print(f"YELP PHOTO FETCHER — DRY RUN")
    print(f"Businesses: {len(urls)}")
    print(f"Max photos/biz: {args.max_photos}")
    print(f"Cache: {'disabled' if args.no_cache else 'enabled (30-day TTL)'}")
    print_separator()

    fetcher = YelpPhotoFetcher(
        max_photos=args.max_photos,
        use_cache=not args.no_cache,
    )

    results = []
    wall_start = time.time()

    for i, url in enumerate(urls, 1):
        biz_start = time.time()
        result = fetcher.fetch(url)
        elapsed = time.time() - biz_start

        status_icon = {
            "ok":      "✓",
            "blocked": "✗",
            "error":   "!",
        }.get(result["status"], "?")

        tier_label = result.get("fetch_tier", "?")[:7]
        print(
            f"  [{i:2d}/{len(urls)}] {status_icon}  "
            f"[{tier_label:<7}]  "
            f"{result['photo_count']:4d} photos  "
            f"({elapsed:.1f}s)  "
            f"{result['business_id']}"
        )
        if result.get("error_detail"):
            print(f"          → {result['error_detail'][:80]}")

        results.append(result)

    wall_elapsed = time.time() - wall_start

    # ------------------------------------------------------------------
    # Summary stats
    # ------------------------------------------------------------------
    stats = fetcher.tier_stats()
    fetcher.close()

    ok_results       = [r for r in results if r["status"] == "ok"]
    blocked_results  = [r for r in results if r["status"] == "blocked"]
    error_results    = [r for r in results if r["status"] == "error"]

    total_photos     = sum(r["photo_count"] for r in ok_results)
    avg_photos       = total_photos / len(ok_results) if ok_results else 0

    print_separator()
    print("SUMMARY")
    print_separator("-")
    print(f"  Businesses tested:     {len(results)}")
    print(f"  Successful (ok):       {len(ok_results)}")
    print(f"    ↳ HTTP tier:         {stats['http_ok']}")
    print(f"    ↳ Browser tier:      {stats['browser_ok']}")
    print(f"    ↳ Cache hits:        {stats['cache_hit']}")
    print(f"  Blocked:               {len(blocked_results)}")
    print(f"  Errors:                {len(error_results)}")
    print(f"  Total photos fetched:  {total_photos:,}")
    print(f"  Avg photos / biz:      {avg_photos:.1f}")
    print(f"  Wall-clock time:       {wall_elapsed:.1f}s  ({wall_elapsed/60:.1f} min)")
    if len(results) > 0:
        print(f"  Avg time / biz:        {wall_elapsed/len(results):.1f}s")

    # ------------------------------------------------------------------
    # Apify cost comparison
    # ------------------------------------------------------------------
    print()
    print_separator("-")
    print("COST COMPARISON — Self-hosted vs Apify")
    print_separator("-")

    # Self-hosted: CPU time on DigitalOcean droplet
    # $0.0476/hr for a DO Basic 2vCPU/4GB droplet (cheapest that handles Camoufox)
    # Use $0.05/hr as a round number
    DO_DROPLET_COST_PER_HR = 0.05

    self_hosted_cost = (wall_elapsed / 3600) * DO_DROPLET_COST_PER_HR
    apify_cost       = apify_cost_for_photos(total_photos, len(results))
    apify_cost_projected = apify_cost_for_photos(
        int(avg_photos * len(results)),   # same photo count
        len(results),
    )

    print(f"  Self-hosted (this run):")
    print(f"    Wall time:           {wall_elapsed:.1f}s ({wall_elapsed/3600:.4f} hr)")
    print(f"    Droplet rate:        ${DO_DROPLET_COST_PER_HR:.2f}/hr (DO Basic 2vCPU)")
    print(f"    Cost:                ${self_hosted_cost:.4f}")
    print()
    print(f"  Apify equivalent:")
    print(f"    Photos:              {total_photos:,} × ${APIFY_COST_PER_PHOTO:.3f} = ${total_photos * APIFY_COST_PER_PHOTO:.3f}")
    print(f"    Compute:             {len(results)} actors × {APIFY_ACTOR_STARTUP_S}s × ${APIFY_COMPUTE_PER_HR:.2f}/hr = ${apify_cost - (total_photos * APIFY_COST_PER_PHOTO):.4f}")
    print(f"    Total Apify cost:    ${apify_cost:.4f}")
    print()
    if apify_cost > 0:
        savings_pct = (1 - self_hosted_cost / apify_cost) * 100
        print(f"  Self-hosted savings:   ${apify_cost - self_hosted_cost:.4f}  ({savings_pct:.0f}% cheaper)")
    print()
    print(f"  Projection to 1,000 businesses (avg {avg_photos:.0f} photos each):")
    scale = 1000 / max(len(results), 1)
    projected_photos = int(avg_photos * 1000)
    proj_self  = (wall_elapsed * scale / 3600) * DO_DROPLET_COST_PER_HR
    proj_apify = apify_cost_for_photos(projected_photos, 1000)
    print(f"    Self-hosted:         ${proj_self:.2f}")
    print(f"    Apify:               ${proj_apify:.2f}")

    # ------------------------------------------------------------------
    # Yelp ToS reminder
    # ------------------------------------------------------------------
    print()
    print_separator("-")
    print("NOTE — Yelp ToS §10(h) prohibits scraping.")
    print("  Risk: civil (breach of contract). At 25-30 biz/day volume,")
    print("  enforcement risk is low but non-zero. This self-hosted approach")
    print("  exposes your own IP; Apify absorbs initial blocking but carries")
    print("  the same legal risk. Confirm with counsel before scaling.")
    print_separator("=")

    # ------------------------------------------------------------------
    # Write JSON output
    # ------------------------------------------------------------------
    if args.output_json:
        out = {
            "run_summary": {
                "total_businesses":    len(results),
                "ok_count":            len(ok_results),
                "blocked_count":       len(blocked_results),
                "error_count":         len(error_results),
                "total_photos":        total_photos,
                "avg_photos":          round(avg_photos, 1),
                "wall_elapsed_s":      round(wall_elapsed, 1),
                "tier_stats":          stats,
                "self_hosted_cost":    round(self_hosted_cost, 5),
                "apify_equivalent_cost": round(apify_cost, 4),
            },
            "results": results,
        }
        Path(args.output_json).write_text(json.dumps(out, indent=2))
        print(f"\nFull results written to: {args.output_json}")

    # Apify adapter smoke-check
    if ok_results:
        sample = ok_results[0]
        apify_items = to_apify_format(sample)
        print(f"\nApify adapter check: {sample['business_id']}")
        print(f"  to_apify_format() → {len(apify_items)} items")
        if apify_items:
            print(f"  First item: {json.dumps(apify_items[0], indent=4)}")


if __name__ == "__main__":
    run(parse_args())
