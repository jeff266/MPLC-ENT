#!/usr/bin/env python3
"""
Enrichment Ledger - Deduplication and Cost Tracking

Prevents double-spend by tracking all enrichment calls with 90-day freshness window.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from pathlib import Path


class EnrichmentLedger:
    """SQLite-based enrichment tracking with 90-day dedup window."""

    def __init__(self, db_path: str = "enrichment_ledger.db"):
        """Initialize ledger connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row  # Enable dict-like access
        self._init_schema()

    def _init_schema(self):
        """Create tables and indexes if they don't exist."""
        schema_path = Path(__file__).parent.parent / "enrichment_ledger_schema.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                self.conn.executescript(f.read())
        else:
            # Fallback inline schema
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS enrichment_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    account_name TEXT NOT NULL,
                    enrichment_type TEXT NOT NULL,
                    enrichment_date TIMESTAMP NOT NULL,
                    result_status TEXT NOT NULL,
                    result_data TEXT,
                    cost_usd REAL,
                    source TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(account_id, enrichment_type, enrichment_date)
                );

                CREATE INDEX IF NOT EXISTS idx_account_enrichment
                ON enrichment_ledger(account_id, enrichment_type, enrichment_date DESC);

                CREATE INDEX IF NOT EXISTS idx_enrichment_date
                ON enrichment_ledger(enrichment_date);
            """)
        self.conn.commit()

    def should_enrich(
        self,
        account_id: str,
        enrichment_type: str,
        freshness_days: int = 90
    ) -> bool:
        """Check if account should be enriched (not enriched within freshness window).

        Args:
            account_id: Salesforce 18-digit Account ID
            enrichment_type: Type of enrichment (employee_count, yelp_url, etc.)
            freshness_days: Number of days before re-enrichment (default 90)

        Returns:
            True if enrichment should proceed, False if recent enrichment exists
        """
        cutoff_date = datetime.now() - timedelta(days=freshness_days)

        cursor = self.conn.execute("""
            SELECT enrichment_date, result_status
            FROM enrichment_ledger
            WHERE account_id = ? AND enrichment_type = ?
            ORDER BY enrichment_date DESC
            LIMIT 1
        """, (account_id, enrichment_type))

        row = cursor.fetchone()

        if row is None:
            # Never enriched - proceed
            return True

        last_enrichment = datetime.fromisoformat(row['enrichment_date'])
        last_status = row['result_status']

        # Re-enrich if:
        # 1. Last enrichment is older than freshness window
        # 2. OR last enrichment failed/not found (allow retry)
        if last_enrichment < cutoff_date:
            return True

        if last_status in ('failure', 'not_found'):
            # TODO: Add exponential backoff logic here
            # For now, allow immediate retry on failure
            return True

        return False

    def record_enrichment(
        self,
        account_id: str,
        account_name: str,
        enrichment_type: str,
        result_status: str,
        result_data: Optional[Dict[str, Any]] = None,
        cost_usd: Optional[float] = None,
        source: Optional[str] = None
    ) -> int:
        """Record an enrichment attempt in the ledger.

        Args:
            account_id: Salesforce 18-digit Account ID
            account_name: Account name for human reference
            enrichment_type: Type of enrichment
            result_status: 'success' / 'failure' / 'not_found'
            result_data: Enrichment results (will be JSON-serialized)
            cost_usd: Cost in USD
            source: Data source (edgar, apify, serper, etc.)

        Returns:
            ID of inserted record
        """
        cursor = self.conn.execute("""
            INSERT INTO enrichment_ledger
            (account_id, account_name, enrichment_type, enrichment_date,
             result_status, result_data, cost_usd, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            account_id,
            account_name,
            enrichment_type,
            datetime.now().isoformat(),
            result_status,
            json.dumps(result_data) if result_data else None,
            cost_usd,
            source
        ))
        self.conn.commit()
        return cursor.lastrowid

    def get_accounts_needing_enrichment(
        self,
        account_ids: List[str],
        enrichment_type: str,
        freshness_days: int = 90
    ) -> List[str]:
        """Get list of accounts from input that need enrichment.

        Args:
            account_ids: List of Salesforce Account IDs to check
            enrichment_type: Type of enrichment
            freshness_days: Freshness window in days

        Returns:
            List of account IDs that need enrichment
        """
        needs_enrichment = []
        for account_id in account_ids:
            if self.should_enrich(account_id, enrichment_type, freshness_days):
                needs_enrichment.append(account_id)
        return needs_enrichment

    def get_enrichment_history(
        self,
        account_id: str,
        enrichment_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get enrichment history for an account.

        Args:
            account_id: Salesforce Account ID
            enrichment_type: Optional filter by enrichment type

        Returns:
            List of enrichment records
        """
        if enrichment_type:
            cursor = self.conn.execute("""
                SELECT * FROM enrichment_ledger
                WHERE account_id = ? AND enrichment_type = ?
                ORDER BY enrichment_date DESC
            """, (account_id, enrichment_type))
        else:
            cursor = self.conn.execute("""
                SELECT * FROM enrichment_ledger
                WHERE account_id = ?
                ORDER BY enrichment_date DESC
            """, (account_id,))

        return [dict(row) for row in cursor.fetchall()]

    def get_cost_summary(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get cost summary for a date range.

        Args:
            start_date: Start of date range (default: 30 days ago)
            end_date: End of date range (default: now)

        Returns:
            List of cost summary records
        """
        if start_date is None:
            start_date = datetime.now() - timedelta(days=30)
        if end_date is None:
            end_date = datetime.now()

        cursor = self.conn.execute("""
            SELECT
                DATE(enrichment_date) as date,
                enrichment_type,
                source,
                COUNT(*) as enrichment_count,
                SUM(cost_usd) as total_cost,
                AVG(cost_usd) as avg_cost,
                SUM(CASE WHEN result_status = 'success' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN result_status = 'failure' THEN 1 ELSE 0 END) as failure_count
            FROM enrichment_ledger
            WHERE enrichment_date BETWEEN ? AND ?
            GROUP BY DATE(enrichment_date), enrichment_type, source
            ORDER BY date DESC
        """, (start_date.isoformat(), end_date.isoformat()))

        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """Close database connection."""
        self.conn.close()

    def __enter__(self):
        """Context manager support."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup."""
        self.close()


# Example usage
if __name__ == "__main__":
    # Demo the ledger
    with EnrichmentLedger() as ledger:
        # Check if enrichment is needed
        account_id = "001MM001TESTID123"

        if ledger.should_enrich(account_id, "employee_count"):
            print(f"Account {account_id} needs employee count enrichment")

            # Simulate enrichment (would call EDGAR API here)
            ledger.record_enrichment(
                account_id=account_id,
                account_name="Buffalo Wild Wings",
                enrichment_type="employee_count",
                result_status="success",
                result_data={"employee_count": 150, "source": "edgar"},
                cost_usd=0.0,
                source="edgar"
            )
            print("Enrichment recorded")
        else:
            print(f"Account {account_id} already enriched within 90 days - skipping")

        # Get history
        history = ledger.get_enrichment_history(account_id)
        print(f"\nEnrichment history for {account_id}:")
        for record in history:
            print(f"  {record['enrichment_date']}: {record['enrichment_type']} = {record['result_status']}")

        # Get cost summary
        costs = ledger.get_cost_summary()
        print("\nCost summary (last 30 days):")
        for record in costs:
            print(f"  {record['date']}: {record['enrichment_type']} - {record['enrichment_count']} calls, ${record['total_cost']:.2f}")
