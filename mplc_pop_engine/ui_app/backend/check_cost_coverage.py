"""
Cost Tracker — Step 0: verify real data coverage before building anything.

Per claude/Cost_Tracker_Design.md §Step 0: before building any cost
rollup/dashboard on top of account_enrichment_results.enrichment_result
->> 'cost', confirm what fraction of completed rows per vertical (and per
channel) actually HAVE that key populated. supabase_client.get_job_cost's
own docstring already flags this as not guaranteed on every enricher's
result shape -- this script turns that into a real number instead of an
assumption, so the Cost Tracker can show an honest data-coverage line per
vertical instead of silently averaging over fewer rows than it claims to.

Usage:
    cd ui_app/backend
    python3 check_cost_coverage.py

Requires DATABASE_URL or SUPABASE_PASSWORD in the environment, same as
every other module that talks to Supabase here (supabase_client.py,
unified_worker.py's SupabaseWriter). This sandbox has neither configured
and no verified network path to Supabase's Postgres endpoint -- this
script has NOT been run against real data yet. Run it wherever those
creds live (same machine/.env as production/workers' SupabaseWriter) and
paste the output back so the Cost Tracker design's coverage assumption
can be confirmed or corrected before Step 1-2 get built on top of it.
"""

import sys

try:
    import supabase_client
except ImportError:
    # allow running as `python3 ui_app/backend/check_cost_coverage.py` too
    sys.path.insert(0, __file__.rsplit('/', 1)[0])
    import supabase_client


COVERAGE_WARN_THRESHOLD = 0.95  # below this, flag it loudly rather than silently reporting


def check_coverage():
    query = """
        SELECT
            vertical,
            COUNT(*)                                                   AS completed_rows,
            COUNT(*) FILTER (WHERE enrichment_result ? 'cost')         AS has_cost,
            COUNT(*) FILTER (WHERE enrichment_result ? 'channel')      AS has_channel,
            COUNT(*) FILTER (WHERE is_prospect)                        AS prospect_count
        FROM account_enrichment_results
        WHERE status = 'completed'
        GROUP BY vertical
        ORDER BY vertical
    """
    channel_query = """
        SELECT
            vertical,
            enrichment_result->>'channel' AS channel,
            COUNT(*) AS rows,
            COUNT(*) FILTER (WHERE enrichment_result ? 'cost') AS has_cost
        FROM account_enrichment_results
        WHERE status = 'completed' AND enrichment_result ? 'channel'
        GROUP BY vertical, channel
        ORDER BY vertical, channel
    """

    try:
        with supabase_client._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
                cur.execute(channel_query)
                channel_rows = cur.fetchall()
    except supabase_client.SupabaseUnavailable as e:
        print(f"CANNOT CHECK: {e}")
        print("\nThis sandbox has no DATABASE_URL/SUPABASE_PASSWORD configured and no "
              "verified network path to Supabase. Run this script on a machine with "
              "those creds set (same .env production/workers' SupabaseWriter uses), "
              "then share the output.")
        return 2

    print(f"{'vertical':<20} {'completed':>10} {'has_cost':>9} {'cost_%':>8} "
          f"{'has_channel':>12} {'channel_%':>10} {'prospects':>10}")
    print("-" * 90)

    any_low_coverage = False
    for vertical, completed, has_cost, has_channel, prospects in rows:
        cost_pct = (has_cost / completed) if completed else 0
        channel_pct = (has_channel / completed) if completed else 0
        flag = ""
        if cost_pct < COVERAGE_WARN_THRESHOLD:
            flag = "  <-- LOW COST COVERAGE"
            any_low_coverage = True
        print(f"{vertical:<20} {completed:>10,} {has_cost:>9,} {cost_pct:>7.1%} "
              f"{has_channel:>12,} {channel_pct:>9.1%} {prospects:>10,}{flag}")

    print("\nBy channel (verticals/channels with ANY rows missing cost):")
    print(f"{'vertical':<20} {'channel':<25} {'rows':>8} {'has_cost':>9} {'cost_%':>8}")
    print("-" * 75)
    for vertical, channel, n_rows, n_has_cost in channel_rows:
        pct = (n_has_cost / n_rows) if n_rows else 0
        if pct < 1.0:
            print(f"{vertical:<20} {(channel or '(null)'):<25} {n_rows:>8,} {n_has_cost:>9,} {pct:>7.1%}")

    if any_low_coverage:
        print(f"\nAt least one vertical is below {COVERAGE_WARN_THRESHOLD:.0%} cost-field "
              f"coverage. The Cost Tracker design (§2.4) requires surfacing this per-vertical "
              f"rather than silently averaging over fewer rows than it claims to.")
    else:
        print(f"\nAll verticals at or above {COVERAGE_WARN_THRESHOLD:.0%} cost-field coverage.")

    return 0


if __name__ == '__main__':
    sys.exit(check_coverage())
