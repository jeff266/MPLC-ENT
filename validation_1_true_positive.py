"""
VALIDATION GAP 1: True-positive sanity test
Find a stock photo with TV in shared space, test VLM detection
"""

import requests
import json
from pathlib import Path
from stage_4_vlm import VLMConfirmation
from cost_tracker import CostTracker
from datetime import datetime
import config

# Setup
tracker = CostTracker('validation_tests.db')
run_id = f'true_positive_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=1.0, max_serper_credits=10, accounts_total=1)

print("="*80)
print("VALIDATION GAP 1: TRUE-POSITIVE SANITY TEST")
print("="*80)
print()

# Step 1: Use Serper Images API to find a sports bar interior with TV
print("Step 1: Searching for sports bar interior images with TV...")
print("-"*80)

serper_payload = {
    "q": "sports bar interior television screens",
    "gl": "us",
    "num": 10
}

headers = {
    "X-API-KEY": config.SERPER_API_KEY,
    "Content-Type": "application/json"
}

try:
    response = requests.post(
        "https://google.serper.dev/images",
        json=serper_payload,
        headers=headers,
        timeout=10
    )

    if response.status_code == 200:
        results = response.json()
        images = results.get('images', [])

        print(f"✓ Found {len(images)} images")
        print()

        if images:
            # Pick the first high-quality image
            test_image = images[0]
            image_url = test_image['imageUrl']

            print(f"Selected image:")
            print(f"  URL: {image_url}")
            print(f"  Title: {test_image.get('title', 'N/A')}")
            print(f"  Source: {test_image.get('source', 'N/A')}")
            print()

            # Download image
            print("Step 2: Downloading image...")
            print("-"*80)

            img_response = requests.get(image_url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            })

            if img_response.status_code == 200:
                # Save to test directory
                test_dir = Path('/Users/jeffignacio/mplc_pop_engine/validation_tests')
                test_dir.mkdir(exist_ok=True)

                # Determine correct extension from URL or Content-Type
                if image_url.endswith('.webp'):
                    ext = '.webp'
                elif image_url.endswith('.png'):
                    ext = '.png'
                elif 'webp' in img_response.headers.get('content-type', ''):
                    ext = '.webp'
                elif 'png' in img_response.headers.get('content-type', ''):
                    ext = '.png'
                else:
                    ext = '.jpg'

                image_path = test_dir / f"true_positive_test{ext}"
                with open(image_path, 'wb') as f:
                    f.write(img_response.content)

                print(f"✓ Downloaded: {image_path}")
                print(f"  Size: {len(img_response.content) / 1024:.1f} KB")
                print()

                # Step 3: Run through VLM
                print("Step 3: Testing VLM detection...")
                print("-"*80)

                vlm = VLMConfirmation(tracker, run_id)

                result = vlm.analyze_image(
                    image_path=str(image_path),
                    image_url=image_url,
                    account_id="VALIDATION_TEST",
                    yolo_detections=[]  # Bypass YOLO - testing VLM directly
                )

                print()
                print("="*80)
                print("VLM RESULT")
                print("="*80)
                print(f"TV Present: {result.get('tv_present')}")
                print(f"Room Type: {result.get('room_type')}")
                print(f"Public Facing: {result.get('public_facing')}")
                print(f"Confidence: {result.get('confidence')}%")
                print(f"Reasoning: {result.get('reasoning')}")
                print()

                # Validate result
                if result.get('tv_present') is True:
                    print("✅ VALIDATION PASSED - VLM correctly detected TV in shared space")
                    print(f"   Confidence: {result.get('confidence')}%")

                    if result.get('public_facing') is True:
                        print("✅ BONUS - VLM correctly identified public-facing space")
                else:
                    print("❌ VALIDATION FAILED - VLM did not detect TV")
                    print("   This indicates a bug in Stage 4 prompt or parsing")
                    print(f"   Image URL for manual review: {image_url}")

                # Cost tracking
                totals = tracker.get_run_totals(run_id)
                print()
                print("="*80)
                anthropic_cost = totals.get('total_anthropic_cost', 0) or 0
                tokens_in = totals.get('total_tokens_input', 0) or 0
                tokens_out = totals.get('total_tokens_output', 0) or 0
                print(f"Cost: ${anthropic_cost:.4f}")
                print(f"Tokens: {tokens_in} in + {tokens_out} out")

            else:
                print(f"❌ Failed to download image: HTTP {img_response.status_code}")

        else:
            print("❌ No images found in Serper results")
    else:
        print(f"❌ Serper API error: HTTP {response.status_code}")
        print(response.text)

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

tracker.complete_run(run_id)
tracker.close()
