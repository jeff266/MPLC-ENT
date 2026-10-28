#!/usr/bin/env python3
"""
Split All Verticals into Worker Batches

Splits work across 10 workers (5 per droplet):
- Hotels: 14,404 records → 1,440 per worker
- Healthcare: 1,424 records → 142 per worker
- Corporate: 3,790 records → 379 per worker
Total: 19,618 records → 1,962 per worker
"""

import csv
import argparse
from pathlib import Path

# Input files (absolute paths from MPLC root)
BASE_DIR = Path(__file__).parent.parent
HOTELS_FILE = BASE_DIR / "../verticals/hotels/output/hotel_franchisee_database_complete.csv"
HEALTHCARE_FILE = BASE_DIR / "output/runs/healthcare_accounts_filtered_2026-10-27.csv"
CORPORATE_FILE = BASE_DIR / "output/runs/corporate_accounts_to_process_2026-10-23.csv"


def split_csv(input_file: str, output_dir: str, num_workers: int, prefix: str):
    """Split CSV into N equal batches."""

    with open(input_file, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    print(f"\n{prefix.upper()}")
    print(f"  Input: {input_file}")
    print(f"  Total records: {len(rows)}")
    print(f"  Workers: {num_workers}")
    print(f"  Per worker: {len(rows) // num_workers}")

    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    # Split into batches
    batch_size = len(rows) // num_workers
    remainder = len(rows) % num_workers

    for i in range(num_workers):
        start = i * batch_size
        end = start + batch_size

        # Distribute remainder across first workers
        if i < remainder:
            start += i
            end += i + 1
        else:
            start += remainder
            end += remainder

        batch = rows[start:end]

        output_file = output_dir / f"batch_{prefix}_worker_{i}.csv"

        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(batch)

        print(f"    Worker {i}: {len(batch)} records → {output_file.name}")

    return len(rows)


def main():
    parser = argparse.ArgumentParser(description='Split all verticals into worker batches')
    parser.add_argument('--output-dir', default='batches', help='Output directory for batches')
    parser.add_argument('--num-workers', type=int, default=10, help='Number of workers')

    args = parser.parse_args()

    print("=" * 80)
    print("SPLITTING ALL VERTICALS")
    print("=" * 80)

    total_hotels = split_csv(HOTELS_FILE, args.output_dir, args.num_workers, 'hotels')
    total_healthcare = split_csv(HEALTHCARE_FILE, args.output_dir, args.num_workers, 'healthcare')
    total_corporate = split_csv(CORPORATE_FILE, args.output_dir, args.num_workers, 'corporate')

    print("\n" + "=" * 80)
    print("SPLIT COMPLETE")
    print("=" * 80)
    print(f"\nTotal records: {total_hotels + total_healthcare + total_corporate:,}")
    print(f"  Hotels: {total_hotels:,}")
    print(f"  Healthcare: {total_healthcare:,}")
    print(f"  Corporate: {total_corporate:,}")
    print(f"\nWorkers: {args.num_workers}")
    print(f"Batches created: {args.num_workers * 3} ({args.num_workers} per vertical)")
    print(f"\nOutput: {args.output_dir}/")


if __name__ == '__main__':
    main()
