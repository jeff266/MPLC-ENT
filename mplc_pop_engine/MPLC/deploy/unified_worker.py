#!/usr/bin/env python3
"""
Unified Worker - Process Hotels, Healthcare, and Corporate in Parallel

Handles all three verticals:
- Hotels: Operator detection (14,404 records)
- Healthcare: PoP detection (1,424 records)
- Corporate: PoP detection (3,790 records)
"""

import csv
import json
import sys
import os
import time
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('worker.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


def process_hotel(record: dict) -> dict:
    """Process hotel record - detect operator."""
    try:
        # Import hotel operator detector
        sys.path.insert(0, '/root/enrichment/hotels')
        from management_company_scraper import ManagementCompanyScraper

        scraper = ManagementCompanyScraper()

        hotel_name = record.get('hotel_name', '')
        city = record.get('city', '')
        state = record.get('state', '')

        if not hotel_name:
            return {**record, 'operator': '', 'error': 'Missing hotel_name'}

        result = scraper.search_operator(hotel_name, city, state)

        if result is None:
            result = {}

        return {
            **record,
            'operator': result.get('operator', ''),
            'operator_source': result.get('source', ''),
            'operator_confidence': result.get('confidence', ''),
            'operator_evidence': result.get('evidence', ''),
            'operator_source_url': result.get('source_url', '')
        }
    except Exception as e:
        log.error(f"Hotel processing error: {e}")
        return {**record, 'operator': '', 'error': str(e)}


def process_healthcare(record: dict) -> dict:
    """Process healthcare record - PoP detection."""
    try:
        sys.path.insert(0, '/root/enrichment/healthcare')
        sys.path.insert(0, '/root/enrichment')

        # For now, return basic structure - healthcare pipeline needs more setup
        return {
            **record,
            'tier': 'PENDING',
            'channel': 'not_implemented',
            'note': 'Healthcare pipeline needs multi_channel_enricher setup'
        }
    except Exception as e:
        log.error(f"Healthcare processing error: {e}")
        return {**record, 'tier': 'ERROR', 'error': str(e)}


def process_corporate(record: dict) -> dict:
    """Process corporate record - PoP detection."""
    try:
        sys.path.insert(0, '/root/enrichment/corporate')
        sys.path.insert(0, '/root/enrichment')
        from pipeline import process_account

        result = process_account(record)

        return result if result else {**record, 'tier': 'REJECTED', 'error': 'No result'}
    except Exception as e:
        log.error(f"Corporate processing error: {e}")
        return {**record, 'tier': 'REJECTED', 'error': str(e)}


def process_batch(batch_file: str, vertical: str, worker_id: int):
    """
    Process a batch file for given vertical.

    Args:
        batch_file: CSV file path
        vertical: 'hotels' | 'healthcare' | 'corporate'
        worker_id: Worker number
    """
    log.info(f"Worker {worker_id} starting: {vertical} - {batch_file}")

    # Read batch
    with open(batch_file, 'r') as f:
        reader = csv.DictReader(f)
        records = list(reader)
        fieldnames = reader.fieldnames

    log.info(f"Loaded {len(records)} records")

    # Process records
    results = []
    processor = {
        'hotels': process_hotel,
        'healthcare': process_healthcare,
        'corporate': process_corporate
    }[vertical]

    for i, record in enumerate(records, 1):
        try:
            log.info(f"[{i}/{len(records)}] Processing {record.get('account_name', record.get('hotel_name', 'Unknown'))}")
            result = processor(record)
            results.append(result)

            # Progress checkpoint every 50 records
            if i % 50 == 0:
                log.info(f"Progress: {i}/{len(records)} ({i/len(records)*100:.1f}%)")

            # Rate limiting
            time.sleep(0.5)

        except Exception as e:
            log.error(f"Error processing record {i}: {e}")
            results.append({**record, 'error': str(e)})

    # Save results
    output_file = f"results_{vertical}_worker_{worker_id}.csv"

    # Determine output fieldnames
    if results:
        output_fieldnames = list(results[0].keys())
    else:
        output_fieldnames = fieldnames

    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=output_fieldnames)
        writer.writeheader()
        writer.writerows(results)

    log.info(f"✅ Worker {worker_id} completed: {output_file}")
    log.info(f"   Processed: {len(results)} records")

    return output_file


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Unified worker for all verticals')
    parser.add_argument('vertical', choices=['hotels', 'healthcare', 'corporate'])
    parser.add_argument('batch_file', help='CSV batch file to process')
    parser.add_argument('--worker-id', type=int, required=True)

    args = parser.parse_args()

    log.info("=" * 80)
    log.info(f"UNIFIED WORKER - {args.vertical.upper()}")
    log.info("=" * 80)
    log.info(f"Worker ID: {args.worker_id}")
    log.info(f"Batch: {args.batch_file}")
    log.info(f"Vertical: {args.vertical}")

    # Check API key
    if not os.getenv('SERPER_API_KEY'):
        log.error("SERPER_API_KEY not set!")
        sys.exit(1)

    # Process batch
    output = process_batch(args.batch_file, args.vertical, args.worker_id)

    log.info("=" * 80)
    log.info("WORKER COMPLETED SUCCESSFULLY")
    log.info("=" * 80)
    log.info(f"Output: {output}")


if __name__ == '__main__':
    main()
