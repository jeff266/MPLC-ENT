# Hotel Enrichment Diagnostic Report
**Date:** October 27, 2026

---

## Summary

**Status:** ❌ 0% Match Rate
- **Total Accounts:** 352 hospitality accounts
- **Franchisee Found:** 0 (0.0%)
- **Operator Found:** 0 (0.0%)
- **Room Count Found:** 0 (0.0% - not searched without SERPER_API_KEY)

**Output File:** `output/runs/hotels_enriched_with_franchisee_operator_2026-10-27.csv` (90KB)

---

## Root Cause: Name Format Mismatch

### Account Names (from Salesforce)
```
"The Renaissance Chicago O'Hare Hotel"
"Embassy Suites Napa Valley"
"AC Hotel Lansing University Area"
"Westin Monache Hotel - Children's Program"
"Virgin Hotels New York City"
```

### Database Names (from FDD/Operator Detector)
```
"Courtyard Anniston Oxford"
"Courtyard Auburn"
"Courtyard Birmingham Downtown at UAB"
"Courtyard Flagstaff"
```

**Problem:** The normalize_hotel_name() function strips suffixes like "hotel", "inn", "suites" but doesn't handle:
1. **Articles:** "The" prefix in account names
2. **Brand format differences:** "Renaissance" vs "Courtyard by Marriott"
3. **Location format:** "Chicago O'Hare" vs "Anniston Oxford"
4. **Suffixes in middle:** "Westin Monache Hotel - Children's Program"

**Result:** Exact key matching fails 100% of the time

---

## Data Loaded Successfully

### Franchisee Database
- **Source:** `/verticals/hotels/output/hotel_franchisee_database_complete.csv`
- **Records:** 10,209 franchisee records
- **Format:**
  ```csv
  company,brand,hotel_name,franchisee,address,city,state,zip
  Marriott,Courtyard by Marriott,Courtyard Anniston Oxford,Oxford CY LLC,...
  ```
- **Coverage:** Marriott brands (complete), Choice Hotels (complete), Wyndham (structure documented), IHG/Hilton (partial)

### Operator Database
- **Source:** `/verticals/hotels/output/70_hotels_validated_20261026_161622.csv`
- **Records:** 70 operator records (67% success rate on test set)
- **Format:**
  ```csv
  hotel_name,operator,operator_source,operator_confidence,operator_evidence
  Courtyard Anniston Oxford,LBA Hospitality,management_search,confirmed_current,"Found ""managed by"" mention"
  ```

---

## Matching Logic Issues

### Current normalize_hotel_name()
```python
def normalize_hotel_name(name: str) -> str:
    name = name.lower()
    # Remove common suffixes
    name = name.replace(' hotel', '').replace(' inn', '').replace(' suites', '')
    name = name.replace(' resort', '').replace(' & spa', '')
    return name.strip()
```

**Example Transformations:**
- "The Renaissance Chicago O'Hare Hotel" → "the renaissance chicago o'hare"
- "Courtyard Anniston Oxford" → "courtyard anniston oxford"
- **NO MATCH** (completely different strings)

---

## Sample Non-Matches

| Account Name | Normalized Key | Expected Match | Status |
|--------------|----------------|----------------|--------|
| The Renaissance Chicago O'Hare Hotel | the renaissance chicago o'hare | Renaissance Chicago O'Hare | ❌ Not found |
| Embassy Suites Napa Valley | embassy napa valley | Embassy Suites Napa Valley | ❌ Not found |
| AC Hotel Lansing University Area | ac lansing university area | AC Hotel Lansing | ❌ Not found |
| Courtyard Anniston Oxford | courtyard anniston oxford | Courtyard Anniston Oxford | ✅ Would match (if in accounts) |

**Note:** All Courtyard by Marriott properties in the database would theoretically match IF they were in the accounts file, but the 352 hospitality accounts appear to be different properties.

---

## Corporate Employee Count Problem

Many accounts show **corporate employee counts** instead of property-level data:

```csv
Account: The Renaissance Chicago O'Hare Hotel
Employees: 377,000  ← This is Marriott Corporation total
Should be: Room count (e.g., 390 rooms)
```

```csv
Account: Embassy Suites Napa Valley
Employees: 159,560  ← This is Hilton Corporation total
Should be: Room count (e.g., 250 rooms)
```

**Impact:** Can't do proper ROE classification (need rooms, not corporate headcount)

