# Religious Institutions Vertical — Detection Spec

**Status:** Planned (not yet validated)
**Volume:** 637 accounts (16.1% of corporate_accounts CSV)
**Priority:** #1 new vertical by account count
**Date drafted:** 2026-10-24

---

## Why This Vertical Exists

Religious institutions appeared in the corporate_accounts CSV because they fall under
the same broad "Commercial/Institutional" ROE umbrella as corporations. They were being
silently misrouted through the corporate pipeline, which uses Yelp as its primary
discovery channel. Churches rarely have Yelp pages, so Yelp-first detection produces
near-zero results for this segment.

---

## Evidence Standard

**What counts as PoP:**
- TV or large display in a public/communal area of the facility
- Specifically: sanctuary, fellowship hall, lobby/narthex, youth/family room, community room
- TV must be visible to congregants or visitors — not in a staff office or private area
- Powered-on preferred but static mount in a clearly communal space is acceptable as SUSPECT

**What does NOT count:**
- Projection screens used exclusively for sermon slides (not licensed TV use)
- Small monitors showing bulletins/directions at entry only
- Office/administrative screens

**Key ROE check needed:**
- Verify the actual ROE for religious facilities — license terms may differ from corporate
- Confirm whether sanctuary A/V systems are in or out of scope

---

## Account Breakdown (from corporate CSV)

Known account types in this segment:
- Baptist churches (multiple denominations)
- LDS / Mormon temples and meetinghouses
- Methodist churches
- Catholic parishes
- Megachurches (likely highest detection rate — more public photos)
- Smaller community churches (lowest detection rate)

**Segmentation hypothesis:**
- Megachurches (500+ seat capacity, well-known name) → higher Yelp/Google coverage
- Mid-size churches → website text mining most viable
- Small community churches → likely REJECTED or SUSPECT at best

---

## Discovery Channel Strategy

### Channel 1: Website Text Mining (PRIMARY — test first)
**Rationale:** ~93% of restaurants were detected via review text-mining. Churches
post publicly about A/V upgrades in newsletters, bulletins, and "what to expect" pages.
High-intent keywords signal real TV/display installations.

**Target URLs:**
- Church website `facilities`, `campus`, `visitor`, `about` pages
- Weekly bulletin PDFs (often linked from homepage)
- Google Maps listing description

**Detection keywords (high signal):**
- "flat screen" / "big screen" / "large screen"
- "television" / "TV" / "monitor" in context of common areas
- "livestream" / "live stream" screen in lobby/overflow room
- "A/V system" / "audio/visual" in facility context
- "overflow room" / "cry room" with screen/monitor
- "video announcement" / "announcement screen"

**Rejection keywords (sermon-only use, not TV):**
- "PowerPoint" / "sermon slides" only context
- "projector" as sole display (not TV)

**Expected coverage:** Unknown — first test at n=20 ground truth accounts

**Cost:** ~$0.005-0.010/account (text scraping only, no image API calls)

---

### Channel 2: Google Places Photos (SECONDARY)
**Rationale:** Google Maps often has interior photos submitted by visitors.
Megachurches and well-known congregations have significant photo coverage.

**Method:** Same Apify Business Scraper approach as corporate, but:
- Filter photos by interior category
- Focus on lobby, fellowship hall, main worship space captions
- YOLO TV pre-filter → VLM classification

**Expected coverage:** ~15-25% (estimated, not validated)
- Skews higher for megachurches, near zero for small community churches

**Cost:** ~$0.022/account (same as corporate channel)

---

### Channel 3: Facebook Page Photos (EXPLORATORY)
**Rationale:** Many churches maintain active Facebook pages and post interior
photos during events, renovations, and holiday services. These often show
fellowship hall setups with TVs visible.

**Method:** Not yet designed — would require Facebook scraping capability
(Apify has a Facebook scraper)

**Expected coverage:** Unknown
**Status:** Design later, after channels 1-2 are validated

---

## Recommended Pipeline Order

```
Account → Website text mine → FOUND? → PROSPECT/SUSPECT
                ↓ not found
        Google Places photos → TV detected? → PROSPECT/SUSPECT
                ↓ not found
        REJECTED (or Facebook if available)
```

Run text mining first: it's cheapest ($0.005) and the hypothesis is it has
the best signal for this vertical. Only call Google Places API if text mining
yields no result.

---

## Ground Truth Accounts Needed

**Before validation run:**
1. Pull a list of confirmed MPLC-licensed religious institutions from Salesforce
   (Account Status = "Licensed", Industry = "Religious Institutions")
2. If none exist, use 5-10 well-known megachurches as positive control
   (Lakewood Church, Saddleback, etc. — likely to have TVs in public areas)
3. Target n=20 minimum before reporting coverage numbers

**Failure mode to watch:**
- Projection screens for sermon slides misclassified as entertainment TVs
- VLM prompt must explicitly ask: "Is this a TV showing broadcast/cable content,
  or a projection screen showing presentation slides?"

---

## Cost Projections (537 accounts after skipping ~100 small-account rejects)

| Channel | $/account | 537 accounts | Notes |
|---------|-----------|--------------|-------|
| Text mining only | $0.008 | $4.30 | Primary pass |
| + Google Places | $0.022 | $11.80 | Secondary for text misses |
| Full dual-channel | $0.030 | $16.10 | Max cost if both channels run |

---

## Open Items Before Build

1. **ROE verification:** Get actual license terms for religious institutions from MPLC
2. **Ground truth:** Pull licensed religious accounts from Salesforce for validation
3. **Projection vs. TV disambiguation:** Test VLM prompt on known projection-only churches
4. **Facebook scraping:** Evaluate Apify Facebook actor cost/availability
5. **Megachurch vs. small church segmentation:** Does account name contain keywords
   that predict photo availability? (e.g., "Community Church" vs. a proper name)
