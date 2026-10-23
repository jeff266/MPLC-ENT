"""
Test dental office waiting room image for TV
"""

from pathlib import Path
from stage_4_vlm import VLMConfirmation
from cost_tracker import CostTracker
from datetime import datetime

# Setup
tracker = CostTracker('test_dental.db')
run_id = f'dental_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=1.0, max_serper_credits=10, accounts_total=1)

# Test the waiting room interior photo
image_path = '/Users/jeffignacio/mplc_pop_engine/cache/images/96f82fe15c2e355112bedc99370256fa.jpg'

vlm = VLMConfirmation(tracker, run_id)

print("="*80)
print("DENTAL OFFICE WAITING ROOM TEST")
print("="*80)
print(f"Image: {Path(image_path).name}")
print("Shows: Interior waiting room with couches")
print()
print("-"*80)

result = vlm.analyze_image(
    image_path=image_path,
    image_url=image_path,
    account_id="TEST_DENTAL",
    yolo_detections=['couch']  # Simulating context objects
)

print("VLM Analysis:")
print("-"*80)
print(f"TV Present: {result.get('tv_present')}")
print(f"Room Type: {result.get('room_type')}")
print(f"Public Facing: {result.get('public_facing')}")
print(f"Confidence: {result.get('confidence')}%")
print(f"Reasoning: {result.get('reasoning')}")

if result.get('tv_present'):
    print("\n🎯 TRUE POSITIVE FOUND!")
else:
    print("\n✓ No TV in this waiting room")

# Show cost
totals = tracker.get_run_totals(run_id)
print()
print("="*80)
print(f"Cost: ${totals.get('total_anthropic_cost', 0):.4f}")

tracker.complete_run(run_id)
tracker.close()
