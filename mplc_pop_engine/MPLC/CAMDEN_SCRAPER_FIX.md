# Camden Property Trust Scraper - Fix Documentation

## Problem Statement

Camden's website (https://www.camdenliving.com) uses heavy JavaScript rendering to display property listings. The original scraper implementation attempted to:

1. Load the `/apartments` page with Playwright
2. Scroll to trigger lazy loading
3. Parse property links from the rendered HTML

**Result:** Only ~7 properties captured (out of ~180 expected)

## Investigation Process

### Approach 1: API Endpoint Discovery (SUCCESSFUL)

Used Playwright to monitor network traffic while loading the apartments page:

```javascript
// Discovered GraphQL API endpoint
https://api.camdenliving.com/graphql
```

The API uses GraphQL queries, but after testing various queries:
- `getDBCommunities` returns only property names (no URLs)
- URL fields are not exposed in the API schema
- Not viable for complete property scraping

### Approach 2: Sitemap Discovery (SOLUTION)

Checked Camden's sitemap structure:

```bash
https://www.camdenliving.com/sitemap.xml
```

Found a dedicated community sitemap:

```bash
https://www.camdenliving.com/sitemap/community-landing-pages.xml
```

**Result:** Complete list of all 170 Camden properties with full URLs

## Solution Implementation

### New Scraper Design

```python
class CamdenScraper(REITScraper):
    """Camden Property Trust scraper - uses sitemap for complete property list."""

    def scrape(self) -> List[Dict]:
        # Fetch XML sitemap
        sitemap_url = "https://www.camdenliving.com/sitemap/community-landing-pages.xml"
        html = self.fetch_page(sitemap_url, wait_time=3)

        # Parse with BeautifulSoup XML parser
        soup = BeautifulSoup(html, 'xml')
        location_tags = soup.find_all('loc')

        # Extract property info from URL pattern
        # Pattern: /apartments/{city-state}/camden-{property}
        for loc_tag in location_tags:
            url = loc_tag.get_text(strip=True)
            # Parse city, state, property name from URL
            # Store structured data
```

### URL Pattern Parsing

Camden URLs follow this pattern:
```
https://www.camdenliving.com/apartments/{city-state}/camden-{property-name}
```

Examples:
- `/apartments/houston-tx/camden-memorial-heights`
- `/apartments/atlanta-ga/camden-phipps`
- `/apartments/washington-dc/camden-roosevelt`

Parsing logic:
1. Extract location: `houston-tx`
2. Split on hyphen: `['houston', 'tx']`
3. Last segment = state code: `TX`
4. Remaining segments = city: `Houston`
5. Property slug: `memorial-heights` → `Camden Memorial Heights`

## Results

### Performance Comparison

| Metric | Before (JavaScript) | After (Sitemap) |
|--------|---------------------|-----------------|
| Properties Captured | 7 | 169 |
| Execution Time | ~30+ seconds | ~5 seconds |
| Success Rate | 4% | 99.4% |
| Method | Playwright + scroll | XML parsing |
| Reliability | Low (JS-dependent) | High (static XML) |

### Coverage by State

| State | Properties |
|-------|------------|
| Texas | 47 |
| Florida | 31 |
| North Carolina | 27 |
| Georgia | 14 |
| Arizona | 12 |
| Colorado | 9 |
| Virginia | 8 |
| California | 8 |
| Tennessee | 5 |
| DC | 4 |
| Maryland | 4 |

**Total:** 169 properties across 11 states

### Sample Output

```python
{
    'reit': 'Camden',
    'community_name': 'Camden South Capitol',
    'city': 'Washington',
    'state': 'DC',
    'property_url': 'https://www.camdenliving.com/apartments/washington-dc/camden-south-capitol'
}
```

## Key Learnings

### When JavaScript Scraping Fails

1. **Check for API endpoints first**
   - Open browser DevTools → Network tab
   - Look for XHR/Fetch requests with JSON data
   - May provide structured data without scraping

2. **Check sitemap.xml**
   - Most modern sites have XML sitemaps
   - Often contain complete URL listings
   - Easy to parse with BeautifulSoup XML parser

3. **Sitemaps are preferable to API scraping**
   - No authentication required
   - Stable, documented format
   - Designed for crawlers (robots.txt compliant)

### Sitemap Advantages

- **Performance:** XML parsing is 6x faster than browser automation
- **Reliability:** No JavaScript dependencies
- **Completeness:** Sitemaps list all public pages
- **Simplicity:** Straightforward parsing logic
- **Maintenance:** Less likely to break with UI changes

## Testing

### Test Script

```bash
python3 test_camden_scraper.py
```

### Expected Results

- Total properties: 169 (out of 170 in sitemap)
- Status: PASS if >= 150 properties
- Execution time: ~5 seconds
- No errors or warnings

### Verification

```python
from scrape_all_reits import CamdenScraper

scraper = CamdenScraper(max_cities=999)
properties = scraper.scrape()
assert len(properties) >= 150, "Camden scraper failed"
```

## Integration

### Updated Configuration

In `scrape_all_reits.py`:

```python
scrapers = [
    AvalonBayScraper(max_cities=50),
    CamdenScraper(max_cities=999),  # No limit needed - sitemap has all
    MAAScraper(max_cities=999),
    UDRScraper(max_cities=50),
    EquityResidentialScraper(max_cities=50),
    EssexScraper(max_cities=50),
]
```

### Output Format

All scrapers produce consistent output for downstream processing:

```python
{
    'reit': str,            # REIT name
    'community_name': str,  # Property name
    'city': str,            # City name
    'state': str,           # State code
    'property_url': str,    # Full URL
}
```

## Future Enhancements

### Potential Improvements

1. **Add error handling for missing location components**
   - Some URLs may have non-standard patterns
   - Currently assumes `{city}-{state}` format

2. **Validate state codes**
   - Check against known US state codes
   - Flag anomalies for manual review

3. **Cache sitemap locally**
   - Reduce redundant fetches during development
   - Respect crawl delays

4. **Add property metadata**
   - Could fetch individual property pages for details
   - Number of units, amenities, etc.

### Other REITs with Similar Patterns

Consider sitemap approach for:
- UDR Inc (if available)
- Equity Residential (if available)
- Essex Property Trust (if available)

## References

- **Camden Sitemap:** https://www.camdenliving.com/sitemap.xml
- **Community Pages:** https://www.camdenliving.com/sitemap/community-landing-pages.xml
- **GraphQL API:** https://api.camdenliving.com/graphql (discovered but not used)

## Status

✓ **COMPLETE** - Camden scraper fully functional and integrated

**Last Updated:** 2026-10-27
**Author:** Claude Code (via Jeff Ignacio)
**File:** `/Users/jeffignacio/mplc_pop_engine/MPLC/scrape_all_reits.py`
