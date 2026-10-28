# Canonical Data - Master Reference Files

**Purpose:** Store enriched data that should NOT be re-enriched via paid APIs (Clay, etc.). These are lookup tables to prevent duplicate enrichment costs.

---

## Files

### employee_counts_master.csv

**Purpose:** Master employee count lookup for all Salesforce accounts

**Created:** October 23, 2026
**Source:** Clay enrichment + cleaned Salesforce data
**Records:** 56,797 accounts
**Coverage:** 65.8% of 86,300 filtered US accounts

**Fields:**
- `account_id` - Salesforce 18-digit Account ID (unique key)
- `account_name` - Business name
- `employee_count` - Verified employee count (integer)
- `source` - Data provenance
  - `clay_enriched_2` - Part 1 Clay enrichment (4,792 accounts)
  - `clay_enriched` - Part 2 Clay enrichment (20,778 accounts)
  - `salesforce_clean` - Salesforce data, filtered placeholders (31,227 accounts)
- `website` - Company website URL

**Filtered placeholders:** 823, 9551, 1232, 154, 443, 246013

**Usage:**
```python
import csv

# Load canonical employee counts
employee_counts = {}
with open('data/canonical/employee_counts_master.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        employee_counts[row['account_id']] = {
            'employee_count': int(row['employee_count']),
            'source': row['source'],
            'website': row['website']
        }

# Check before enriching
account_id = '0016e00002vwmiuAAA'
if account_id in employee_counts:
    print(f"Already have data: {employee_counts[account_id]}")
else:
    print(f"Needs enrichment: {account_id}")
```

**Updates:**
- Add new enrichments by appending to this file
- Never remove entries (data is cumulative)
- Re-export to HubSpot monthly to sync any manual corrections

---

## Guidelines

### When to Use Canonical Data

✅ **ALWAYS check canonical files before:**
- Running Clay enrichment
- Calling external APIs for employee counts
- Requesting manual data entry

✅ **DO use canonical data for:**
- ROE classification
- Weekly pipeline processing
- HubSpot import/sync
- Deduplication checks

### When to Update Canonical Data

✅ **ADD to canonical when:**
- New Clay enrichment batch completes
- Manual research provides employee counts
- Salesforce data is corrected/updated
- Merging accounts from new data sources

❌ **DO NOT modify canonical when:**
- Running exploratory analysis
- Testing new enrichment logic
- Processing subsets of data

### Backup Protocol

1. **Before major updates:** Copy canonical file with timestamp
   ```bash
   cp employee_counts_master.csv employee_counts_master_backup_YYYY-MM-DD.csv
   ```

2. **Weekly backups:** Automated backup to `data/canonical/backups/`

3. **Version control:** Canonical files are tracked in git

---

## File Organization

```
data/canonical/
├── README.md                          # This file
├── employee_counts_master.csv         # Current master file
├── backups/                           # Timestamped backups
│   ├── employee_counts_master_2026-10-23.csv
│   └── employee_counts_master_2026-10-30.csv
└── deprecated/                        # Old versions (reference only)
```

---

## Integration with Pipeline

### Stage 1: ROE Classification

Before running ROE classifier, merge with canonical data:

```python
# Load canonical employee counts
canonical = load_canonical_employee_counts()

# Enrich accounts
for account in accounts:
    account_id = account['account_id']

    # Check canonical first
    if account_id in canonical:
        account['employee_count'] = canonical[account_id]['employee_count']
        account['employee_count_source'] = canonical[account_id]['source']
    elif account['capacity']:
        # Use Salesforce capacity if available
        account['employee_count'] = account['capacity']
        account['employee_count_source'] = 'salesforce'
    else:
        # Needs enrichment
        account['employee_count'] = None
        account['employee_count_source'] = 'missing'
```

### Enrichment Ledger Integration

The enrichment ledger (SQLite) tracks API calls and costs.
Canonical data is the **result** of successful enrichments.

**Flow:**
1. Check enrichment ledger → Did we already try to enrich this account?
2. Check canonical data → Do we have a successful result?
3. If both No → Run enrichment
4. Record attempt in ledger
5. If successful → Add to canonical

---

## Cost Savings

**Current canonical coverage:** 56,797 accounts

**Estimated savings:**
- Clay enrichment: ~$0.01 per account
- **Saved:** $567.97 if these accounts were re-enriched

**Annual savings (assuming 4 re-enrichment cycles):**
- **~$2,272** per year by maintaining canonical data

---

## Maintenance

**Monthly:**
- Review for duplicate entries
- Validate employee counts haven't changed significantly
- Re-sync with HubSpot

**Quarterly:**
- Flag accounts >1 year old for re-validation
- Update with any manual corrections from sales team
- Archive old backups

**Annually:**
- Full re-enrichment for public companies (employee counts change)
- Validate against EDGAR for public companies
- Clean up deprecated data

---

## Related Files

- **Source data:** `data/salesforce/` - Weekly Salesforce exports
- **Pipeline outputs:** `output/runs/` - ROE classification results
- **Documentation:** `documents/EMPLOYEE_COUNT_EXTRACTION_2026-10-23.md` - How canonical was created
- **Enrichment ledger:** `enrichment_ledger.db` - API call tracking

---

**Last Updated:** October 23, 2026
**Maintainer:** RevOps Team
**Questions:** See `documents/EMPLOYEE_COUNT_EXTRACTION_2026-10-23.md`
