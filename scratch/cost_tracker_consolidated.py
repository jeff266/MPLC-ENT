"""
Consolidated Cost Tracker - Single Database for ALL Apify Runs

Key improvements:
1. Single database file used by all scripts
2. Stores Apify run IDs for reconciliation
3. Thread-safe for parallel operations
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, Optional, List
from pathlib import Path
from threading import Lock


class ConsolidatedCostTracker:
    """Single source of truth for all cost tracking"""

    # Singleton database path - ALL scripts use this
    GLOBAL_DB = Path("mplc_costs_consolidated.db")

    def __init__(self):
        self.db_path = self.GLOBAL_DB
        self.conn = None
        self._db_lock = Lock()
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with consolidated schema"""
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        cursor = self.conn.cursor()

        # Main cost tracking table with Apify run ID
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                source TEXT NOT NULL,

                -- Apify-specific fields
                apify_run_id TEXT,
                apify_actor_name TEXT,
                apify_dataset_id TEXT,

                -- Cost tracking
                cost_usd REAL DEFAULT 0,

                -- Metadata
                timestamp TEXT NOT NULL,
                result_status TEXT,
                result_summary TEXT,

                -- Script tracking
                script_name TEXT,
                run_session_id TEXT
            )
        """)

        # Run session table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS run_sessions (
                session_id TEXT PRIMARY KEY,
                script_name TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                status TEXT DEFAULT 'running',
                accounts_total INTEGER,
                accounts_processed INTEGER DEFAULT 0,
                total_cost_usd REAL DEFAULT 0
            )
        """)

        # Indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_account_stage
            ON api_calls(account_id, stage)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_apify_run_id
            ON api_calls(apify_run_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON api_calls(timestamp)
        """)

        self.conn.commit()

    def log_apify_call(
        self,
        account_id: str,
        stage: str,
        source: str,
        cost_usd: float = 0.0,
        result_status: str = "success",
        result_summary: str = "",
        apify_run_id: Optional[str] = None,
        apify_actor_name: Optional[str] = None,
        apify_dataset_id: Optional[str] = None,
        script_name: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> int:
        """
        Log an Apify API call with full tracking

        Args:
            account_id: Business/account identifier
            stage: Pipeline stage
            source: Source identifier (e.g., 'apify_compass_maps')
            cost_usd: Cost in USD
            result_status: 'success' or 'error'
            result_summary: Summary of results (e.g., '25 reviews')
            apify_run_id: Apify run ID for reconciliation
            apify_actor_name: Actor name
            apify_dataset_id: Dataset ID
            script_name: Name of script making the call
            session_id: Session ID for grouping calls

        Returns:
            Log entry ID
        """
        with self._db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO api_calls (
                    account_id, stage, source, cost_usd,
                    result_status, result_summary,
                    apify_run_id, apify_actor_name, apify_dataset_id,
                    script_name, run_session_id, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                account_id, stage, source, cost_usd,
                result_status, result_summary,
                apify_run_id, apify_actor_name, apify_dataset_id,
                script_name, session_id,
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()
            return cursor.lastrowid

    def create_session(
        self,
        session_id: str,
        script_name: str,
        accounts_total: int
    ):
        """Initialize a new run session"""
        with self._db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO run_sessions (
                    session_id, script_name, start_time, accounts_total
                ) VALUES (?, ?, ?, ?)
            """, (
                session_id, script_name,
                datetime.utcnow().isoformat(), accounts_total
            ))
            self.conn.commit()

    def complete_session(self, session_id: str):
        """Mark session as completed"""
        with self._db_lock:
            cursor = self.conn.cursor()

            # Calculate totals
            cursor.execute("""
                SELECT
                    COUNT(DISTINCT account_id) as accounts,
                    SUM(cost_usd) as total_cost
                FROM api_calls
                WHERE run_session_id = ?
            """, (session_id,))

            row = cursor.fetchone()
            accounts = row['accounts'] if row['accounts'] else 0
            total_cost = row['total_cost'] if row['total_cost'] else 0.0

            cursor.execute("""
                UPDATE run_sessions SET
                    end_time = ?,
                    status = 'completed',
                    accounts_processed = ?,
                    total_cost_usd = ?
                WHERE session_id = ?
            """, (
                datetime.utcnow().isoformat(),
                accounts,
                total_cost,
                session_id
            ))
            self.conn.commit()

    def get_session_totals(self, session_id: str) -> Dict:
        """Get totals for a specific session"""
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total_calls,
                COUNT(DISTINCT account_id) as unique_accounts,
                SUM(cost_usd) as total_cost,
                SUM(CASE WHEN result_status = 'success' THEN 1 ELSE 0 END) as successful_calls,
                SUM(CASE WHEN result_status = 'error' THEN 1 ELSE 0 END) as failed_calls
            FROM api_calls
            WHERE run_session_id = ?
        """, (session_id,))

        row = cursor.fetchone()
        return dict(row) if row else {}

    def get_all_apify_runs(self, limit: int = 100) -> List[Dict]:
        """Get all Apify runs with run IDs for reconciliation"""
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT
                timestamp,
                account_id,
                source,
                apify_run_id,
                apify_actor_name,
                cost_usd,
                result_summary,
                script_name
            FROM api_calls
            WHERE source LIKE '%apify%'
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))

        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


if __name__ == "__main__":
    # Test the consolidated tracker
    tracker = ConsolidatedCostTracker()

    # Create test session
    session_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    tracker.create_session(session_id, "test_script.py", 3)

    # Log test call
    tracker.log_apify_call(
        account_id="Test Account",
        stage="test_stage",
        source="apify_compass_maps",
        cost_usd=0.0075,
        result_status="success",
        result_summary="25 reviews",
        apify_run_id="test_run_123",
        apify_actor_name="compass/google-maps-reviews-scraper",
        script_name="test_script.py",
        session_id=session_id
    )

    # Complete session
    tracker.complete_session(session_id)

    # Get totals
    totals = tracker.get_session_totals(session_id)
    print("Session totals:", json.dumps(totals, indent=2))

    # Get all runs
    runs = tracker.get_all_apify_runs(limit=5)
    print(f"\nRecent Apify runs: {len(runs)}")
    for run in runs:
        print(f"  {run['timestamp']} | {run['account_id']} | Run ID: {run['apify_run_id']} | ${run['cost_usd']:.4f}")

    tracker.close()

    print("\n✓ Consolidated cost tracker test completed")
