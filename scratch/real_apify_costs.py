"""Check actual Apify costs from screenshot"""

# From screenshot: $1.47 for 0 results shown (but file has 25 reviews)
single_run_cost = 1.47

# Total runs
v1_runs = 39  # First eval
v2_runs = 39  # Second eval  
test_runs = 3  # Heartland, Gentle Dental, AutoNation

total_runs = v1_runs + v2_runs + test_runs

# If each run costs ~$1.47
estimated_total = total_runs * single_run_cost

print("="*80)
print("ACTUAL APIFY COSTS")
print("="*80)

print(f"\nFrom screenshot: Single run (Joyce Honda) = ${single_run_cost}")
print(f"\nTotal runs: {total_runs}")
print(f"  V1 eval: {v1_runs} accounts")
print(f"  V2 eval: {v2_runs} accounts")
print(f"  Test runs: {test_runs} accounts")

print(f"\nEstimated total: {total_runs} × ${single_run_cost} = ${estimated_total:.2f}")
print(f"Your actual bill: $17.86")
print(f"Difference: ${abs(estimated_total - 17.86):.2f}")

# But wait - that's way too high per run
print("\n" + "="*80)
print("DISCREPANCY ANALYSIS")
print("="*80)

if estimated_total > 17.86:
    actual_per_run = 17.86 / total_runs
    print(f"\nActual cost per run: $17.86 / {total_runs} = ${actual_per_run:.2f}")
    print(f"\nScreenshot shows $1.47 for ONE run")
    print(f"But total bill ÷ runs = ${actual_per_run:.2f} per run")
    print(f"\nPossible explanations:")
    print(f"  1. Screenshot is for a DIFFERENT run (not from our evals)")
    print(f"  2. Some runs were cheaper (fewer results)")
    print(f"  3. Batch discounting applied")

# Check if $17.86 makes sense
print("\n" + "="*80)
print("VALIDATION")
print("="*80)

# Apify standard pricing is typically $0.20-0.50 per run for small actors
low_estimate = total_runs * 0.20
high_estimate = total_runs * 0.50

print(f"\nTypical Apify cost range:")
print(f"  Low ($0.20/run): {total_runs} × $0.20 = ${low_estimate:.2f}")
print(f"  High ($0.50/run): {total_runs} × $0.50 = ${high_estimate:.2f}")
print(f"  Your actual: $17.86")

if low_estimate <= 17.86 <= high_estimate:
    print(f"\n✓ Your cost is WITHIN normal range")
    actual_per_run = 17.86 / total_runs
    print(f"  Actual cost per run: ${actual_per_run:.2f}")
else:
    print(f"\n⚠️  Cost is outside normal range - investigating...")

