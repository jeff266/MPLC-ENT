"""
Cost Tracking Database for MPLC PoP Detection Engine

Logs every external API call BEFORE the result is used.
Provides circuit breaker functionality to prevent cost overruns.
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, Optional, List
from pathlib import Path
from threading import Lock


class CostTracker:
    """
    Tracks costs and usage across all pipeline stages.
    Implements hard circuit breaker to prevent budget overruns.
    """

    def __init__(self, db_path: str = "mplc_costs.db"):
        self.db_path = Path(db_path)
        self.conn = None
        self._db_lock = Lock()  # Thread-safe database access
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with cost tracking schema"""
        # check_same_thread=False allows multi-threaded access
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        cursor = self.conn.cursor()

        # Main cost tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                source TEXT NOT NULL,

                -- Serper costs
                serper_credits INTEGER DEFAULT 0,
                serper_query TEXT,

                -- Anthropic costs
                anthropic_tokens_input INTEGER DEFAULT 0,
                anthropic_tokens_output INTEGER DEFAULT 0,
                anthropic_cost_usd REAL DEFAULT 0,
                anthropic_model TEXT,

                -- Other usage metrics
                playwright_requests INTEGER DEFAULT 0,
                yolo_inferences INTEGER DEFAULT 0,

                -- Metadata
                timestamp TEXT NOT NULL,
                result_status TEXT,
                result_summary TEXT,

                UNIQUE(account_id, stage, source, timestamp)
            )
        """)

        # Run configuration table (tracks circuit breaker limits)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS run_config (
                run_id TEXT PRIMARY KEY,
                max_cost_usd REAL NOT NULL,
                max_serper_credits INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                status TEXT DEFAULT 'running',
                accounts_processed INTEGER DEFAULT 0,
                accounts_total INTEGER
            )
        """)

        # Index for fast lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_account_stage
            ON api_calls(account_id, stage)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON api_calls(timestamp)
        """)

        self.conn.commit()

    def log_serper_call(self, account_id: str, stage: str, query: str,
                        credits_used: int, result_status: str = "success") -> int:
        """
        Log a Serper API call BEFORE using the result.
        Returns the log ID.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO api_calls (
                account_id, stage, source, serper_credits, serper_query,
                timestamp, result_status
            ) VALUES (?, ?, 'serper', ?, ?, ?, ?)
        """, (
            account_id, stage, credits_used, query,
            datetime.utcnow().isoformat(), result_status
        ))
        self.conn.commit()
        return cursor.lastrowid

    def log_anthropic_call(self, account_id: str, stage: str, model: str,
                          tokens_in: int, tokens_out: int,
                          result_status: str = "success") -> int:
        """
        Log an Anthropic API call BEFORE using the result.
        Calculates cost based on model pricing.
        Returns the log ID.
        """
        # Pricing as of Oct 2026 (adjust if needed)
        pricing = {
            "claude-sonnet-4-5": {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000},
            "claude-haiku-4": {"input": 0.80 / 1_000_000, "output": 4.00 / 1_000_000},
            "claude-3-5-sonnet": {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000},
        }

        model_key = "claude-haiku-4"  # Default to Haiku for cost control
        if "sonnet" in model.lower():
            model_key = "claude-sonnet-4-5"

        rates = pricing.get(model_key, pricing["claude-haiku-4"])
        cost_usd = (tokens_in * rates["input"]) + (tokens_out * rates["output"])

        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO api_calls (
                account_id, stage, source, anthropic_tokens_input,
                anthropic_tokens_output, anthropic_cost_usd, anthropic_model,
                timestamp, result_status
            ) VALUES (?, ?, 'anthropic', ?, ?, ?, ?, ?, ?)
        """, (
            account_id, stage, tokens_in, tokens_out, cost_usd, model,
            datetime.utcnow().isoformat(), result_status
        ))
        self.conn.commit()
        return cursor.lastrowid

    def log_playwright_request(self, account_id: str, stage: str,
                               url: str, requests_count: int = 1):
        """Log Playwright page requests (free, but track for monitoring)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO api_calls (
                account_id, stage, source, playwright_requests,
                timestamp, result_status, result_summary
            ) VALUES (?, ?, 'playwright', ?, ?, 'success', ?)
        """, (
            account_id, stage, requests_count,
            datetime.utcnow().isoformat(), url
        ))
        self.conn.commit()

    def log_yolo_inference(self, account_id: str, image_url: str,
                          detections: List[str]):
        """Log YOLO inference (free, but track for throughput)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO api_calls (
                account_id, stage, source, yolo_inferences,
                timestamp, result_status, result_summary
            ) VALUES (?, 'stage_3_yolo', 'yolo', 1, ?, 'success', ?)
        """, (
            account_id, datetime.utcnow().isoformat(),
            json.dumps({"image": image_url, "detections": detections})
        ))
        self.conn.commit()

    def log_api_call(self, account_id: str, stage: str, source: str,
                     cost_usd: float = 0.0, result_status: str = "success",
                     result_summary: str = "") -> int:
        """
        Log a generic API call with cost tracking (for Apify, Google Places, etc.)
        Returns the log ID.
        """
        with self._db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO api_calls (
                    account_id, stage, source, anthropic_cost_usd,
                    timestamp, result_status, result_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                account_id, stage, source, cost_usd,
                datetime.utcnow().isoformat(), result_status, result_summary
            ))
            self.conn.commit()
            return cursor.lastrowid

    def get_run_totals(self, run_id: Optional[str] = None) -> Dict:
        """Get total costs and usage for current or specified run"""
        cursor = self.conn.cursor()

        if run_id:
            # Get specific run window
            cursor.execute("""
                SELECT start_time, end_time FROM run_config WHERE run_id = ?
            """, (run_id,))
            run = cursor.fetchone()
            if not run:
                return {}
            time_filter = f"AND timestamp BETWEEN '{run['start_time']}' AND '{run['end_time'] or datetime.utcnow().isoformat()}'"
        else:
            # Get all time totals
            time_filter = ""

        cursor.execute(f"""
            SELECT
                COUNT(DISTINCT account_id) as accounts_processed,
                SUM(serper_credits) as total_serper_credits,
                SUM(anthropic_cost_usd) as total_anthropic_cost,
                SUM(anthropic_tokens_input) as total_tokens_input,
                SUM(anthropic_tokens_output) as total_tokens_output,
                SUM(playwright_requests) as total_playwright_requests,
                SUM(yolo_inferences) as total_yolo_inferences
            FROM api_calls
            WHERE 1=1 {time_filter}
        """)

        row = cursor.fetchone()
        return dict(row) if row else {}

    def check_circuit_breaker(self, run_id: str) -> tuple[bool, str]:
        """
        Check if circuit breaker should trip.
        Returns (should_continue, reason)
        """
        cursor = self.conn.cursor()

        # Get run limits
        cursor.execute("""
            SELECT max_cost_usd, max_serper_credits, start_time
            FROM run_config WHERE run_id = ?
        """, (run_id,))
        config = cursor.fetchone()

        if not config:
            return False, "Run config not found"

        # Get current usage
        totals = self.get_run_totals(run_id)

        # Check cost limit
        current_cost = totals.get('total_anthropic_cost', 0) or 0
        if current_cost >= config['max_cost_usd']:
            return False, f"Cost limit reached: ${current_cost:.2f} >= ${config['max_cost_usd']:.2f}"

        # Check Serper credit limit
        current_credits = totals.get('total_serper_credits', 0) or 0
        if current_credits >= config['max_serper_credits']:
            return False, f"Serper limit reached: {current_credits} >= {config['max_serper_credits']} credits"

        return True, "OK"

    def create_run(self, run_id: str, max_cost_usd: float,
                   max_serper_credits: int, accounts_total: int):
        """Initialize a new run with budget limits"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO run_config (
                run_id, max_cost_usd, max_serper_credits,
                start_time, accounts_total, status
            ) VALUES (?, ?, ?, ?, ?, 'running')
        """, (
            run_id, max_cost_usd, max_serper_credits,
            datetime.utcnow().isoformat(), accounts_total
        ))
        self.conn.commit()

    def complete_run(self, run_id: str):
        """Mark run as completed"""
        cursor = self.conn.cursor()
        totals = self.get_run_totals(run_id)

        cursor.execute("""
            UPDATE run_config SET
                end_time = ?,
                status = 'completed',
                accounts_processed = ?
            WHERE run_id = ?
        """, (
            datetime.utcnow().isoformat(),
            totals.get('accounts_processed', 0),
            run_id
        ))
        self.conn.commit()

    def get_rollup_by_stage(self, run_id: Optional[str] = None) -> List[Dict]:
        """Rollup costs by stage"""
        cursor = self.conn.cursor()

        time_filter = ""
        if run_id:
            cursor.execute("""
                SELECT start_time, end_time FROM run_config WHERE run_id = ?
            """, (run_id,))
            run = cursor.fetchone()
            if run:
                time_filter = f"WHERE timestamp BETWEEN '{run['start_time']}' AND '{run['end_time'] or datetime.utcnow().isoformat()}'"

        cursor.execute(f"""
            SELECT
                stage,
                COUNT(*) as call_count,
                COUNT(DISTINCT account_id) as unique_accounts,
                SUM(serper_credits) as serper_credits,
                SUM(anthropic_cost_usd) as anthropic_cost,
                SUM(playwright_requests) as playwright_requests,
                SUM(yolo_inferences) as yolo_inferences
            FROM api_calls
            {time_filter}
            GROUP BY stage
            ORDER BY stage
        """)

        return [dict(row) for row in cursor.fetchall()]

    def get_rollup_by_vertical(self, accounts_df) -> List[Dict]:
        """
        Rollup costs by industry vertical.
        Requires accounts DataFrame with account_id and Industry_Bucket.
        """
        # Create temp table with account->vertical mapping
        cursor = self.conn.cursor()
        cursor.execute("CREATE TEMP TABLE IF NOT EXISTS account_verticals (account_id TEXT, vertical TEXT)")

        # Insert mapping
        for _, row in accounts_df[['18 Digit Account ID', 'Industry_Bucket']].iterrows():
            cursor.execute(
                "INSERT OR REPLACE INTO account_verticals VALUES (?, ?)",
                (row['18 Digit Account ID'], row['Industry_Bucket'])
            )

        # Rollup by vertical
        cursor.execute("""
            SELECT
                av.vertical,
                COUNT(*) as call_count,
                COUNT(DISTINCT ac.account_id) as unique_accounts,
                SUM(ac.serper_credits) as serper_credits,
                SUM(ac.anthropic_cost_usd) as anthropic_cost,
                SUM(ac.playwright_requests) as playwright_requests,
                SUM(ac.yolo_inferences) as yolo_inferences
            FROM api_calls ac
            JOIN account_verticals av ON ac.account_id = av.account_id
            GROUP BY av.vertical
            ORDER BY anthropic_cost DESC
        """)

        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


if __name__ == "__main__":
    # Test the cost tracker
    tracker = CostTracker("test_costs.db")

    # Create a test run
    run_id = f"test_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    tracker.create_run(run_id, max_cost_usd=50.0, max_serper_credits=1000, accounts_total=100)

    # Log some test calls
    tracker.log_serper_call("001TEST123", "stage_0.5", "test company yelp", credits_used=1)
    tracker.log_anthropic_call("001TEST123", "stage_4_vlm", "claude-haiku-4", 500, 100)
    tracker.log_yolo_inference("001TEST123", "http://example.com/image.jpg", ["tv", "couch"])

    # Check totals
    totals = tracker.get_run_totals(run_id)
    print("Run totals:", json.dumps(totals, indent=2))

    # Check circuit breaker
    should_continue, reason = tracker.check_circuit_breaker(run_id)
    print(f"Circuit breaker: {should_continue} - {reason}")

    tracker.complete_run(run_id)
    tracker.close()

    print("\n✓ Cost tracker test completed")
