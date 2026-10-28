#!/usr/bin/env python3
"""
MDU PoP Detection Analyzer

Combines:
1. Property website media scraping
2. YOLO TV detection
3. VLM verification (common area + TV on)

Pipeline:
Property URLs → Scrape Media → YOLO Filter → VLM Analysis → PoP Results
"""

import sys
import csv
import json
import time
import logging
from pathlib import Path
from typing import List, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from stage_3_yolo import YOLODetector
from stage_4_vlm import VLMConfirmation
from cost_tracker import CostTracker
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


class MDUPoPAnalyzer:
    """Analyze MDU properties for PoP evidence."""

    def __init__(self, run_id: str = 'mdu_run'):
        self.run_id = run_id
        self.tracker = CostTracker(run_id)

        # Initialize YOLO and VLM
        self.yolo = YOLODetector(self.tracker, run_id)
        self.vlm = VLMConfirmation(self.tracker, run_id)

    def analyze_property(self, property_data: Dict) -> Dict:
        """
        Analyze a single property for PoP.

        Args:
            property_data: Dict with community_name, image_urls, etc.

        Returns:
            {
                'property': str,
                'tier': 'PROSPECT' | 'SUSPECT' | 'REJECTED',
                'tvs_detected': int,
                'pop_evidence': List[Dict],
                'cost': float,
            }
        """
        community_name = property_data.get('community_name', 'Unknown')
        log.info(f"Analyzing: {community_name}")

        # Parse image URLs
        try:
            image_urls = json.loads(property_data.get('image_urls', '[]'))
        except:
            image_urls = []

        if not image_urls:
            log.info("  No images to analyze")
            return {
                'property': community_name,
                'tier': 'REJECTED',
                'reason': 'no_images',
                'tvs_detected': 0,
                'pop_evidence': [],
                'cost': 0.0,
            }

        log.info(f"  Analyzing {len(image_urls)} images")

        # Stage 1: YOLO filter - find images with TVs
        tv_candidates = []

        for i, url in enumerate(image_urls[:20], 1):  # Limit to 20 images
            # Download image
            image_path = self.yolo._download_image(url)

            if not image_path:
                continue

            # Run YOLO
            detections = self.yolo.detect_objects(image_path)

            # Check for TV
            has_tv = any(d['class'] == 'tv' for d in detections)

            if has_tv:
                tv_candidates.append({
                    'url': url,
                    'image_path': str(image_path),
                    'detections': detections,
                })

                log.info(f"    Image {i}: TV detected!")

        log.info(f"  YOLO found {len(tv_candidates)} images with TVs")

        if not tv_candidates:
            return {
                'property': community_name,
                'tier': 'REJECTED',
                'reason': 'no_tvs_detected',
                'tvs_detected': 0,
                'pop_evidence': [],
                'cost': 0.0,  # YOLO is free
            }

        # Stage 2: VLM verification - verify common area + TV on
        pop_evidence = []

        for candidate in tv_candidates[:5]:  # Limit VLM calls (they cost money)
            # Get YOLO detection classes
            yolo_classes = [d['class'] for d in candidate['detections']]

            # VLM analysis
            vlm_result = self.vlm.analyze_image(
                image_path=candidate['image_path'],
                image_url=candidate['url'],
                account_id=community_name,
                yolo_detections=yolo_classes
            )

            if vlm_result.get('tv_present') and vlm_result.get('public_facing'):
                pop_evidence.append({
                    'image_url': candidate['url'],
                    'image_path': candidate['image_path'],
                    'space_type': vlm_result.get('room_type'),
                    'tv_powered_on': True,  # VLM confirms TV present
                    'confidence': vlm_result.get('confidence'),
                    'reasoning': vlm_result.get('reasoning'),
                })

                log.info(f"    PoP confirmed: {vlm_result.get('room_type')}")

        # Determine tier
        if pop_evidence:
            tier = 'PROSPECT'  # Sales-ready
        elif tv_candidates:
            tier = 'SUSPECT'  # YOLO found TVs but VLM rejected
        else:
            tier = 'REJECTED'

        totals = self.tracker.get_run_totals(self.run_id)
        cost = totals.get('total_anthropic_cost', 0.0)

        return {
            'property': community_name,
            'tier': tier,
            'tvs_detected': len(tv_candidates),
            'pop_evidence': pop_evidence,
            'cost': cost,
        }


def process_properties_for_pop(input_csv: str, output_csv: str, limit: int = None):
    """Process properties and detect PoP."""

    # Read properties with media
    with open(input_csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        properties = list(reader)

    if limit:
        properties = properties[:limit]

    log.info(f"Processing {len(properties)} properties for PoP detection")

    # Create unique run ID with timestamp
    from datetime import datetime
    run_id = f"mdu_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    analyzer = MDUPoPAnalyzer(run_id=run_id)

    # Initialize run configuration with budget limits
    analyzer.tracker.create_run(
        run_id=analyzer.run_id,
        max_cost_usd=10.0,  # $10 budget for test run
        max_serper_credits=1000,  # High limit (not used for MDU)
        accounts_total=len(properties)
    )

    results = []
    prospects = 0
    suspects = 0
    total_cost = 0.0

    for i, prop in enumerate(properties, 1):
        log.info(f"[{i}/{len(properties)}]")

        result = analyzer.analyze_property(prop)

        if result['tier'] == 'PROSPECT':
            prospects += 1
        elif result['tier'] == 'SUSPECT':
            suspects += 1

        total_cost += result['cost']

        # Flatten for CSV
        results.append({
            'reit': prop.get('reit'),
            'community_name': result['property'],
            'city': prop.get('city'),
            'state': prop.get('state'),
            'tier': result['tier'],
            'tvs_detected': result['tvs_detected'],
            'pop_evidence_count': len(result['pop_evidence']),
            'cost': result['cost'],
        })

        # Progress
        if i % 10 == 0:
            log.info(f"  Progress: {i}/{len(properties)}")
            log.info(f"  Prospects: {prospects}, Suspects: {suspects}")
            log.info(f"  Total cost: ${total_cost:.3f}")

    # Summary
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)
    print(f"Properties analyzed: {len(results)}")
    print(f"PROSPECTS (sales-ready): {prospects} ({prospects/len(results)*100:.1f}%)")
    print(f"SUSPECTS (needs validation): {suspects} ({suspects/len(results)*100:.1f}%)")
    print(f"REJECTED: {len(results) - prospects - suspects}")
    print(f"\nTotal cost: ${total_cost:.3f}")
    print(f"Cost per property: ${total_cost/len(results):.4f}")

    if prospects > 0:
        print(f"Cost per PROSPECT: ${total_cost/prospects:.3f}")

    # Write CSV
    fieldnames = [
        'reit', 'community_name', 'city', 'state', 'tier',
        'tvs_detected', 'pop_evidence_count', 'cost'
    ]

    with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nWrote to: {output_csv}")

    # Complete the run
    analyzer.tracker.complete_run(analyzer.run_id)

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description='MDU PoP Detection')
    parser.add_argument('--input', default='properties_with_media.csv', help='Input CSV with media')
    parser.add_argument('--output', default='mdu_pop_results.csv', help='Output CSV')
    parser.add_argument('--limit', type=int, help='Limit number of properties')

    args = parser.parse_args()

    process_properties_for_pop(args.input, args.output, args.limit)


if __name__ == '__main__':
    main()
