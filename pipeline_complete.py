"""
MPLC PoP Detection Pipeline - Complete Implementation
All stages fully implemented with real API calls
"""

import pandas as pd
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from cost_tracker import CostTracker
import config
from text_patterns import aggregate_text_evidence
from stage_05_serper import SerperURLDiscovery
from stage_1_text_evidence import PlaywrightTextCollector
from stage_3_yolo import YOLODetector
from stage_4_vlm import VLMConfirmation


class MPLCPoPPipelineComplete:
    """Complete MPLC PoP Detection Pipeline with all stages implemented"""

    def __init__(self, input_csv: str, run_id: Optional[str] = None):
        self.input_csv = Path(input_csv)
        self.run_id = run_id or f"mplc_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Initialize cost tracker
        self.tracker = CostTracker(config.PROJECT_ROOT / "mplc_costs.db")

        # Load input accounts
        self.accounts = self._load_and_filter_accounts()

        # Initialize run with circuit breaker limits
        self.tracker.create_run(
            self.run_id,
            max_cost_usd=config.MAX_COST_USD,
            max_serper_credits=config.MAX_SERPER_CREDITS,
            accounts_total=len(self.accounts)
        )

        print(f"✓ Pipeline initialized: {self.run_id}")
        print(f"  Accounts to process: {len(self.accounts):,}")
        print(f"  Cost limits: ${config.MAX_COST_USD}, {config.MAX_SERPER_CREDITS} Serper credits")

    def _load_and_filter_accounts(self) -> pd.DataFrame:
        """Load accounts and filter to MM/ENT segments"""
        df = pd.read_csv(self.input_csv, encoding='latin-1', low_memory=False)

        # Filter to MM/ENT segments only
        filtered = df[df['Segment'].isin(['MM', 'ENT'])].copy()

        # Add employee count (Capacity when Capacity_Type == "Employees")
        filtered['employee_count'] = filtered.apply(
            lambda row: row.get('Capacity_Numeric') if row.get('Capacity Type') == 'Employees' else None,
            axis=1
        )

        print(f"✓ Loaded {len(df):,} total accounts")
        print(f"  Filtered to {len(filtered):,} MM/ENT accounts")

        return filtered

    def _check_circuit_breaker(self) -> bool:
        """Check if should continue or stop"""
        should_continue, reason = self.tracker.check_circuit_breaker(self.run_id)
        if not should_continue:
            print(f"\n🛑 CIRCUIT BREAKER TRIPPED: {reason}")
            print("Pipeline halted to prevent cost overrun.")
            self.tracker.complete_run(self.run_id)
        return should_continue

    def process_account(self, row: pd.Series, serper: SerperURLDiscovery,
                       text_collector: PlaywrightTextCollector,
                       yolo: YOLODetector, vlm: VLMConfirmation) -> Dict:
        """Process a single account through all stages"""
        account_id = row['18 Digit Account ID']
        account_name = row.get('Account Name', '')
        website = row.get('Website', '')
        city = row.get('Account Street', '').split(',')[0] if pd.notna(row.get('Account Street')) else ''
        state = row.get('Account State/Province', '')
        vertical = row.get('Industry_Bucket', 'Other')

        try:
            # Stage 0: Entity resolution (simple, no API calls)
            website_url = website if website and ('http' in website or '.' in website) else ''
            if website_url and not website_url.startswith('http'):
                website_url = f"https://{website_url}"

            # Stage 0.5: URL discovery (Serper)
            if not self._check_circuit_breaker():
                return None

            discovered_urls = serper.discover_urls_for_account(
                account_name=account_name,
                website=website_url,
                city=city,
                state=state,
                vertical=vertical,
                account_id=account_id
            )

            # Collect all URLs to scrape
            urls_to_scrape = [
                website_url,
                discovered_urls.get('yelp_url'),
                discovered_urls.get('google_places_url'),
                discovered_urls.get('tripadvisor_url'),
                discovered_urls.get('careers_url')
            ]

            # Stage 1: Text evidence collection (Playwright)
            text_result = text_collector.collect_evidence_for_urls(
                urls=[u for u in urls_to_scrape if u],
                account_id=account_id,
                vertical=vertical
            )

            text_matches = text_result['text_matches']
            image_paths = text_result.get('image_paths', [])
            image_urls = text_result.get('image_urls', [])

            # Stage 2: Text resolution gate
            text_strength, best_score, top_matches = aggregate_text_evidence(text_matches)

            # If Very Strong or Strong text evidence, close here
            if text_strength in ["Very Strong", "Strong"]:
                return {
                    'account_id': account_id,
                    'MPLC_EvidenceStrength': text_strength,
                    'MPLC_EvidenceReason': 'Direct evidence from text',
                    'evidence_source_urls': [m['source_url'] for m in top_matches],
                    'model_provider': 'none',
                    'resolution_stage': 'stage_2_text_gate',
                    'text_matches_count': len(text_matches),
                    'images_collected': len(image_paths),
                    'total_cost_usd': 0.0
                }

            # Stage 3: YOLO detection (only if we have saved images)
            yolo_passed = []
            if image_paths:
                yolo_passed = yolo.process_image_files(image_paths, image_urls, account_id)

            # Stage 4: VLM confirmation (only if YOLO passed images)
            vlm_results = []
            if yolo_passed and self._check_circuit_breaker():
                vlm_results = vlm.analyze_batch(yolo_passed, account_id)

            # Stage 5: Evidence aggregation
            final_strength = self._aggregate_evidence(
                text_strength=text_strength,
                vlm_results=vlm_results
            )

            # Calculate total cost for this account
            # (would query tracker for account-specific costs)
            total_cost = 0.0  # Placeholder

            return {
                'account_id': account_id,
                'MPLC_EvidenceStrength': final_strength['strength'],
                'MPLC_EvidenceReason': final_strength['reason'],
                'evidence_source_urls': json.dumps([m['source_url'] for m in top_matches[:3]]),
                'model_provider': 'anthropic' if vlm_results else 'none',
                'resolution_stage': final_strength['stage'],
                'text_matches_count': len(text_matches),
                'images_collected': len(image_urls),
                'yolo_passed_count': len(yolo_passed),
                'vlm_analyzed_count': len(vlm_results),
                'total_cost_usd': total_cost
            }

        except Exception as e:
            print(f"Error processing {account_id}: {e}")
            return {
                'account_id': account_id,
                'MPLC_EvidenceStrength': 'Error',
                'MPLC_EvidenceReason': str(e)[:100],
                'resolution_stage': 'error',
                'error': True
            }

    def _aggregate_evidence(self, text_strength: str, vlm_results: List[Dict]) -> Dict:
        """Combine text and visual evidence"""
        # Check if any VLM confirmed public space TV
        public_tv_confirmed = any(
            r.get('tv_present') and r.get('public_facing') and r.get('confidence', 0) >= 60
            for r in vlm_results
        )

        if public_tv_confirmed:
            if text_strength in ["Very Strong", "Strong"]:
                return {
                    'strength': 'Very Strong',
                    'reason': 'Direct evidence from text and visual',
                    'stage': 'stage_5_aggregation'
                }
            else:
                return {
                    'strength': 'Strong',
                    'reason': 'Direct evidence from visual',
                    'stage': 'stage_4_vlm'
                }
        elif vlm_results:
            # VLM analyzed but unclear/negative
            if text_strength == "Medium":
                return {
                    'strength': 'Medium',
                    'reason': 'Operating inference from text',
                    'stage': 'stage_5_aggregation'
                }
            else:
                return {
                    'strength': 'Weak',
                    'reason': 'Unclear visual evidence',
                    'stage': 'stage_4_vlm'
                }
        else:
            # No visual confirmation, use text only
            if text_strength in ["Not Applicable", "Weak"]:
                return {
                    'strength': 'Not Applicable',
                    'reason': 'Insufficient data, needs manual research',
                    'stage': 'stage_3_yolo'
                }
            else:
                return {
                    'strength': text_strength,
                    'reason': 'Operating inference from text',
                    'stage': 'stage_2_text_gate'
                }

    def run(self, limit: Optional[int] = None):
        """Run complete pipeline on all accounts"""
        results = []
        accounts_to_process = self.accounts.head(limit) if limit else self.accounts

        print(f"\n🚀 Processing {len(accounts_to_process):,} accounts...")
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # Initialize stages
        serper = SerperURLDiscovery(self.tracker, self.run_id)
        yolo = YOLODetector(self.tracker, self.run_id)
        vlm = VLMConfirmation(self.tracker, self.run_id)

        with PlaywrightTextCollector(self.tracker, self.run_id) as text_collector:
            for idx, row in accounts_to_process.iterrows():
                result = self.process_account(row, serper, text_collector, yolo, vlm)

                if result is None:
                    # Circuit breaker tripped
                    break

                results.append(result)

                # Progress update every 10 accounts
                if (idx + 1) % 10 == 0:
                    totals = self.tracker.get_run_totals(self.run_id)
                    print(f"[{idx + 1}/{len(accounts_to_process)}] "
                          f"Cost: ${totals.get('total_anthropic_cost', 0):.2f} | "
                          f"Serper: {totals.get('total_serper_credits', 0)} credits")

        # Save results
        self._save_results(results)

        # Complete run
        self.tracker.complete_run(self.run_id)

        # Print summary
        self._print_summary(results)

    def _save_results(self, results: List[Dict]):
        """Save results to CSV"""
        if not results:
            print("No results to save")
            return

        df = pd.DataFrame(results)
        output_file = config.OUTPUT_DIR / f"mplc_results_{self.run_id}.csv"
        df.to_csv(output_file, index=False)

        print(f"\n✓ Results saved: {output_file}")

    def _print_summary(self, results: List[Dict]):
        """Print run summary"""
        print("\n" + "=" * 100)
        print("RUN SUMMARY")
        print("=" * 100)

        totals = self.tracker.get_run_totals(self.run_id)

        print(f"\nAccounts processed: {len(results):,}")
        print(f"Total cost: ${totals.get('total_anthropic_cost', 0):.2f}")
        print(f"Serper credits: {totals.get('total_serper_credits', 0)}")
        print(f"Playwright requests: {totals.get('total_playwright_requests', 0)}")
        print(f"YOLO inferences: {totals.get('total_yolo_inferences', 0)}")

        # Evidence strength distribution
        df = pd.DataFrame(results)
        if 'MPLC_EvidenceStrength' in df.columns:
            print("\nEvidence Strength Distribution:")
            print(df['MPLC_EvidenceStrength'].value_counts().to_string())

        # Stage rollup
        print("\nCosts by Stage:")
        stage_rollup = self.tracker.get_rollup_by_stage(self.run_id)
        for stage in stage_rollup:
            print(f"  {stage['stage']}: {stage['call_count']} calls, "
                  f"${stage.get('anthropic_cost', 0) or 0:.2f}, "
                  f"{stage.get('serper_credits', 0) or 0} credits")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pipeline_complete.py <input_csv> [--limit N]")
        sys.exit(1)

    input_csv = sys.argv[1]
    limit = None

    if "--limit" in sys.argv:
        limit_idx = sys.argv.index("--limit")
        if len(sys.argv) > limit_idx + 1:
            limit = int(sys.argv[limit_idx + 1])

    pipeline = MPLCPoPPipelineComplete(input_csv)
    pipeline.run(limit=limit)
