"""
Direct Stage 3/4 Test - Bypass text gate to validate YOLO + VLM
Tests with actual saved images from Hooters
"""

from pathlib import Path
from stage_3_yolo import YOLODetector
from stage_4_vlm import VLMConfirmation
from cost_tracker import CostTracker
import json

# Setup
cache_dir = Path('/Users/jeffignacio/mplc_pop_engine/cache/images')
tracker = CostTracker('test_stage4_direct.db')
from datetime import datetime
run_id = f'stage4_validation_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=2.0, max_serper_credits=10, accounts_total=1)

# Get saved Dave & Busters / Topgolf images (from recent run)
# Look for images saved around 00:25-00:26 timestamp
all_images = sorted(cache_dir.glob('*.jpg'), key=lambda p: p.stat().st_mtime, reverse=True)
test_images = all_images[:30]  # Test on 30 most recent images

print("="*80)
print("STAGE 3/4 DIRECT VALIDATION TEST")
print("="*80)
print(f"Testing {len(test_images)} most recent images from Dave & Busters / Topgolf")
print()

# Stage 3: YOLO
print("Stage 3: Running YOLO detection...")
print("-"*80)

yolo = YOLODetector(tracker, run_id)
yolo_results = []

for img_path in test_images:
    detections = yolo.detect_objects(img_path)

    # Log
    detection_summary = [d['class'] for d in detections]
    tracker.log_yolo_inference(
        account_id='TEST_HOOTERS',
        image_url=str(img_path),
        detections=detection_summary
    )

    # Analyze context
    analysis = yolo.analyze_context(detections)

    result = {
        'image_path': str(img_path.name),
        'detections': detections,
        'analysis': analysis
    }
    yolo_results.append(result)

    # Print summary
    det_str = ', '.join(detection_summary[:5])
    if len(detection_summary) > 5:
        det_str += f' (+{len(detection_summary)-5} more)'

    status = "✅ PASS" if analysis['pass_to_vlm'] else "❌ SKIP"
    print(f"{status} {img_path.name[:30]:<30} | {det_str}")

# Filter to those that passed YOLO
yolo_passed = [r for r in yolo_results if r['analysis']['pass_to_vlm']]

print()
print(f"YOLO Results: {len(yolo_passed)}/{len(test_images)} images passed to VLM")
print()

# Stage 4: VLM (only if some passed)
if yolo_passed:
    print("Stage 4: Running VLM confirmation...")
    print("-"*80)

    vlm = VLMConfirmation(tracker, run_id)

    vlm_results = []
    for result in yolo_passed[:5]:  # Limit to 5 to save costs
        img_path = cache_dir / result['image_path']
        detections = [d['class'] for d in result['detections']]

        print(f"Analyzing: {result['image_path'][:40]}")

        vlm_result = vlm.analyze_image(
            image_path=str(img_path),
            image_url=str(img_path),
            account_id='TEST_HOOTERS',
            yolo_detections=detections
        )

        vlm_results.append(vlm_result)

        # Print result
        tv = vlm_result.get('tv_present', 'N/A')
        room = vlm_result.get('room_type', 'N/A')
        public = vlm_result.get('public_facing', 'N/A')
        conf = vlm_result.get('confidence', 0)

        print(f"  TV: {tv} | Room: {room} | Public: {public} | Confidence: {conf}%")
        print(f"  Reasoning: {vlm_result.get('reasoning', 'N/A')[:100]}")
        print()

    # Summary
    print()
    print("="*80)
    print("VLM SUMMARY")
    print("="*80)
    tv_confirmed = sum(1 for r in vlm_results if r.get('tv_present') and r.get('public_facing'))
    print(f"Public TVs confirmed: {tv_confirmed}/{len(vlm_results)}")
    print(f"Average confidence: {sum(r.get('confidence', 0) for r in vlm_results) / len(vlm_results):.1f}%")

else:
    print("⚠️  No images passed YOLO filter - cannot test VLM")
    print("    (This is expected if images don't contain TV + supportive context)")

# Cost summary
print()
print("="*80)
print("COST TRACKING")
print("="*80)
totals = tracker.get_run_totals(run_id)
print(f"YOLO inferences: {totals.get('total_yolo_inferences', 0)}")
print(f"VLM API calls: {len(vlm_results) if yolo_passed else 0}")
print(f"Anthropic cost: ${totals.get('total_anthropic_cost', 0):.4f}")
print(f"Anthropic tokens: {totals.get('total_tokens_input', 0)} in + {totals.get('total_tokens_output', 0)} out")

tracker.complete_run(run_id)
tracker.close()
