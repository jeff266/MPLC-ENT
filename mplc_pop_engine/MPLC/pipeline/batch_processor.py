#!/usr/bin/env python3
"""
Batch Processor - Stage 3 of Pipeline

Processes vertical-routed accounts through PoP detection pipeline:
1. Translate CSV to standard schema
2. Check enrichment ledger (90-day dedup)
3. Find Yelp URL
4. Download photos
5. YOLO TV pre-filter
6. VLM classification
7. Save evidence
8. Record in ledger

Uses existing components from vertical scripts.
"""

import sys
import csv
import time
import requests
import base64
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Add core to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.csv_translator import translate_csv_file
from core.enrichment_ledger import EnrichmentLedger
from core.evidence_persistence import EvidenceRecorder

# Import API clients (need config)
try:
    sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
    from config import APIFY_API_TOKEN, ANTHROPIC_API_KEY
    from apify_client import ApifyClient
    from anthropic import Anthropic
    from ultralytics import YOLO
except ImportError as e:
    print(f"⚠️  Missing dependency: {e}")
    print("Install: pip install apify-client anthropic ultralytics")
    sys.exit(1)


class BatchProcessor:
    """Process accounts through PoP detection pipeline in batch."""

    def __init__(
        self,
        vertical_name: str,
        ledger_path: str = "enrichment_ledger.db",
        evidence_dir: str = "output/evidence"
    ):
        """Initialize batch processor.

        Args:
            vertical_name: Name of vertical (corporate, auto, healthcare, etc.)
            ledger_path: Path to enrichment ledger SQLite database
            evidence_dir: Directory to save evidence photos
        """
        self.vertical_name = vertical_name
        self.ledger = EnrichmentLedger(ledger_path)
        self.evidence = EvidenceRecorder(evidence_dir)

        # API clients
        self.apify_client = ApifyClient(APIFY_API_TOKEN)
        self.anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.yolo_model = YOLO('yolo11n.pt')

        # Statistics
        self.stats = {
            'total_accounts': 0,
            'skipped_recent_enrichment': 0,
            'processed': 0,
            'yelp_not_found': 0,
            'no_photos': 0,
            'no_tv_detected': 0,
            'prospect': 0,
            'suspect': 0,
            'rejected': 0,
            'errors': 0,
            'total_cost': 0.0
        }

    def find_yelp_url(self, account_name: str, city: str, state: str) -> Optional[Dict]:
        """Find Yelp business URL using Apify Business Scraper.

        Args:
            account_name: Business name
            city: City (optional)
            state: State (optional)

        Returns:
            Dict with Yelp data or None if not found
        """
        try:
            # Build search query and location
            query = account_name
            location = f"{city}, {state}" if city and state else state if state else "United States"

            run_input = {
                "searchQueries": [query],
                "searchLocations": [location],
                "maxResultsPerSearch": 1
            }

            run = self.apify_client.actor("beatanalytics/yelp-business-scraper").call(run_input=run_input)

            for item in self.apify_client.dataset(run.default_dataset_id).iterate_items():
                return {
                    'name': item.get('name'),
                    'url': item.get('url'),
                    'alias': item.get('alias'),
                    'rating': item.get('avg_rating'),
                    'review_count': item.get('review_count')
                }

            return None

        except Exception as e:
            print(f"    ⚠️  Yelp search error: {e}")
            return None

    def download_photos(self, yelp_url: str, max_photos: int = 50) -> List[Dict]:
        """Download photos from Yelp using Apify Photos Scraper.

        Args:
            yelp_url: Yelp business URL
            max_photos: Maximum number of photos to download

        Returns:
            List of photo dictionaries with 'url' and 'caption'
        """
        try:
            run_input = {
                "businessUrls": [{"url": yelp_url}],
                "category": "all",
                "maxPhotos": max_photos,
                "includeSensitiveData": False
            }

            run = self.apify_client.actor("beatanalytics/yelp-photos-scraper").call(run_input=run_input)

            photos = []
            for item in self.apify_client.dataset(run.default_dataset_id).iterate_items():
                if item.get('type') == 'photo':
                    photos.append({
                        'url': item.get('url'),
                        'caption': item.get('caption', ''),
                        'date': item.get('date', '')
                    })

            return photos

        except Exception as e:
            print(f"    ⚠️  Photo download error: {e}")
            return []

    def yolo_detect_tv(self, image_path: str) -> List[Dict]:
        """Detect TVs/monitors in image using YOLO.

        Args:
            image_path: Path to image file

        Returns:
            List of detection dictionaries
        """
        try:
            results = self.yolo_model(image_path, conf=0.20, verbose=False)
            detections = []

            for result in results:
                if result.boxes:
                    for box in result.boxes:
                        class_id = int(box.cls[0])
                        class_name = self.yolo_model.names[class_id]
                        if class_name in ['tv', 'monitor']:
                            detections.append({
                                'class': class_name,
                                'confidence': float(box.conf[0])
                            })

            return detections

        except Exception as e:
            print(f"    ⚠️  YOLO error: {e}")
            return []

    def download_image(self, url: str, save_path: str) -> bool:
        """Download image from URL.

        Args:
            url: Image URL
            save_path: Where to save image

        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                return True
        except:
            pass
        return False

    def classify_photo_vlm(self, image_path: str) -> Dict:
        """Classify photo using VLM (Claude Sonnet 4.5).

        Args:
            image_path: Path to image

        Returns:
            Classification dictionary with tier, space, tv, confidence
        """
        try:
            with open(image_path, 'rb') as f:
                image_data = base64.standard_b64encode(f.read()).decode('utf-8')

            prompt = f"""Classify this {self.vertical_name} facility photo:

