"""
MPLC PoP Detection Pipeline Orchestrator

Runs multi-stage detection with cost tracking and circuit breaker.
"""

import pandas as pd
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import hashlib

from cost_tracker import CostTracker
import config
from text_patterns import find_text_evidence, aggregate_text_evidence

class MPLCPoPPipeline:
    """Main pipeline orchestrator"""
    
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
        
        print(f"Pipeline initialized: {self.run_id}")
        print(f"Accounts to process: {len(self.accounts)}")
        print(f"Cost limits: ${config.MAX_COST_USD}, {config.MAX_SERPER_CREDITS} Serper credits")
    
    def _load_and_filter_accounts(self) -> pd.DataFrame:
        """Load accounts and filter to MM/ENT segments"""
        df = pd.read_csv(self.input_csv, encoding='latin-1', low_memory=False)
        
        # Filter to MM/ENT segments only (exclude SMB)
        filtered = df[df['Segment'].isin(['MM', 'ENT'])].copy()
        
        # Add employee count column (Capacity when Capacity_Type == "Employees")
        filtered['employee_count'] = filtered.apply(
            lambda row: row['Capacity_Numeric'] if row.get('Capacity Type') == 'Employees' else None,
            axis=1
        )
        
        print(f"Loaded {len(df):,} total accounts")
        print(f"Filtered to {len(filtered):,} MM/ENT accounts")
        
        return filtered
    
    def _check_circuit_breaker(self) -> bool:
        """Check if should continue or stop"""
        should_continue, reason = self.tracker.check_circuit_breaker(self.run_id)
        if not should_continue:
            print(f"\n🛑 CIRCUIT BREAKER TRIPPED: {reason}")
            print("Pipeline halted to prevent cost overrun.")
            self.tracker.complete_run(self.run_id)
        return should_continue
    
    def _get_cache_key(self, account_id: str, stage: str, content: str = "") -> str:
        """Generate cache key for an API call"""
        key_data = f"{account_id}:{stage}:{content}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def stage_0_entity_resolution(self, row: pd.Series) -> Dict:
        """
        Stage 0: Verify business identity and website
        Returns: {website_url, confidence, method}
        """
        account_id = row['18 Digit Account ID']
        account_name = row['Account Name']
        website = row.get('Website', '').strip()
        
        # If website exists and looks valid, use it
        if website and ('http://' in website or 'https://' in website or '.' in website):
            return {
                "website_url": website if website.startswith('http') else f"https://{website}",
                "confidence": "high",
                "method": "direct"
            }
        
        # Otherwise, would use Serper to find website
        # For now, return blank (Stage 0.5 will handle discovery)
        return {
            "website_url": "",
            "confidence": "none",
            "method": "none"
        }
    
    def stage_05_url_discovery(self, row: pd.Series, entity_result: Dict) -> Dict:
        """
        Stage 0.5: Discover URLs via Serper (Yelp, Google Places, etc.)
        IMPORTANT: This is the ONLY stage that uses Serper
        """
        # STUB: Full implementation would call Serper API here
        # For now, return empty results
        # This stage would:
        # 1. Log Serper call BEFORE making it
        # 2. Check circuit breaker BEFORE each call
        # 3. Route queries based on vertical (config.VERTICAL_URL_STRATEGY)
        
        return {
            "yelp_url": "",
            "google_places_url": "",
            "careers_url": "",
            "tripadvisor_url": "",
            "serper_credits_used": 0
        }
    
    def stage_1_text_evidence(self, row: pd.Series, urls: Dict) -> List[Dict]:
        """
        Stage 1: Collect text evidence from discovered URLs
        Uses Playwright to scrape pages
        """
        # STUB: Full implementation would use Playwright here
        # For now, return empty results
        # This stage would:
        # 1. Use Playwright with stealth plugin
        # 2. Route by vertical (customer-facing vs employee-facing sites)
        # 3. Extract text and find pattern matches using text_patterns module
        # 4. Collect image URLs for Stage 3
        
        return []
    
    def stage_2_text_resolution_gate(self, text_matches: List[Dict]) -> tuple[str, bool]:
        """
        Stage 2: Check if text evidence is strong enough to close
        Returns: (evidence_strength, should_continue_to_visual)
        """
        if not text_matches:
            return "Not Applicable", True  # No text, proceed to visual
        
        strength, score, top_matches = aggregate_text_evidence(text_matches)
        
        # If Very Strong or Strong, we can close here
        if strength in ["Very Strong", "Strong"]:
            return strength, False  # Don't need visual confirmation
        
        # Medium or Weak - proceed to visual if we have images
        return strength, True
    
    def stage_3_yolo_detection(self, image_urls: List[str]) -> List[Dict]:
        """
        Stage 3: Free object detection with YOLO
        Returns list of images that passed (have TV + context)
        """
        # STUB: Full implementation would use Ultralytics YOLO here
        # For now, return empty results
        # This stage would:
        # 1. Download images
        # 2. Run YOLO inference (local, free)
        # 3. Filter to images with TV + supportive context
        # 4. Exclude desk/monitor contexts
        # 5. Log inferences to cost tracker (free but tracked)
        
        return []
    
    def stage_4_vlm_confirmation(self, account_id: str, yolo_results: List[Dict]) -> List[Dict]:
        """
        Stage 4: VLM confirmation with Anthropic (PAID - minimize volume)
        Only for images that passed Stage 3
        """
        # STUB: Full implementation would call Anthropic Vision API here
        # This stage would:
        # 1. Check circuit breaker BEFORE each call
        # 2. Log Anthropic call BEFORE using result
        # 3. Use structured prompt for public/shared space detection
        # 4. Return JSON with tv_present, room_type, public_facing, confidence
        
        return []
    
    def stage_5_evidence_aggregation(self, text_strength: str, visual_results: List[Dict]) -> Dict:
        """
        Stage 5: Combine text and visual evidence into final assessment
        """
        # Combine evidence from text and visual
        # Map to MPLC_EvidenceStrength scale
        
        if not visual_results and text_strength in ["Not Applicable", "Weak"]:
            return {
                "MPLC_EvidenceStrength": "Not Applicable",
                "MPLC_EvidenceReason": "Insufficient data, needs manual research",
                "evidence_source_urls": [],
                "resolution_stage": "stage_2_text_gate"
            }
        
        # If visual confirmed
        if visual_results and any(v.get('public_facing') for v in visual_results):
            if text_strength in ["Very Strong", "Strong"]:
                strength = "Very Strong"
                reason = "Direct evidence from text and visual"
            else:
                strength = "Strong"
                reason = "Direct evidence from visual confirmation"
        else:
            strength = text_strength
            reason = "Direct evidence" if strength in ["Very Strong", "Strong"] else "Operating inference"
        
        return {
            "MPLC_EvidenceStrength": strength,
            "MPLC_EvidenceReason": reason,
            "evidence_source_urls": [],
            "resolution_stage": "stage_5_aggregation"
        }
    
    def process_account(self, row: pd.Series) -> Dict:
        """Process a single account through all stages"""
        account_id = row['18 Digit Account ID']
        
        try:
            # Stage 0: Entity resolution
            entity = self.stage_0_entity_resolution(row)
            
            # Stage 0.5: URL discovery
            if not self._check_circuit_breaker():
                return None
            
            urls = self.stage_05_url_discovery(row, entity)
            
            # Stage 1: Text evidence
            text_matches = self.stage_1_text_evidence(row, urls)
            
            # Stage 2: Text resolution gate
            text_strength, proceed_to_visual = self.stage_2_text_resolution_gate(text_matches)
            
            if not proceed_to_visual:
                # Close here with text evidence
                return {
                    "account_id": account_id,
                    "MPLC_EvidenceStrength": text_strength,
                    "MPLC_EvidenceReason": "Direct evidence",
                    "evidence_source_urls": [m['source_url'] for m in text_matches[:3]],
                    "model_provider": "none",
                    "resolution_stage": "stage_2_text_gate",
                    "total_cost_usd": 0.0
                }
            
            # Stage 3: YOLO detection (if we have images)
            image_urls = []  # Would extract from Stage 1
            yolo_results = self.stage_3_yolo_detection(image_urls)
            
            # Stage 4: VLM confirmation
            if yolo_results and self._check_circuit_breaker():
                visual_results = self.stage_4_vlm_confirmation(account_id, yolo_results)
            else:
                visual_results = []
            
            # Stage 5: Aggregation
            final = self.stage_5_evidence_aggregation(text_strength, visual_results)
            final["account_id"] = account_id
            final["model_provider"] = "anthropic" if visual_results else "none"
            
            # Get cost for this account
            # (would sum from tracker)
            final["total_cost_usd"] = 0.0
            
            return final
            
        except Exception as e:
            print(f"Error processing {account_id}: {e}")
            return {
                "account_id": account_id,
                "MPLC_EvidenceStrength": "Error",
                "MPLC_EvidenceReason": str(e)[:100],
                "error": True
            }
    
    def run(self, limit: Optional[int] = None):
        """Run pipeline on all accounts"""
        results = []
        accounts_to_process = self.accounts.head(limit) if limit else self.accounts
        
        print(f"\nProcessing {len(accounts_to_process)} accounts...")
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        for idx, row in accounts_to_process.iterrows():
            result = self.process_account(row)
            
            if result is None:
                # Circuit breaker tripped
                break
            
            results.append(result)
            
            if (idx + 1) % 10 == 0:
                totals = self.tracker.get_run_totals(self.run_id)
                print(f"[{idx + 1}/{len(accounts_to_process)}] Processed | "
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
        
        print(f"\nAccounts processed: {len(results)}")
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
        print("Usage: python pipeline.py <input_csv> [--limit N]")
        sys.exit(1)
    
    input_csv = sys.argv[1]
    limit = None
    
    if "--limit" in sys.argv:
        limit_idx = sys.argv.index("--limit")
        if len(sys.argv) > limit_idx + 1:
            limit = int(sys.argv[limit_idx + 1])
    
    pipeline = MPLCPoPPipeline(input_csv)
    pipeline.run(limit=limit)