---

## Recommendations

### Option 1: Fuzzy Matching (Quick Fix)
Use fuzzy string matching to bridge naming differences:
- **Library:** `rapidfuzz` or `fuzzywuzzy`
- **Threshold:** 80% similarity
- **Match on:** City + brand keywords
- **Estimated time:** 1-2 hours
- **Expected improvement:** 20-40% match rate

### Option 2: Multi-Field Matching (Better)
Match on multiple fields instead of just name:
```python
def match_hotel(account, franchisee_db):
    # Match on: brand keyword + city + state
    # Example: "Renaissance" + "Chicago" + "IL"
    # Franchisee: "Courtyard" + "Oxford" + "AL"
```
- **Estimated time:** 2-3 hours
- **Expected improvement:** 40-60% match rate

### Option 3: Address Geocoding (Most Accurate)
Match on physical location (lat/lon):
- Geocode account addresses
- Match to franchisee database by proximity (<100m)
- **Cost:** $0.005 per geocode × 352 = $1.76
- **Estimated time:** 3-4 hours
- **Expected improvement:** 70-90% match rate

### Option 4: Manual Enrichment (Guaranteed)
Use Clay or ZoomInfo for human-assisted matching:
- Upload 352 accounts
- Enrich with franchisee + operator + room count
- **Cost:** ~$50-100 (depending on service)
- **Estimated time:** 30 minutes setup + overnight processing

---

## Room Count Enrichment

**Current Status:** Not attempted (SERPER_API_KEY not set)

**If SERPER_API_KEY provided:**
- Cost: $0.01 per search
- Expected success: 60-70% (based on similar searches)
- Total cost: $3.52 for 352 accounts

**Alternative Sources:**
1. **STR Database:** $750/year (industry standard, complete data)
2. **Hotel websites:** FREE but requires scraping (67% success rate)
3. **TripAdvisor/Booking.com:** FREE, high coverage

---

## Current Output CSV

**File:** `output/runs/hotels_enriched_with_franchisee_operator_2026-10-27.csv`

**Columns:**
```
account_id, account_name, industry, account_sub_industry, capacity,
capacity_type, capacity_source, website, account_street, account_state,
account_country, phone, account_owner, account_status, operating_market,
segment, capacity_used, classification_reason,
franchisee, franchisee_source, operator, operator_source,
operator_confidence, operator_evidence, operator_source_url,
room_count, room_count_source, room_count_confidence
```

**All enrichment columns are empty:**
- `franchisee`: empty
- `operator`: empty
- `room_count`: empty

---

## Next Steps

**Before proceeding with hotels:**

1. **Decide matching strategy** (Option 1-4 above)
2. **Add SERPER_API_KEY** for room count search (or choose alternative)
3. **Re-run enrichment** with improved matching logic
4. **Validate results** on sample of 20-30 hotels

**Alternative approach:**
- Prioritize Healthcare (1,424 accounts) and Corporate (3,790 accounts) first
- Hotels are smaller dataset (352 accounts) and need more work
- Come back to hotels after main verticals are production-ready

---

## Files for Reference

### Created/Modified:
- `enrich_hotel_data.py` - Enrichment script (current version has matching issues)
- `output/runs/hotels_enriched_with_franchisee_operator_2026-10-27.csv` - Output (0% match)

### Data Sources:
- `output/runs/hospitality_accounts_to_process_2026-10-23.csv` - 352 accounts
- `../verticals/hotels/output/hotel_franchisee_database_complete.csv` - 10,209 franchisee records
- `../verticals/hotels/output/70_hotels_validated_20261026_161622.csv` - 70 operator records

### Documentation:
- `HOTEL_HOSPITALITY_STATUS.md` - Overall hotel pipeline status
- `HOTEL_OPERATOR_FINAL_STATUS.md` - Operator detector assessment

---

## Cost-Benefit Analysis

**Hotel Pipeline Work Remaining:**
- Fix matching logic: 2-4 hours
- Room count enrichment: 1-2 hours
- Test + validation: 1 hour
- **Total: 4-7 hours**

**vs. Healthcare + Corporate:**
- Already built and tested
- 5,214 accounts ready for parallel processing
- Proven hit rates (16.7% corporate, TBD healthcare)
- Immediate sales impact

**Recommendation:** Ship Healthcare + Corporate first, then circle back to hotels.
