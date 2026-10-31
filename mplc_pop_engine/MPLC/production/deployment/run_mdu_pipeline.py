#!/usr/bin/env python3
"""
MDU Pipeline Orchestration - Single Command Entry Point

Chains all MDU pipeline stages with automatic file hand-offs and validation.
No more manually tracking which CSV is current or typing file paths by hand.

STATUS: STRUCTURE COMPLETE, INTEGRATION IN PROGRESS

Current stage scripts need CLI updates to accept --input and --output arguments:
- mdu_proper_discovery_track_a_b.py (needs --states, --output)
- crossreference_track_a_b_operators_corrected.py (needs --input, --output-netnew, --output-existing, --salesforce)
- scrape_track_a_b_v4_final.py (needs --input, --output)

Stage 4 (YOLO/VLM) needs to be pointed to the correct enricher entry point.

Usage:
    python3 run_mdu_pipeline.py --states VA,MD,DC,WA,TX,CO,AZ --run-id 2026-10-30-regional

Output Structure:
    production/runs/<run-id>/
        01_discovery_raw.csv                    # Raw operators from Track A+B
        02_discovery_netnew.csv                 # After Salesforce filter (net-new only)
        02_discovery_existing_customers.csv     # Existing customers (excluded)
        03_properties_scraped.csv               # Property URLs from operator websites
        04_evidence_raw.csv                     # PoP evidence from YOLO/VLM
        05_handoff_HANDOFF.csv                  # Final verified handoff
        05_handoff_FLAGGED.csv                  # Needs manual review
        05_handoff_DUPLICATES.csv               # Removed duplicates
        05_handoff_SUMMARY.txt                  # Verification report
        run_log.txt                             # Timestamped stage log

Stop Conditions:
- Any stage produces zero output
- Salesforce accounts file missing
- >50% operators fail scraping
"""

import argparse
import subprocess
import sys
import csv
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple


