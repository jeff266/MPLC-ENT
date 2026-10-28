# Education Vertical — Detection Spec

**Status:** Planned (not yet validated)
**Volume:** 471 accounts (11.9% of corporate_accounts CSV)
**Priority:** #2 new vertical by account count
**Date drafted:** 2026-10-24

---

## Why This Vertical Exists

Education accounts appeared in the corporate CSV because they share the same
institutional ROE category. The corporate pipeline (Yelp-first) performs poorly
here because K-12 schools have almost no Yelp presence, and universities have
Yelp pages only for specific on-campus venues (dining halls, coffee shops), not
the institution itself.

---

## Sub-Segment Split (CRITICAL)

Education is not one vertical — it's two with very different detection strategies:

### Sub-Segment A: Universities & Colleges (~40% of education accounts)
- Public-facing student areas with high photo availability
- Student reviews on Google, Yelp (for dining), Niche.com
- Campus tour content on YouTube and official websites
- Expected detection rate: **25-40%** (comparable to corporate)
- Highest ROI sub-segment

### Sub-Segment B: K-12 Schools (~60% of education accounts)
- Elementary, middle, and high schools
- Very limited public photo evidence
- No Yelp presence, minimal Google photos
- Government-like in terms of access restrictions
- Expected detection rate: **<10%** — likely not worth dedicated pipeline cost
- **Recommendation:** Run text-mining pass only; skip image channels

**Implementation note:** Split on account name keywords before routing:
- University / College / Institute / Academy / Seminary → Sub-Segment A
- Elementary / Middle / High School / ISD / USD → Sub-Segment B

---

## Evidence Standard

**What counts as PoP:**
- TV in a student-facing communal space:
  - Student union / campus center lounge
  - Dining hall / cafeteria
  - Recreation center lobby or common area
  - Library study/lounge area
  - Dormitory common room
  - Athletic facility lobby
- Must be visible to students, not in classroom or faculty office

**What does NOT count:**
- Classroom projectors / smartboards (instructional use, not TV)
- Faculty/admin office monitors
- Digital signage with text-only announcements (no broadcast content)
- Scoreboard displays (athletic field — different ROE context)

**Key ROE check needed:**
- Verify license scope for educational institutions (student common areas vs. all campus)
- Classroom TVs may be explicitly excluded from license requirement

---

## Discovery Channel Strategy — Universities

### Channel 1: Website / Campus Tour Photos (PRIMARY)
**Rationale:** Universities actively market their facilities. Official campus tour pages,
virtual tours, and student life sections regularly show student union lounges, dining
halls, and rec centers — often with TVs visible.

**Target URLs:**
- `[university].edu/campus-life`, `/student-union`, `/dining`, `/recreation`
- Google Images: "[University Name] student union interior"
- Virtual tour platforms (YouVisit, Concept3D) — some scrapers available

**Detection keywords:**
- "lounge" / "common area" / "gathering space" with TV/screen mention
- "flat screen" / "big screen" in student areas
- "game room" / "rec center lounge"
- Facility descriptions mentioning A/V in student spaces

**Expected coverage:** ~20-30% (text + campus page photo scraping)

---

### Channel 2: Google Places / Yelp for On-Campus Venues (SECONDARY)
**Rationale:** Specific on-campus venues (dining halls, coffee shops, student unions)
often have their own Google Maps listings with photos from students.

**Method:**
- Search "[University] student union" / "[University] dining hall" on Google Places
- Pull photos, run YOLO + VLM
- Same pipeline as corporate channel

**Expected coverage:** ~15-25% additional lift for universities

**Cost:** ~$0.022/account

---

### Channel 3: Niche.com / College Confidential Reviews (EXPLORATORY)
**Rationale:** Students write detailed reviews of campus facilities on Niche.com,
mentioning TVs in dorms, student unions, and rec centers.

**Status:** Exploratory — requires scraping design, not yet in any pipeline

---

## Discovery Channel Strategy — K-12

### Channel 1: Text Mining Only
**Rationale:** K-12 schools have almost no image channels. Run a cheap text pass
to look for facility renovation announcements, PTA newsletters mentioning new TVs
in cafeterias, etc.

**Target:**
- School district website
- School Facebook page (if Apify Facebook actor available)
- Google Maps listing description

**Expected coverage:** 5-10% at best
**Cost:** ~$0.005/account

**If text mining yields nothing:** Classify as REJECTED. Do not escalate to image
channels for K-12 — cost/coverage ratio is unfavorable.

---

## Recommended Pipeline Order

```
Account → Sub-segment split (University vs. K-12)
              ↓                          ↓
    UNIVERSITY PATH               K-12 PATH
    Website text mine             Text mine only
         ↓                             ↓
    Google Places photos          REJECT if no text hit
         ↓
    PROSPECT/SUSPECT/REJECTED
```

---

## Ground Truth Accounts Needed

**Universities (positive control candidates):**
- Large state universities (UNC Chapel Hill, Ohio State, UCLA) — known to license
- Look for confirmed MPLC-licensed universities in Salesforce first

**Known accounts from CSV:**
- Case Western Reserve University (CWRU) — appeared as PROSPECT in batch run
- UNC (University of North Carolina)
- Western Washington University
- These can be initial validation targets

**K-12 (negative control):**
- Average elementary/middle school — expect REJECTED
- Use to calibrate false positive rate before scaling

---

## Cost Projections

### Universities (~185 accounts estimated)
| Channel | $/account | 185 accounts |
|---------|-----------|--------------|
| Text only | $0.008 | $1.48 |
| + Google Places | $0.022 | $4.07 |
| Full dual-channel | $0.030 | $5.55 |

### K-12 (~286 accounts estimated)
| Channel | $/account | 286 accounts |
|---------|-----------|--------------|
| Text only | $0.005 | $1.43 |
| Total K-12 | — | **$1.43** |

**Total education vertical cost: ~$7/full run**

---

## Open Items Before Build

1. **ROE verification:** Confirm license scope for educational institutions
2. **Sub-segment keywords:** Build keyword list to reliably split University vs. K-12
   from account name alone
3. **CWRU validation:** CWRU appeared as PROSPECT in batch run — manually verify
   that evidence is a real student-facing space, not a classroom
4. **K-12 go/no-go decision:** Confirm with MPLC whether K-12 is worth pursuing
   given low expected coverage
5. **Campus tour scraping:** Evaluate whether virtual tour platforms (YouVisit, etc.)
   are scrapable or have an API