PROSPECT: ALL must be true:
- TV/monitor confirmed POWERED ON with visible content
- Located in CUSTOMER area (waiting area, lounge, lobby, customer seating)
- Real facility photo (not stock/promotional)

SUSPECT:
- TV present but not confirmed powered on
- Stock/promotional photo
- Space type unclear

REJECTED: No TV visible

Format:
TIER: [PROSPECT/SUSPECT/REJECTED]
SPACE: [waiting_area/lounge/lobby/service_area/staff_only/unclear]
TV: [on_with_content/unclear/off/none]
PHOTO_TYPE: [real_facility/stock_catalog/unclear]
DESCRIPTION: [One sentence describing what's visible]
CONFIDENCE: [high/medium/low]"""

            response = self.anthropic_client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=150,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data
                        }},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )

            output = response.content[0].text.strip()
            cost = (response.usage.input_tokens * 0.003 / 1000) + (response.usage.output_tokens * 0.015 / 1000)

            # Parse output
            lines = output.split('\n')
            parsed = {}
            for line in lines:
                if ':' in line:
                    key, val = line.split(':', 1)
                    parsed[key.strip()] = val.strip()

            return {
                'tier': parsed.get('TIER', 'UNKNOWN'),
                'space': parsed.get('SPACE', 'unknown'),
                'tv': parsed.get('TV', 'unknown'),
                'photo_type': parsed.get('PHOTO_TYPE', 'unknown'),
                'description': parsed.get('DESCRIPTION', ''),
                'confidence': parsed.get('CONFIDENCE', 'low'),
                'cost': cost,
                'raw_output': output
            }

        except Exception as e:
            print(f"    ⚠️  VLM error: {e}")
            return {
                'tier': 'ERROR',
                'space': 'unknown',
                'tv': 'unknown',
                'photo_type': 'unknown',
                'description': str(e),
                'confidence': 'low',
                'cost': 0.0
            }

    def determine_final_tier(self, classifications: List[Dict]) -> str:
        """Determine final tier from multiple photo classifications.

        Args:
            classifications: List of VLM classification results

        Returns:
            'PROSPECT', 'SUSPECT', or 'REJECTED'
        """
        if not classifications:
            return 'REJECTED'

        # If ANY photo is PROSPECT, account is PROSPECT
        if any(c.get('tier') == 'PROSPECT' for c in classifications):
            return 'PROSPECT'

        # If ANY photo is SUSPECT, account is SUSPECT
        if any(c.get('tier') == 'SUSPECT' for c in classifications):
            return 'SUSPECT'

        # Otherwise, REJECTED
        return 'REJECTED'

    def process_account(self, account: Dict) -> Optional[Dict]:
        """Process a single account through PoP detection pipeline.

        Args:
            account: Account dictionary (standardized schema)

        Returns:
            Result dictionary or None if skipped
        """
        account_id = account['account_id']
        account_name = account['account_name']

        print(f"\n  Processing: {account_name}")

        # Step 1: Check enrichment ledger (90-day dedup)
        if not self.ledger.should_enrich(account_id, 'yelp_pop_detection'):
            print(f"    ⏭  Skipped (enriched within 90 days)")
            self.stats['skipped_recent_enrichment'] += 1
            return None

        total_cost = 0.0

        try:
            # Step 2: Find Yelp URL
            print(f"    🔍 Finding Yelp URL...")
            yelp_data = self.find_yelp_url(
                account_name,
                account.get('city', ''),
                account.get('state', '')
            )

            if not yelp_data:
                print(f"    ❌ Yelp URL not found")
                self.stats['yelp_not_found'] += 1
                self.ledger.record_enrichment(
                    account_id, account_name, 'yelp_pop_detection',
                    result_status='not_found',
                    result_data={'reason': 'yelp_url_not_found'},
                    cost_usd=0.0025, source='apify_yelp'
                )
                return None

            total_cost += 0.0025  # Yelp search cost

            # Step 3: Download photos
            print(f"    📷 Downloading photos...")
            photos = self.download_photos(yelp_data['url'], max_photos=30)

            if not photos:
                print(f"    ❌ No photos found")
                self.stats['no_photos'] += 1
                self.ledger.record_enrichment(
                    account_id, account_name, 'yelp_pop_detection',
                    result_status='not_found',
                    result_data={'reason': 'no_photos', 'yelp_url': yelp_data['url']},
                    cost_usd=total_cost, source='apify_yelp'
                )
                return None

            total_cost += 0.002 * len(photos)  # Photo download cost

            # Step 4: YOLO pre-filter
            print(f"    🤖 YOLO filtering {len(photos)} photos...")
            tv_candidates = []

            # Create temp directory for images
            temp_dir = Path('temp_images')
            temp_dir.mkdir(exist_ok=True)

            for i, photo in enumerate(photos[:10]):  # Limit to first 10 photos
                temp_path = temp_dir / f"{account_id}_{i}.jpg"

                if self.download_image(photo['url'], str(temp_path)):
                    detections = self.yolo_detect_tv(str(temp_path))
                    if detections:
                        tv_candidates.append({
                            'photo': photo,
                            'temp_path': temp_path,
                            'yolo_detections': detections
                        })

            if not tv_candidates:
                print(f"    ❌ No TVs detected by YOLO")
                self.stats['no_tv_detected'] += 1

                # Clean up temp files
                for f in temp_dir.glob(f"{account_id}_*"):
                    f.unlink()

                self.ledger.record_enrichment(
                    account_id, account_name, 'yelp_pop_detection',
                    result_status='not_found',
                    result_data={'reason': 'no_tv_detected', 'photos_checked': len(photos)},
                    cost_usd=total_cost, source='yolo_local'
                )
                return None

            # Step 5: VLM classification
            print(f"    🧠 VLM classifying {len(tv_candidates)} TV candidates...")
            classifications = []

            for candidate in tv_candidates[:3]:  # Limit to top 3 TV candidates
                result = self.classify_photo_vlm(str(candidate['temp_path']))
                result['yolo_confidence'] = max(d['confidence'] for d in candidate['yolo_detections'])
                classifications.append(result)
                total_cost += result['cost']

            # Step 6: Determine final tier
            final_tier = self.determine_final_tier(classifications)
            print(f"    ✅ Result: {final_tier}")

            # Update stats
            self.stats['processed'] += 1
            self.stats[final_tier.lower()] += 1
            self.stats['total_cost'] += total_cost

            # Step 7: Save evidence
            if final_tier in ['PROSPECT', 'SUSPECT']:
                best_classification = max(
                    classifications,
                    key=lambda c: 1 if c['tier'] == 'PROSPECT' else 0.5 if c['tier'] == 'SUSPECT' else 0
                )

                self.evidence.add_evidence(
                    account_name=account_name,
                    channel='yelp_photos',
                    tier=final_tier,
                    evidence_photo_location=str(tv_candidates[0]['temp_path']),
                    evidence_description=best_classification['description'],
                    yolo_confidence=best_classification['yolo_confidence'],
                    vlm_confidence=best_classification['confidence'],
                    source_url=yelp_data['url'],
                    space_type=best_classification['space'],
                    tv_powered_on=(best_classification['tv'] == 'on_with_content'),
                    cost=total_cost,
                    vertical=self.vertical_name
                )

            # Step 8: Record in ledger
            self.ledger.record_enrichment(
                account_id, account_name, 'yelp_pop_detection',
                result_status='success',
                result_data={
                    'tier': final_tier,
                    'yelp_url': yelp_data['url'],
                    'photos_found': len(photos),
                    'tv_candidates': len(tv_candidates),
                    'classifications': classifications
                },
                cost_usd=total_cost,
                source='yelp_yolo_vlm'
            )

            # Clean up temp files
            for f in temp_dir.glob(f"{account_id}_*"):
                f.unlink()

            return {
                'account_id': account_id,
                'account_name': account_name,
                'tier': final_tier,
                'yelp_url': yelp_data['url'],
                'cost': total_cost,
                'classifications': classifications
            }

        except Exception as e:
            print(f"    ❌ Error: {e}")
            self.stats['errors'] += 1
            self.ledger.record_enrichment(
                account_id, account_name, 'yelp_pop_detection',
                result_status='failure',
                result_data={'error': str(e)},
                cost_usd=total_cost,
                source='error'
            )
            return None

    def process_batch(
        self,
        input_csv: str,
        max_accounts: Optional[int] = None
    ) -> List[Dict]:
        """Process a batch of accounts from CSV.

        Args:
            input_csv: Path to input CSV (will be translated to standard schema)
            max_accounts: Optional limit on number of accounts to process

        Returns:
            List of result dictionaries
        """
        # Step 1: Translate CSV to standard schema
        print(f"\n{'='*70}")
        print(f"BATCH PROCESSOR - {self.vertical_name.upper()}")
        print(f"{'='*70}\n")

        standardized_csv = input_csv.replace('.csv', '_standardized.csv')
        print(f"Step 1: Translating CSV to standard schema...")
        translate_csv_file(input_csv, standardized_csv, print_report=True)

        # Step 2: Load accounts
        print(f"\nStep 2: Loading accounts...")
        with open(standardized_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            accounts = list(reader)

        if max_accounts:
            accounts = accounts[:max_accounts]

        self.stats['total_accounts'] = len(accounts)
        print(f"✓ Loaded {len(accounts):,} accounts\n")

        # Step 3: Process each account
        print(f"Step 3: Processing accounts through PoP detection pipeline...")
        results = []

        for i, account in enumerate(accounts, 1):
            print(f"\n[{i}/{len(accounts)}]", end='')
            result = self.process_account(account)
            if result:
                results.append(result)

            # Rate limiting (don't overwhelm APIs)
            if i % 10 == 0:
                print(f"\n  ⏸  Pausing 2 seconds...")
                time.sleep(2)

        # Print summary
        self.print_summary()

        # Save evidence
        evidence_file = self.evidence.save(filename=f"{self.vertical_name}_evidence_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        print(f"\n✓ Saved evidence: {evidence_file}")

        return results

    def print_summary(self):
        """Print batch processing summary."""
        print(f"\n{'='*70}")
        print(f"BATCH PROCESSING SUMMARY - {self.vertical_name.upper()}")
        print(f"{'='*70}")
        print(f"Total accounts: {self.stats['total_accounts']:,}")
        print(f"\nProcessing:")
        print(f"  Skipped (recent enrichment): {self.stats['skipped_recent_enrichment']:,}")
        print(f"  Processed: {self.stats['processed']:,}")
        print(f"  Errors: {self.stats['errors']:,}")
        print(f"\nResults:")
        print(f"  PROSPECT: {self.stats['prospect']:,} ({self.stats['prospect']/max(self.stats['processed'],1)*100:.1f}%)")
        print(f"  SUSPECT: {self.stats['suspect']:,} ({self.stats['suspect']/max(self.stats['processed'],1)*100:.1f}%)")
        print(f"  REJECTED: {self.stats['rejected']:,} ({self.stats['rejected']/max(self.stats['processed'],1)*100:.1f}%)")
        print(f"\nNot Found:")
        print(f"  Yelp URL not found: {self.stats['yelp_not_found']:,}")
        print(f"  No photos: {self.stats['no_photos']:,}")
        print(f"  No TV detected: {self.stats['no_tv_detected']:,}")
        print(f"\nCost:")
        print(f"  Total cost: ${self.stats['total_cost']:.2f}")
        if self.stats['processed'] > 0:
            print(f"  Cost per account: ${self.stats['total_cost']/self.stats['processed']:.3f}")
        print(f"{'='*70}\n")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Batch PoP Detection Processor')
    parser.add_argument('input_csv', help='Input CSV file (vertical-routed accounts)')
    parser.add_argument('--vertical', required=True, help='Vertical name (corporate, auto, healthcare, etc.)')
    parser.add_argument('--max-accounts', type=int, help='Maximum number of accounts to process (for testing)')
    args = parser.parse_args()

    processor = BatchProcessor(vertical_name=args.vertical)
    results = processor.process_batch(args.input_csv, max_accounts=args.max_accounts)

    print(f"\n✓ Processed {len(results)} accounts with results")
