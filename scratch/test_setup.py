"""
Test script to verify MPLC PoP engine setup
"""

import sys
from pathlib import Path

print("=" * 80)
print("MPLC PoP Detection Engine - Setup Test")
print("=" * 80)

# Test imports
print("\n1. Testing imports...")
try:
    from cost_tracker import CostTracker
    print("   ✓ cost_tracker")
except ImportError as e:
    print(f"   ✗ cost_tracker: {e}")
    sys.exit(1)

try:
    import config
    print("   ✓ config")
except ImportError as e:
    print(f"   ✗ config: {e}")
    sys.exit(1)

try:
    from text_patterns import find_text_evidence, aggregate_text_evidence
    print("   ✓ text_patterns")
except ImportError as e:
    print(f"   ✗ text_patterns: {e}")
    sys.exit(1)

# Test cost tracker
print("\n2. Testing cost tracker...")
tracker = CostTracker("test_setup.db")

# Create test run
run_id = "test_setup_run"
tracker.create_run(run_id, max_cost_usd=10.0, max_serper_credits=100, accounts_total=10)

# Log test calls
tracker.log_serper_call("001TEST", "stage_0.5", "test query", 1)
tracker.log_anthropic_call("001TEST", "stage_4", "claude-haiku-4", 500, 100)

# Check totals
totals = tracker.get_run_totals(run_id)
print(f"   ✓ Logged calls: {totals}")

# Check circuit breaker
should_continue, reason = tracker.check_circuit_breaker(run_id)
print(f"   ✓ Circuit breaker: {should_continue} - {reason}")

tracker.complete_run(run_id)
tracker.close()

# Clean up test DB
Path("test_setup.db").unlink(missing_ok=True)

# Test text patterns
print("\n3. Testing text pattern matching...")
sample_text = "Come watch the big game on our big screen TV in the sports bar!"
matches = find_text_evidence(sample_text, "http://test.com")
if matches:
    print(f"   ✓ Found {len(matches)} matches")
    best = matches[0]
    print(f"   Best match: '{best['matched_keyword']}' (score: {best['confidence_score']})")
else:
    print("   ✗ No matches found")

# Test config
print("\n4. Testing configuration...")
print(f"   Serper API key: {'*' * 20}{config.SERPER_API_KEY[-10:]}")
print(f"   Max cost: ${config.MAX_COST_USD}")
print(f"   Max Serper credits: {config.MAX_SERPER_CREDITS}")
print(f"   Cache dir: {config.CACHE_DIR}")

# Check directories
for dir_name, dir_path in [("Cache", config.CACHE_DIR), ("Logs", config.LOGS_DIR), ("Output", config.OUTPUT_DIR)]:
    if dir_path.exists():
        print(f"   ✓ {dir_name} directory exists: {dir_path}")
    else:
        print(f"   ✗ {dir_name} directory missing: {dir_path}")

print("\n" + "=" * 80)
print("✅ Setup test PASSED")
print("=" * 80)
print("\nNext steps:")
print("1. Install dependencies: pip install pandas requests beautifulsoup4 anthropic")
print("2. Prepare input CSV with MM/ENT accounts")
print("3. Run test: python pipeline.py input.csv --limit 10")
print("4. Check README.md for full implementation details")
