"""
Manual VLM Test - Check if interior photo has TV that YOLO missed
"""

from pathlib import Path
from stage_4_vlm import VLMConfirmation
from cost_tracker import CostTracker
from datetime import datetime

# Setup
tracker = CostTracker('test_manual_vlm.db')
run_id = f'manual_vlm_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=1.0, max_serper_credits=10, accounts_total=1)

# Test the interior photo that YOLO processed
image_path = '/Users/jeffignacio/mplc_pop_engine/cache/images/971823336ba582f64c99e253cd62fc76.jpg'

vlm = VLMConfirmation(tracker, run_id)

print("="*80)
print("MANUAL VLM TEST - Interior Photo from Dave & Busters/Topgolf")
print("="*80)
print(f"Image: {Path(image_path).name}")
print()
print("YOLO detected: person (16x), but no TV")
print("Question: Did YOLO miss a TV that's actually in frame?")
print()
print("-"*80)

result = vlm.analyze_image(
    image_path=image_path,
    image_url=image_path,
    account_id="TEST_MANUAL",
    yolo_detections=['person'] * 16  # Simulating YOLO's output
)

print("VLM Analysis:")
print("-"*80)
print(f"TV Present: {result.get('tv_present')}")
print(f"Room Type: {result.get('room_type')}")
print(f"Public Facing: {result.get('public_facing')}")
print(f"Confidence: {result.get('confidence')}%")
print(f"Reasoning: {result.get('reasoning')}")

if result.get('tv_present'):
    print("\n✅ TRUE POSITIVE - VLM found TV that YOLO missed!")
else:
    print("\n✓ Confirmed - No TV in this image")

# Show cost
totals = tracker.get_run_totals(run_id)
print()
print("="*80)
print(f"Cost: ${totals.get('total_anthropic_cost', 0):.4f}")
print(f"Tokens: {totals.get('total_tokens_input', 0)} in + {totals.get('total_tokens_output', 0)} out")

tracker.complete_run(run_id)
tracker.close()