class MDUPipelineOrchestrator:
    """Orchestrate the complete MDU pipeline from discovery to handoff."""

    def __init__(self, states: List[str], run_id: str):
        self.states = states
        self.run_id = run_id
        self.base_dir = Path(__file__).parent.parent
        self.run_dir = self.base_dir / "runs" / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.log_file = self.run_dir / "run_log.txt"
        self.stage_outputs = {}
        self.stats = {}

        self._log_header()

    def _log(self, message: str):
        """Log to both console and run_log.txt with timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        print(log_line)

        with open(self.log_file, 'a') as f:
            f.write(log_line + "\n")

    def _log_header(self):
        """Write run header to log."""
        self._log("=" * 80)
        self._log("MDU PIPELINE ORCHESTRATION")
        self._log("=" * 80)
        self._log(f"Run ID: {self.run_id}")
        self._log(f"States: {', '.join(self.states)}")
        self._log(f"Output directory: {self.run_dir}")
        self._log("")

    def _count_csv_rows(self, csv_file: Path) -> int:
        """Count rows in CSV (excluding header)."""
        if not csv_file.exists():
            return 0

        with open(csv_file, 'r') as f:
            reader = csv.reader(f)
            next(reader, None)  # Skip header
            return sum(1 for _ in reader)

    def _run_command(self, cmd: List[str], stage_name: str) -> Tuple[bool, str]:
        """Run a command and capture output."""
        self._log(f"Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                timeout=7200  # 2 hour timeout per stage
            )

            if result.returncode != 0:
                error_msg = f"Stage failed with exit code {result.returncode}\n{result.stderr}"
                self._log(f"❌ ERROR: {error_msg}")
                return False, error_msg

            return True, result.stdout

        except subprocess.TimeoutExpired:
            error_msg = f"Stage timed out after 2 hours"
            self._log(f"❌ ERROR: {error_msg}")
            return False, error_msg

        except Exception as e:
            error_msg = f"Stage failed: {str(e)}"
            self._log(f"❌ ERROR: {error_msg}")
            return False, error_msg

    def stage_1_discovery(self) -> bool:
        """Stage 1: Operator Discovery (Track A + Track B)."""
        self._log("")
        self._log("=" * 80)
        self._log("STAGE 1: OPERATOR DISCOVERY")
        self._log("=" * 80)

        output_file = self.run_dir / "01_discovery_raw.csv"

        # Build command for discovery script
        cmd = [
            "python3",
            str(self.base_dir / "deployment/mdu_proper_discovery_track_a_b.py"),
            "--states", ",".join(self.states),
            "--output", str(output_file)
        ]

        success, output = self._run_command(cmd, "discovery")

        if not success:
            return False

        # Validate output
        row_count = self._count_csv_rows(output_file)
        self._log(f"✓ Discovered {row_count} operators")

        if row_count == 0:
            self._log("❌ STOP: Discovery produced zero operators")
            return False

        self.stage_outputs['discovery'] = output_file
        self.stats['operators_discovered'] = row_count

        return True

    def stage_2_salesforce_crossreference(self) -> bool:
        """Stage 2: Cross-reference against Salesforce existing customers."""
        self._log("")
        self._log("=" * 80)
        self._log("STAGE 2: SALESFORCE CROSS-REFERENCE")
        self._log("=" * 80)

        # Check for Salesforce accounts file (SOURCE OF TRUTH, not prior run output)
        sf_file = self.base_dir.parent / "data/salesforce/unique_accounts_2026-10-22.csv"

        if not sf_file.exists():
            self._log(f"❌ STOP: Salesforce accounts file not found: {sf_file}")
            self._log("This file is required for existing customer filtering.")
            return False

        input_file = self.stage_outputs['discovery']
        output_netnew = self.run_dir / "02_discovery_netnew.csv"
        output_existing = self.run_dir / "02_discovery_existing_customers.csv"

        cmd = [
            "python3",
            str(self.base_dir / "deployment/crossreference_track_a_b_operators_corrected.py"),
            "--input", str(input_file),
            "--salesforce", str(sf_file),
            "--output-netnew", str(output_netnew),
            "--output-existing", str(output_existing)
        ]

        success, output = self._run_command(cmd, "salesforce_crossreference")

        if not success:
            return False

        # Validate outputs
        netnew_count = self._count_csv_rows(output_netnew)
        existing_count = self._count_csv_rows(output_existing)

        self._log(f"✓ Net-new operators: {netnew_count}")
        self._log(f"✓ Existing customers excluded: {existing_count}")

        if netnew_count == 0:
            self._log("❌ STOP: All operators are existing customers (zero net-new)")
            return False

        self.stage_outputs['netnew'] = output_netnew
        self.stage_outputs['existing_customers'] = output_existing
        self.stats['operators_netnew'] = netnew_count
        self.stats['operators_existing'] = existing_count

        return True

    def stage_3_property_scraping(self) -> bool:
        """Stage 3: Scrape property URLs from operator websites."""
        self._log("")
        self._log("=" * 80)
        self._log("STAGE 3: PROPERTY URL SCRAPING")
        self._log("=" * 80)

        input_file = self.stage_outputs['netnew']
        output_file = self.run_dir / "03_properties_scraped.csv"

        cmd = [
            "python3",
            str(self.base_dir / "deployment/scrape_track_a_b_v4_final.py"),
            "--input", str(input_file),
            "--output", str(output_file)
        ]

        success, output = self._run_command(cmd, "property_scraping")

        if not success:
            return False

        # Validate output
        property_count = self._count_csv_rows(output_file)
        self._log(f"✓ Properties scraped: {property_count}")

        if property_count == 0:
            self._log("❌ STOP: Scraping produced zero properties")
            return False

        # Check scraping success rate
        operators_attempted = self.stats['operators_netnew']

        # Count unique operators in scraped properties
        unique_operators = set()
        with open(output_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                unique_operators.add(row.get('operator', ''))

        operators_succeeded = len(unique_operators)
        success_rate = operators_succeeded / operators_attempted if operators_attempted > 0 else 0

        self._log(f"✓ Operators with properties: {operators_succeeded}/{operators_attempted} ({success_rate*100:.1f}%)")

        # Stop if >50% failure
        if success_rate < 0.5:
            self._log(f"❌ STOP: Scraping success rate too low ({success_rate*100:.1f}%)")
            self._log("This suggests an upstream list problem (generic operators, trade associations, etc.)")
            return False

        self.stage_outputs['properties'] = output_file
        self.stats['properties_scraped'] = property_count
        self.stats['operators_with_properties'] = operators_succeeded
        self.stats['scraping_success_rate'] = success_rate

        return True

    def stage_4_evidence_detection(self) -> bool:
        """Stage 4: YOLO + VLM evidence detection."""
        self._log("")
        self._log("=" * 80)
        self._log("STAGE 4: YOLO + VLM EVIDENCE DETECTION")
        self._log("=" * 80)

        input_file = self.stage_outputs['properties']
        output_file = self.run_dir / "04_evidence_raw.csv"

        # run_mdu_batch.py takes positional args: batch_file, num_workers
        # It outputs to mdu_results_<batch_file_stem>.csv
        cmd = [
            "python3",
            str(self.base_dir / "deployment/run_mdu_batch.py"),
            str(input_file),
            "5"  # 5 workers
        ]

        success, output = self._run_command(cmd, "evidence_detection")

        if not success:
            return False

        # Find and move the output file
        # run_mdu_batch.py creates mdu_results_<batch_file_stem>.csv
        expected_output = self.base_dir / "deployment" / f"mdu_results_{input_file.stem}.csv"

        if not expected_output.exists():
            self._log(f"❌ ERROR: Expected output file not found: {expected_output}")
            return False

        # Move to 04_evidence_raw.csv
        import shutil
        shutil.move(str(expected_output), str(output_file))

        # Validate output
        evidence_count = self._count_csv_rows(output_file)
        self._log(f"✓ Evidence rows: {evidence_count}")

        if evidence_count == 0:
            self._log("❌ STOP: Evidence detection produced zero rows")
            return False

        self.stage_outputs['evidence'] = output_file
        self.stats['evidence_count'] = evidence_count

        return True

    def stage_5_verification_handoff(self) -> bool:
        """Stage 5: Verification and handoff assembly."""
        self._log("")
        self._log("=" * 80)
        self._log("STAGE 5: VERIFICATION & HANDOFF ASSEMBLY")
        self._log("=" * 80)

        input_file = self.run_dir / "04_evidence_raw.csv"

        if not input_file.exists():
            self._log("⚠️  Evidence file not found - skipping verification")
            return True

        output_base = self.run_dir / "05_handoff"
        sf_file = self.base_dir / "deployment/mdu_track_a_b_existing_customers_excluded_corrected.csv"

        cmd = [
            "python3",
            str(self.base_dir / "tools/verify_and_assemble_handoff.py"),
            str(input_file),
            "--salesforce-list", str(sf_file),
            "--output", str(output_base)
        ]

        success, output = self._run_command(cmd, "verification_handoff")

        if not success:
            return False

        # Count outputs
        handoff_file = self.run_dir / "05_handoff_HANDOFF.csv"
        flagged_file = self.run_dir / "05_handoff_FLAGGED.csv"
        duplicates_file = self.run_dir / "05_handoff_DUPLICATES.csv"

        handoff_count = self._count_csv_rows(handoff_file)
        flagged_count = self._count_csv_rows(flagged_file)
        duplicates_count = self._count_csv_rows(duplicates_file)

        self._log(f"✓ Verified handoff: {handoff_count}")
        self._log(f"✓ Flagged for review: {flagged_count}")
        self._log(f"✓ Duplicates removed: {duplicates_count}")

        self.stats['handoff_count'] = handoff_count
        self.stats['flagged_count'] = flagged_count
        self.stats['duplicates_count'] = duplicates_count

        return True

    def _print_final_summary(self):
        """Print final summary block."""
        self._log("")
        self._log("=" * 80)
        self._log("PIPELINE COMPLETE - FINAL SUMMARY")
        self._log("=" * 80)
        self._log(f"Run ID: {self.run_id}")
        self._log(f"States: {', '.join(self.states)}")
        self._log("")
        self._log("STAGE RESULTS:")
        self._log(f"  Operators discovered: {self.stats.get('operators_discovered', 'N/A')}")
        self._log(f"  Net-new (after Salesforce): {self.stats.get('operators_netnew', 'N/A')}")
        self._log(f"  Existing customers excluded: {self.stats.get('operators_existing', 'N/A')}")
        self._log(f"  Properties scraped: {self.stats.get('properties_scraped', 'N/A')}")
        self._log(f"  Scraping success rate: {self.stats.get('scraping_success_rate', 0)*100:.1f}%")
        self._log(f"  Evidence rows: {self.stats.get('evidence_count', 'N/A')}")
        self._log(f"  Final handoff count: {self.stats.get('handoff_count', 'N/A')}")
        self._log(f"  Flagged for review: {self.stats.get('flagged_count', 'N/A')}")
        self._log(f"  Duplicates removed: {self.stats.get('duplicates_count', 'N/A')}")
        self._log(f"  Total cost: ${self.stats.get('total_cost', 0):.2f}")
        self._log("")
        self._log("OUTPUT FILES:")
        self._log(f"  Run directory: {self.run_dir}")
        self._log(f"  Summary: {self.run_dir / '05_handoff_SUMMARY.txt'}")
        self._log(f"  Handoff CSV: {self.run_dir / '05_handoff_HANDOFF.csv'}")
        self._log(f"  Run log: {self.log_file}")
        self._log("=" * 80)

    def run(self) -> bool:
        """Execute the complete pipeline."""
        stages = [
            ("Discovery", self.stage_1_discovery),
            ("Salesforce Cross-reference", self.stage_2_salesforce_crossreference),
            ("Property Scraping", self.stage_3_property_scraping),
            ("Evidence Detection", self.stage_4_evidence_detection),
            ("Verification & Handoff", self.stage_5_verification_handoff),
        ]

        for stage_name, stage_func in stages:
            try:
                success = stage_func()
                if not success:
                    self._log("")
                    self._log(f"❌ PIPELINE STOPPED AT: {stage_name}")
                    self._log(f"See {self.log_file} for details")
                    return False

            except Exception as e:
                self._log("")
                self._log(f"❌ UNEXPECTED ERROR IN {stage_name}: {str(e)}")
                return False

        self._print_final_summary()
        return True


def main():
    parser = argparse.ArgumentParser(
        description="MDU Pipeline Orchestration - Single command entry point",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Regional run across multiple states
  python3 run_mdu_pipeline.py --states VA,MD,DC,WA,TX,CO,AZ --run-id 2026-10-30-regional

  # Single state test run
  python3 run_mdu_pipeline.py --states TX --run-id 2026-10-30-texas-test

Output directory structure:
  production/runs/<run-id>/
    01_discovery_raw.csv
    02_discovery_netnew.csv
    02_discovery_existing_customers.csv
    03_properties_scraped.csv
    04_evidence_raw.csv
    05_handoff_HANDOFF.csv
    05_handoff_FLAGGED.csv
    05_handoff_DUPLICATES.csv
    05_handoff_SUMMARY.txt
    run_log.txt
        """
    )

    parser.add_argument(
        '--states',
        required=True,
        help="Comma-separated state codes (e.g., VA,MD,DC,WA,TX)"
    )

    parser.add_argument(
        '--run-id',
        required=True,
        help="Unique run identifier (e.g., 2026-10-30-regional)"
    )

    args = parser.parse_args()

    # Parse states
    states = [s.strip().upper() for s in args.states.split(',')]

    # Validate states
    valid_states = [
        'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
        'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
        'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
        'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
        'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
        'DC'
    ]

    invalid_states = [s for s in states if s not in valid_states]
    if invalid_states:
        print(f"❌ ERROR: Invalid state codes: {', '.join(invalid_states)}")
        sys.exit(1)

    # Run pipeline
    orchestrator = MDUPipelineOrchestrator(states, args.run_id)
    success = orchestrator.run()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
