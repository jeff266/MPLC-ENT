"""
Test all dental office images through YOLO to see what was detected
"""

from pathlib import Path
from stage_3_yolo import YOLODetector
from cost_tracker import CostTracker
from datetime import datetime

# Setup
cache_dir = Path('/Users/jeffignacio/mplc_pop_engine/cache/images')
tracker = CostTracker('test_all_dental.db')
run_id = f'dental_images_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=2.0, max_serper_credits=10, accounts_total=1)

# Get images saved at 00:35 (dental office runs)
import os
all_images = []
for img_path in cache_dir.glob('*'):
    if img_path.suffix in ['.jpg', '.png']:
        mtime = os.path.getmtime(img_path)
        if datetime.fromtimestamp(mtime).strftime('%H:%M') == '00:35':
            all_images.append(img_path)

all_images = sorted(all_images, key=lambda p: p.stat().st_size, reverse=True)[:50]

print("="*80)
print("DENTAL OFFICE IMAGES - COMPREHENSIVE YOLO TEST")
print("="*80)
print(f"Testing {len(all_images)} images from dental offices")
print()

# Run YOLO
yolo = YOLODetector(tracker, run_id)
yolo_results = []

print("YOLO Detection Results:")
print("-"*80)

for img_path in all_images:
    detections = yolo.detect_objects(img_path)

    detection_summary = [d['class'] for d in detections]
    tracker.log_yolo_inference(
        account_id='TEST_DENTAL',
        image_url=str(img_path),
        detections=detection_summary
    )

    analysis = yolo.analyze_context(detections)

    result = {
        'image_path': str(img_path.name),
        'detections': detections,
        'analysis': analysis,
        'size_kb': img_path.stat().st_size / 1024
    }
    yolo_results.append(result)

    # Print summary
    det_str = ', '.join(detection_summary[:5])
    if len(detection_summary) > 5:
        det_str += f' (+{len(detection_summary)-5} more)'
    elif not detection_summary:
        det_str = 'none'

    status = "✅ PASS" if analysis['pass_to_vlm'] else "❌ SKIP"
    size = f"{result['size_kb']:.0f}KB"
    print(f"{status} {img_path.name[:35]:<35} {size:>8} | {det_str}")

# Summary
yolo_passed = [r for r in yolo_results if r['analysis']['pass_to_vlm']]

print()
print("="*80)
print("SUMMARY")
print("="*80)
print(f"Images processed: {len(all_images)}")
print(f"Images passed to VLM: {len(yolo_passed)}")
print()

if yolo_passed:
    print("Images that passed YOLO filter:")
    for r in yolo_passed:
        print(f"  - {r['image_path']}")
        print(f"    Detections: {[d['class'] for d in r['detections']]}")
        print(f"    Supportive: {r['analysis']['supportive_objects']}")
else:
    print("No images passed YOLO filter")
    print()
    print("Common detections found:")
    all_detections = {}
    for r in yolo_results:
        for d in r['detections']:
            cls = d['class']
            all_detections[cls] = all_detections.get(cls, 0) + 1

    if all_detections:
        sorted_dets = sorted(all_detections.items(), key=lambda x: x[1], reverse=True)
        for cls, count in sorted_dets[:10]:
            print(f"  {cls}: {count}")

tracker.complete_run(run_id)
tracker.close()
