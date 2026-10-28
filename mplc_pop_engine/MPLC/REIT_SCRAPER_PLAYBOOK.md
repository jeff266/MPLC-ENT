# REIT Scraper Playbook - Quick Reference

**When a REIT scraper has dynamic content issues, follow this order:**

---

## 1. Sitemap Approach (FASTEST - Try First)

**Success:** Camden, UDR (2/2 = 100% success rate)
**Speed:** 0.2-4.5 seconds
**Complexity:** Low

### Quick Check
```bash
curl https://www.{reit}.com/sitemap.xml
curl https://www.{reit}.com/robots.txt  # Check for sitemap reference
```

### Common Patterns
```
# Full sitemap
https://www.{reit}.com/sitemap.xml

# Specific sitemaps
https://www.{reit}.com/sitemap/properties.xml
https://www.{reit}.com/sitemap/communities.xml
https://www.{reit}.com/sitemap/community-landing-pages.xml
```

### Implementation Template
```python
import requests
import re

def scrape_from_sitemap(sitemap_url, path_segments=3):
    resp = requests.get(sitemap_url)
    urls = re.findall(r'<loc>(.*?)</loc>', resp.text)

    properties = []
    for url in urls:
        path = url.replace('https://domain.com/', '')
        segments = [s for s in path.strip('/').split('/') if s]

        if len(segments) == path_segments:
            # Parse URL for data
            properties.append({
                'reit': 'REIT Name',
                'community_name': extract_name(url),
                'city': extract_city(url),
                'state': extract_state(url),
                'property_url': url,
            })

    return properties
```

### When to Use
- Website has structured property portfolio
- Sitemap exists and is accessible
- URLs follow predictable patterns
- Need complete property list

---

## 2. Embedded JSON Extraction (FAST - Try Second)

**Success:** Equity Residential (1/1 = 100% success rate)
**Speed:** 1-2 seconds
**Complexity:** Medium

### Quick Check
```bash
# View page source and search for:
curl -s https://www.{reit}.com/properties | grep -o "var.*=.*\[{.*}\]"
```

### Common Patterns
```javascript
// Look for embedded data structures
window.__INITIAL_STATE__ = {...}
ea5.siteSearch = [{...}]
var propertyData = [{...}]
window.PROPERTIES = [{...}]
```

### Implementation Template
```python
import cloudscraper
import re
import json

scraper = cloudscraper.create_scraper()
resp = scraper.get(url)
html = resp.text

# Find embedded JSON
pattern = r'variableName\s*=\s*(\[.*?\]);'
match = re.search(pattern, html, re.DOTALL)

if match:
    data = json.loads(match.group(1))
    # Parse JSON structure
```

### When to Use
- Sitemap doesn't exist
- Page has Cloudflare protection
- Data is embedded in JavaScript
- Single page contains all data

---

## 3. API Endpoint Discovery (MEDIUM - Try Third)

**Success:** Not yet validated
**Speed:** <1 second (if found)
**Complexity:** Medium-High

### Discovery Process
1. Open website in browser
2. Open DevTools → Network tab
3. Filter: XHR/Fetch
4. Navigate to property search
5. Look for JSON responses

### Common Endpoints
```
/api/properties
/api/communities
/api/search
/graphql
```

### Implementation Template
```python
import requests

# Direct API call
resp = requests.get('https://www.{reit}.com/api/properties')
data = resp.json()

# Parse API response
for item in data['properties']:
    properties.append({
        'reit': 'REIT Name',
        'community_name': item['name'],
        'city': item['city'],
        'state': item['state'],
        'property_url': item['url'],
    })
```

### When to Use
- Modern React/Vue SPA website
- No sitemap available
- Need real-time data
- API is not authenticated

---

## 4. Playwright Automation (SLOW - Last Resort)

**Success:** AvalonBay, Essex, MAA (3/3 = 100% but slow)
**Speed:** 20-60 seconds
**Complexity:** High

### Implementation Template
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    page.goto(url, wait_until='networkidle')
    page.wait_for_selector('.property-card', timeout=10000)

    # Scroll if needed
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(3)

    html = page.content()
    browser.close()

    # Parse HTML
```

### When to Use
- ALL other methods failed
- True JavaScript rendering required
- No API or sitemap available
- Willing to trade speed for completeness

---

## Decision Flowchart

```
REIT Scraper Failing?
│
├─→ Check sitemap.xml
│   └─→ EXISTS? → Use Sitemap Approach (0.2-4.5s) ✅
│
├─→ Check page source for embedded JSON
│   └─→ FOUND? → Use JSON Extraction (1-2s) ✅
│
├─→ Check DevTools for API endpoints
│   └─→ FOUND? → Use API Approach (<1s) ✅
│
└─→ None of the above?
    └─→ Use Playwright (20-60s) ⚠️
```

---

## Success Metrics by Technique

| Technique | Speed | Reliability | Maintenance | Success Rate |
|-----------|-------|-------------|-------------|--------------|
| Sitemap | ⚡⚡⚡ | ✅✅✅ | Easy | 100% (2/2) |
| JSON | ⚡⚡ | ✅✅✅ | Medium | 100% (1/1) |
| API | ⚡⚡⚡ | ✅✅ | Medium | TBD |
| Playwright | ⚡ | ✅✅ | Hard | 100% (3/3) |

---

## Validated Solutions by REIT

| REIT | Technique | Properties | Time | Status |
|------|-----------|------------|------|--------|
| Camden | Sitemap | 170 | 4.5s | ✅ |
| UDR | Sitemap | 172 | 0.2s | ✅ |
| Equity | JSON | 539 | 1.2s | ✅ |
| AvalonBay | Playwright | ~300 | 30s | ✅ |
| Essex | Playwright | ~250 | 25s | ✅ |
| MAA | HTML Sitemap | ~300 | 10s | ✅ |

---

## Testing Checklist

Before declaring a fix complete:

- [ ] Captures target number of properties (check investor docs)
- [ ] All required fields present (reit, name, city, state, url)
- [ ] Execution time acceptable (<30s ideal)
- [ ] Runs reliably (test 3+ times)
- [ ] Data quality verified (spot check 10 random properties)
- [ ] Integrates with other scrapers (no conflicts)
- [ ] Documentation updated

---

## Files to Update

When fixing a REIT scraper:

1. **Code:** `/Users/jeffignacio/mplc_pop_engine/MPLC/scrape_all_reits.py`
   - Update scraper class
   - Test integration

2. **Documentation:** Create fix summary
   - `{REIT}_SCRAPER_FIX_COMPLETE.md` (detailed)
   - `{REIT}_FIX_SUMMARY.md` (executive)
   - `{REIT}_FIX_COMPARISON.txt` (visual)

3. **This Playbook:** Update success metrics table

---

## Quick Test Command

```bash
cd /Users/jeffignacio/mplc_pop_engine/MPLC

# Test single REIT
python3 -c "from scrape_all_reits import {REIT}Scraper; print(len({REIT}Scraper().scrape()))"

# Test integration
python3 scrape_all_reits.py
```

---

## Next Steps for UDR Fix

✅ Fix complete
✅ Integration tested
✅ Documentation created
✅ Playbook updated

**Remaining REITs to optimize:**
- [ ] Essex Property Trust (check for sitemap first)
- [ ] AvalonBay Communities (check for sitemap first)

Both currently use Playwright - may be candidates for sitemap approach.

---

**Last Updated:** October 27, 2026
**Maintained By:** PoP Detection Engine Team
