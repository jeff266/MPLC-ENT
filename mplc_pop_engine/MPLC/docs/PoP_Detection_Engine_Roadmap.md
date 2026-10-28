# PoP Detection Engine — Product Roadmap & Project Plan

*As of 22 Oct 2026 · prepared with Claude*

## Vision & North Star

**Vision:** replace Brittany's manual PoP (Proof of Performance) detection work with an automated pipeline that screens MPLC's target accounts across every industry vertical and produces sales-ready, documented evidence of public TV display, at a fraction of the cost of manual search.

**North Star metric:** cost per verified Prospect-tier lead, tracked per vertical. A Prospect-tier result is one a rep can act on without re-checking: a real image, a real source URL, in a space that meets the vertical's actual evidence standard.

**Current baseline, by vertical:**

| Vertical | Validated coverage | Cost per account screened | Status |
| --- | --- | --- | --- |
| Restaurants/bars | ~93% | n/a (pre-existing pipeline) | Solved |
| Corporate (ENT) | 16.7% (n=42) | ~$0.022 | Validated |
| Auto dealerships | 30.0% (n=10) | ~$0.119 | Exploratory, no confirmed customer |
| Dental | 0% (2 channels tested) | ~$0.02–$0.14 | Ruled non-viable so far |
| Healthcare | Untested | — | Largest real segment (~45% of customers) |
| MDU | Untested | — | Promising hypothesis, no pilot run |

**Open input needed:** Brittany's fully-loaded cost per lead (time plus salary) isn't known yet. Getting that number turns "cost per verified lead" from a standalone metric into a direct automation ROI comparison.

## Pipeline Architecture

Five stages take an account from a weekly Salesforce extract to either a Prospect lead or a Mystery Shopper visit:

1. **Salesforce Extract + EDGAR Join** — weekly CSV, employee-count backfill, 90-day reuse cache
2. **ROE Segmentation** — SB / MM / ENT by industry rule (employee or location count)
3. **Vertical Pipeline Router** — routes to Corporate · Dental · Auto · Healthcare · MDU
4. **Three-Tier Evidence Labeling** — Prospect / Suspect / Rejected, each with saved evidence
5. **Outcome fork:**
   - **5a. Prospect → Sales** — sales-ready, documented evidence
   - **5b. Suspect (geo-clustered) → Mystery Shopper** — in-person premises validation

Accounts flow from the weekly Salesforce+EDGAR extract through ROE segmentation and a vertical-specific router, get labeled Prospect / Suspect / Rejected with saved evidence, and Prospect leads go to sales while geo-clustered Suspects route to the Mystery Shopper program for an in-person check.

