"""
Manual Stage 4 Test - Force a test image through VLM
Downloads a known sports bar image with TV to validate Stage 4
"""

import requests
from pathlib import Path
from stage_4_vlm import VLMConfirmation
from cost_tracker import CostTracker

# Setup
test_dir = Path('/Users/jeffignacio/mplc_pop_engine/test_images')
test_dir.mkdir(exist_ok=True)

# Download a test image (sports bar with TV)
# Using a public domain image URL
test_url = "https://images.unsplash.com/photo-1543007630-9710e4a00a20?w=800"  # Sports bar
test_path = test_dir / "sports_bar_test.jpg"

print("Downloading test image...")
try:
    response = requests.get(test_url, timeout=10)
    if response.status_code == 200:
        with open(test_path, 'wb') as f:
            f.write(response.content)
        print(f"✓ Downloaded: {test_path}")
    else:
        print(f"❌ Download failed: {response.status_code}")
        print("Using existing test image if available...")
except Exception as e:
    print(f"❌ Error: {e}")
    print("Using existing test image if available...")

if not test_path.exists():
    print("No test image available. Exiting.")
    exit(1)

# Test VLM
tracker = CostTracker('test_stage4_manual.db')
run_id = 'manual_vlm_test'
tracker.create_run(run_id, max_cost_usd=1.0, max_serper_credits=100, accounts_total=1)

vlm = VLMConfirmation(tracker, run_id)

print()
print("="*80)
print("MANUAL VLM TEST - FORCING IMAGE THROUGH STAGE 4")
print("="*80)
print()

result = vlm.analyze_image(
    image_path=str(test_path),
    image_url="test_sports_bar",
    account_id="MANUAL_TEST",
    yolo_detections=['tv', 'couch', 'chair']  # Simulating YOLO found TV + context
)

print("VLM Response:")
print("-"*80)
print(f"TV Present: {result.get('tv_present')}")
print(f"Room Type: {result.get('room_type')}")
print(f"Public Facing: {result.get('public_facing')}")
print(f"Confidence: {result.get('confidence')}%")
print(f"Reasoning: {result.get('reasoning')}")

if result.get('error'):
    print(f"\n❌ ERROR: {result.get('reasoning')}")
else:
    print(f"\n✅ VLM CALL SUCCEEDED")

# Show cost
totals = tracker.get_run_totals(run_id)
print()
print("="*80)
print(f"Anthropic Cost: ${totals.get('total_anthropic_cost', 0):.4f}")
print(f"Tokens: {totals.get('total_tokens_input', 0)} in + {totals.get('total_tokens_output', 0)} out")
print(f"Model: {result.get('model')}")

tracker.complete_run(run_id)
tracker.close()
