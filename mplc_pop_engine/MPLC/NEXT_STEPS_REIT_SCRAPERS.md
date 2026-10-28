# Next Steps: Completing Camden, UDR, and Equity Residential Scrapers

## Current Status
- **Essex Property Trust:** ✓ Working (59 properties in test)
- **AvalonBay Communities:** ✓ Working (177 properties)
- **Mid-America Apartments (MAA):** ✓ Working (improved sitemap approach)
- **Camden Property Trust:** ✗ Not working (needs advanced techniques)
- **UDR Inc:** ✗ Not working (needs advanced techniques)
- **Equity Residential:** ✗ Not working (Cloudflare protection)

---

## Quick Win: Run Working Scrapers Now

```bash
cd /Users/jeffignacio/mplc_pop_engine/MPLC
python run_working_scrapers.py
```

This will collect ~850 properties from the 3 working REITs.

---

## Option 1: Advanced Scraping Techniques (Recommended)

### Install Stealth Browser
```bash
pip install undetected-playwright
# or
pip install selenium-stealth undetected-chromedriver
```

### Implement for Each REIT

#### Camden Property Trust
**Target URL:** `https://www.camdenliving.com/apartments`

**Strategy:**
1. Use stealth Playwright with residential proxies
2. Wait for property cards to load (selector-based wait)
3. Scroll incrementally and wait between scrolls
4. Extract from: `/{state}/{city}/camden-{property-name}` pattern

**Code Template:**
```python
from playwright_stealth import stealth_sync

def scrape_camden_stealth():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, proxy={'server': 'proxy-url'})
        page = browser.new_page()
        stealth_sync(page)

        page.goto('https://www.camdenliving.com/apartments')
        page.wait_for_selector('.property-card', timeout=30000)  # Adjust selector
        # ... rest of scraping logic
```

#### UDR Inc
**Target URL:** `https://www.udr.com/search-apartments/`

**Strategy:**
1. Inspect Network tab for API endpoints (likely JSON response with all properties)
2. If API found: Direct API calls (much faster and more reliable)
3. If no API: Stealth browser with property card selectors

**Check for API:**
```bash
# Open browser DevTools → Network tab → XHR/Fetch filter
# Look for JSON responses containing property data
# Common endpoints: /api/properties, /search, /communities
```

#### Equity Residential
**Target URL:** `https://www.equityapartments.com/apartments`

**Strategy:**
1. **Primary:** Cloudflare bypass using FlareSolverr or similar
2. **Alternative:** undetected-chromedriver with residential proxy
3. **Fallback:** Scrape from Apartments.com (they list Equity properties)

**Cloudflare Bypass:**
```python
import cloudscraper

scraper = cloudscraper.create_scraper()
html = scraper.get('https://www.equityapartments.com/apartments').text
# Parse HTML as normal
```

---

## Option 2: API Endpoint Discovery (Fastest if Available)

### Tools Needed
1. Browser DevTools (Network tab)
2. Postman or curl for testing
3. Optional: Burp Suite for advanced inspection

### Steps for Each REIT

1. **Open apartments listing page in browser**
2. **Open DevTools → Network tab**
3. **Filter for: XHR, Fetch, or JS**
4. **Scroll/interact with page to trigger API calls**
5. **Look for JSON responses containing property data**
6. **Copy as cURL, convert to Python requests**

### Example: If UDR Has API
```python
import requests

def scrape_udr_via_api():
    # Example - adjust based on actual API
    url = "https://www.udr.com/api/properties"
    headers = {
        'User-Agent': 'Mozilla/5.0...',
        'Accept': 'application/json'
    }

    response = requests.get(url, headers=headers)
    properties = response.json()

    # Process properties...
```

---

## Option 3: Third-Party Source Scraping (Most Reliable Fallback)

### Apartments.com Approach
All three REITs list on Apartments.com with complete property data.

**Advantages:**
- More scraper-friendly than official REIT sites
- Standardized data format across all REITs
- Includes additional data (amenities, photos, reviews)

**Implementation:**
```python
def scrape_apartments_com_for_reit(reit_name):
    # Search for: "{reit_name} apartments"
    # Example: "Camden apartments"
    search_url = f"https://www.apartments.com/search/?q={reit_name}"
    # Extract property listings
    # Return standardized format
```

---

## Option 4: Manual Data Collection (Last Resort)

### For Small Datasets (<50 properties)
If a REIT has limited coverage in your target markets:
1. Manually browse their website
2. Copy property names and URLs into CSV
3. Import into your database

### For Larger Datasets
1. **Request data from REIT:**
   - Email investor relations
   - Request property list for research purposes
   - Mention academic/business use case

2. **Use investor presentations:**
   - Check REIT investor relations page
   - Download property lists from PDFs/Excel
   - Parse and import

---

## Recommended Priority Order

### Phase 1: Low-Hanging Fruit (This Week)
1. **Check for API endpoints** (UDR, Equity, Camden)
   - 1-2 hours per REIT
   - If found: ~30 minutes to implement
   - Highest ROI if successful

2. **Try Cloudflare bypass** (Equity Residential)
   - Install: `pip install cloudscraper`
   - Test: 30 minutes
   - If works: Done in <1 hour

### Phase 2: Stealth Techniques (Next Week)
3. **Implement stealth Playwright** (Camden, UDR)
   - Install undetected-playwright: 30 minutes
   - Adapt existing scrapers: 2-3 hours per REIT
   - Success rate: ~70%

### Phase 3: Alternative Sources (Backup Plan)
4. **Apartments.com scraper** (All 3 REITs)
   - Build once, use for all: 4-6 hours
   - More reliable than direct scraping
   - Additional data available

### Phase 4: Manual Fallback
5. **Contact REITs for data** or **manual entry**
   - Only if all above fail
   - Time: varies

---

## Testing Commands

### Test Individual Scraper
```bash
python test_reit_scrapers.py  # Tests all 4 new scrapers
```

### Test Only Working Scrapers
```bash
python run_working_scrapers.py  # Production run of working scrapers
```

### Debug Specific REIT
```bash
python debug_reit_pages.py  # Inspect HTML structure
python try_alternative_approaches.py  # Test different approaches
```

---

## Success Criteria

### Minimum Viable (MVP)
- [ ] 850+ properties from working scrapers (AvalonBay, MAA, Essex)
- [x] Production script ready (`run_working_scrapers.py`)
- [x] Documentation complete

### Complete Success
- [ ] 1,530+ properties (all 6 REITs working)
- [ ] Camden scraper operational (~180 properties)
- [ ] UDR scraper operational (~200 properties)
- [ ] Equity Residential scraper operational (~300 properties)

---

## Files Reference

### Production Ready
- `run_working_scrapers.py` - Run working scrapers only
- `scrape_all_reits.py` - Main scraper file (includes all attempts)

### Testing & Development
- `test_reit_scrapers.py` - Test harness for new scrapers
- `debug_reit_pages.py` - HTML structure inspection
- `try_alternative_approaches.py` - Experimental techniques

### Documentation
- `REIT_SCRAPER_STATUS_REPORT.md` - Full status report
- `NEXT_STEPS_REIT_SCRAPERS.md` - This file

---

## Questions?

Contact: jeff@revopsimpact.com
Repo: `/Users/jeffignacio/mplc_pop_engine/MPLC`
Date: October 27, 2026
