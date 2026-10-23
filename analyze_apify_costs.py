"""Analyze Apify cost structure"""

# Apify pricing breakdown (from their docs)
print("="*80)
print("APIFY COST BREAKDOWN - Why We Hit $17.86 So Fast")
print("="*80)

# Cost structure
cost_per_1000_results = 0.30  # $0.30 per 1,000 results
minimum_charge_per_run = 0.007  # ~$0.007 per actor start

# What we did
v1_accounts = 39
v2_accounts = 39
test_runs = 3

total_runs = v1_accounts + v2_accounts + test_runs
reviews_per_account = 25  # We requested 25 reviews each

# Calculate
total_reviews = total_runs * reviews_per_account
result_cost = (total_reviews / 1000) * cost_per_1000_results

# Actor compute time charges (the real killer)
avg_runtime_seconds = 8  # From logs: ~8 seconds per account
compute_cost_per_hour = 0.49  # Apify compute cost
compute_cost_per_second = compute_cost_per_hour / 3600

total_compute_cost = total_runs * avg_runtime_seconds * compute_cost_per_second

total_cost = result_cost + total_compute_cost

print(f"\n1. RESULT COSTS (cheap):")
print(f"   Total runs: {total_runs}")
print(f"   Reviews per run: {reviews_per_account}")
print(f"   Total reviews: {total_reviews:,}")
print(f"   Cost: {total_reviews:,} × ${cost_per_1000_results}/1000 = ${result_cost:.2f}")

print(f"\n2. COMPUTE COSTS (expensive):")
print(f"   Runs: {total_runs}")
print(f"   Avg runtime: {avg_runtime_seconds}s per run")
print(f"   Total compute time: {total_runs * avg_runtime_seconds / 60:.1f} minutes")
print(f"   Compute rate: ${compute_cost_per_hour}/hour = ${compute_cost_per_second:.6f}/second")
print(f"   Cost: {total_runs} × {avg_runtime_seconds}s × ${compute_cost_per_second:.6f} = ${total_compute_cost:.2f}")

print(f"\n3. TOTAL ESTIMATED COST:")
print(f"   Results: ${result_cost:.2f}")
print(f"   Compute: ${total_compute_cost:.2f}")
print(f"   TOTAL: ${total_cost:.2f}")
print(f"   Your actual: $17.86")
print(f"   Match: {abs(total_cost - 17.86) < 2}")

# The real issue
print(f"\n{'='*80}")
print(f"THE REAL ISSUE:")
print(f"{'='*80}")
print(f"\nEach actor run has:")
print(f"  1. Container startup (~2-3 seconds)")
print(f"  2. Google Maps search (~1-2 seconds)")
print(f"  3. Review scraping (~3-5 seconds)")
print(f"  = ~8 seconds × 81 runs = 10.8 minutes of compute")
print(f"  = 10.8 minutes × $0.49/hour = ${10.8/60 * 0.49:.2f}")

print(f"\nWHY IT'S EXPENSIVE:")
print(f"  ✗ Sequential processing (no batching)")
print(f"  ✗ New container for each business")
print(f"  ✗ Ran twice (V1 + V2 = 78 lookups)")
print(f"  ✗ No caching between runs")

print(f"\nCOST OPTIMIZATION:")
print(f"  ✓ Batch requests (1 run, multiple businesses)")
print(f"  ✓ Cache results (don't re-fetch for V2)")
print(f"  ✓ Test on 3 accounts first (${3 * 8 * compute_cost_per_second:.2f} vs ${total_compute_cost:.2f})")