*(An interactive diagram of this flow is maintained in the companion Claude Docs artifact: [PoP Detection Engine — Product Roadmap & Project Plan](https://claude.ai/artifact/PNAiDmxBFWKDbo6X5oa3cz).)*

## Current State by Vertical

| Vertical | Status | Key finding | Next step |
| --- | --- | --- | --- |
| Restaurants/bars | Solved (pre-existing) | ~93% via review text-mining; used as a positive control for this pipeline (4/5 on sports bars) | None, maintain as-is |
| Corporate (ENT) | Validated | 16.7% Prospect at n=42 real customers; two earlier claims (100%, 70%) collapsed on manual review | Scale to the full qualifying list once Steps 1–2 are built |
| Auto dealerships | Exploratory | 30.0% Prospect via Yelp photos (n=10, no confirmed MPLC customer); marketing-channel false positives (vehicle infotainment screens) unresolved | Get a confirmed MPLC dealership account if one exists; fix the marketing channel with a vehicle-interior pre-check |
| Dental | Non-viable (2 channels) | 0% via text-mining and Yelp photos on real, verified DSO locations (PDS confirmed as a paying customer) | Try the marketing/local-press channel before closing this out fully |
| Healthcare | Untested | ~45% of the real customer base, the single largest segment | First-principles pilot; likely a waiting-room standard, not employee-only |
| MDU | Untested | Hypothesis: luxury operators market their own amenities, unlike corporate or dental | Pilot once a real account list is available |

## Phased Roadmap

**Phase 1 — Foundation (next)**
1. Build Step 1: weekly Salesforce CSV ingestion into Python, joined against the local EDGAR employee-count file (robust name/entity matching, not exact string match)
2. Build Step 2: a precise MM/ENT/SB classifier encoding the exact ROE industry exceptions (Corporate uses global headcount; MDU by location count; Healthcare outpatient vs. inpatient; Hospitals 3,000+ for ENT)
3. Build the enrichment ledger (SQLite, portable to droplets later): a dedup check before any paid enrichment call, 90-day default freshness window
4. Flag "Unclassified — missing employee count" explicitly rather than dropping or guessing

**Phase 2 — Routing and scale-up**
1. Build Step 3: the account router that dispatches a classified account to its vertical pipeline
2. Scale the corporate pipeline to the full qualifying account list
3. Fix the auto marketing channel (vehicle-interior pre-check) and re-validate
4. Pilot healthcare and MDU, with each vertical's evidence standard confirmed against the ROE first

**Phase 3 — Mystery Shopper integration**
1. Define the "moderate probability" threshold (likely the Suspect tier, or a confidence sub-range within it)
2. Build geographic clustering logic for Suspect-tier accounts
3. Design the handoff format to the Mystery Shopper program (address, what to check, reporting results back into the ledger)

**Phase 4 — Infrastructure migration**
1. Move the pipeline from local build to DigitalOcean droplets
2. Confirm throughput at full account-list scale (118 accounts/hour single-worker held at n=42; re-verify at larger n)
3. Set up team dev access (droplet-per-person plus Tailscale)

## QA & Evaluation Framework

Every coverage or cost claim from any pipeline must clear this bar before it's trusted:

- [ ] Real, saved evidence exists (image, source URL) for every Prospect/Suspect, not just a summary percentage
- [ ] A failed or errored API call is excluded from the denominator, never counted as a clean Rejected
- [ ] Validation uses real, confirmed ground-truth accounts (existing paying customers) where available, not convenient or famous substitutes
- [ ] Any "ROE-adjusted" evidence standard is checked against the actual ROE text, not assumed
- [ ] Small-sample results (n<20) are explicitly labeled directional, with a plan to retest at larger n before being used for planning
- [ ] A VLM prompt fix is spot-checked against real examples after the fix, never trusted on the strength of the instruction alone
- [ ] Entity attribution (is this account actually, currently affiliated with the parent brand/DSO/dealership group being tested) is verified against an authoritative source, not a generic search result

This list is maintained in the project's `PoP_Detection_Engine_Learnings.md` doc and should grow as new failure patterns are found.

## Risks & Open Questions

- No live Salesforce connection: the weekly CSV export is the working plan; confirm this stays sufficient as the pipeline scales
- Employee-count data gaps: many accounts have blank counts; EDGAR only covers public companies, so private-company counts still need another method
- Entity-resolution risk recurs in every multi-location vertical: DSOs, dealership groups, and likely MDU property portfolios all share the same parent-brand-vs-real-location attribution problem
- No confirmed MPLC customer for auto dealerships or MDU: exploratory samples for both carry real but lower confidence than the corporate and dental ground-truth results
- Vehicle-interior false positives: the marketing/image-search channel misclassifies vehicle dashboards as facility TVs; a fix is scoped (multi-stage VLM) but not yet built or verified
- The "209-account" list and the 123-row MM+ CSV are two different, not-yet-reconciled populations: don't conflate them when projecting scale or cost
- Mystery Shopper program details (cost per visit, turnaround time, reporting format back into the pipeline) aren't defined yet

## Local Repo Formalization

To keep the build disciplined as it grows, the actual code repository (where Claude Code implements this) should get:

**`CLAUDE.md`** — project context, the 5-stage architecture, the exact ROE/MM-ENT rules, and the QA checklist above, so every session starts from the same ground truth instead of re-deriving it.

**A `ground_truth/` fixture set** — the confirmed real accounts validated so far (Cigna, PNC, Costco for corporate; PDS/Smile Generation for dental; the 5-location sports-bar positive control) kept as a standing regression set, re-run whenever a VLM prompt or channel changes.

**A QA/validation harness** — a lightweight script or checklist that enforces the evidence-persistence schema is complete (photo location, description, confidence, source URL, space type, TV on/off, cost, enrichment date) before any batch result is accepted, and that flags any claim missing saved evidence.

**North Star tracking** — a simple running log (even a CSV) of cost-per-verified-lead by vertical and by pilot date, so the corporate numbers (16.7% at n=42) and future reruns stay comparable over time, not just point-in-time claims.

**This doc (`PoP_Detection_Engine_Learnings.md`, in the MPLC project)** stays the source of truth for validated findings and the process-discipline list; the repo's `CLAUDE.md` should point to it rather than duplicating it, so there's one place to update.
