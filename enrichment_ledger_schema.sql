-- Enrichment Ledger Schema (SQLite)
-- Purpose: Prevent double-spend by tracking all enrichment calls with 90-day freshness window

CREATE TABLE IF NOT EXISTS enrichment_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,              -- Salesforce 18-digit Account ID
    account_name TEXT NOT NULL,            -- For human reference
    enrichment_type TEXT NOT NULL,         -- 'employee_count' / 'yelp_url' / 'photo_scan' / etc.
    enrichment_date TIMESTAMP NOT NULL,    -- When enrichment was performed
    result_status TEXT NOT NULL,           -- 'success' / 'failure' / 'not_found'
    result_data TEXT,                      -- JSON blob with enrichment results
    cost_usd REAL,                         -- Cost in USD for this enrichment
    source TEXT,                           -- 'edgar' / 'apify' / 'serper' / etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, enrichment_type, enrichment_date)
);

-- Index for fast lookups: "Has this account been enriched recently?"
CREATE INDEX IF NOT EXISTS idx_account_enrichment
ON enrichment_ledger(account_id, enrichment_type, enrichment_date DESC);

-- Index for cost tracking
CREATE INDEX IF NOT EXISTS idx_enrichment_date
ON enrichment_ledger(enrichment_date);

-- View: Accounts needing re-enrichment (>90 days old or failed/not found)
CREATE VIEW IF NOT EXISTS accounts_needing_enrichment AS
SELECT
    account_id,
    account_name,
    enrichment_type,
    MAX(enrichment_date) as last_enrichment_date,
    JULIANDAY('now') - JULIANDAY(MAX(enrichment_date)) as days_since_enrichment,
    result_status as last_result_status
FROM enrichment_ledger
GROUP BY account_id, enrichment_type
HAVING
    -- Re-enrich if >90 days old
    days_since_enrichment > 90
    -- OR if last attempt failed (retry with exponential backoff logic)
    OR last_result_status IN ('failure', 'not_found');

-- View: Cost tracking by date and source
CREATE VIEW IF NOT EXISTS enrichment_costs_summary AS
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
GROUP BY DATE(enrichment_date), enrichment_type, source
ORDER BY date DESC;

-- Sample queries for common operations:

-- 1. Check if account needs enrichment (within 90 days)
-- SELECT account_id, days_since_enrichment
-- FROM accounts_needing_enrichment
-- WHERE account_id = '001MM001TESTID123' AND enrichment_type = 'employee_count';

-- 2. Get all accounts from weekly Salesforce export that need enrichment
-- SELECT sf.account_id, sf.account_name
-- FROM salesforce_weekly_export sf
-- LEFT JOIN (
--     SELECT account_id, enrichment_type, MAX(enrichment_date) as last_date
--     FROM enrichment_ledger
--     WHERE enrichment_type = 'employee_count'
--     GROUP BY account_id
-- ) el ON sf.account_id = el.account_id
-- WHERE el.last_date IS NULL
--    OR JULIANDAY('now') - JULIANDAY(el.last_date) > 90;

-- 3. Daily cost report
-- SELECT * FROM enrichment_costs_summary
-- WHERE date >= DATE('now', '-30 days')
-- ORDER BY date DESC;
