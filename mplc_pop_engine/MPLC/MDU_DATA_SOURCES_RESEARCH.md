# MDU Data Sources Research - Hotel/Property Verification
**Research Date:** October 25, 2026
**Purpose:** Document data sources for MDU (hotel) property verification, ownership lookup, and location validation

---

## 1. Hotel Brand Franchise Disclosure Documents (FDDs)

### Overview
Franchise Disclosure Documents (FDDs) contain Item 20 sections with comprehensive outlet counts and location data for hotel brands. These are official filings required by the FTC.

### Major Hotel Brands - Direct Download Sources

#### Hilton Brands
- **Official Source:** Hilton Corporate Disclosure Documents Portal
  - URL: https://www.hilton.com/en/corporate/disclosure-documents/
  - Direct PDF downloads available for all brands

- **Brands & 2026 FDDs:**
  - Hilton: https://hmd-wp.go-vip.net/wp-content/uploads/2026/07/2026-US-FDD-Hilton-.pdf
  - DoubleTree: https://hmd-wp.go-vip.net/wp-content/uploads/2026/03/2026-US-FDD-DoubleTree.pdf
  - Hampton Inn: Available on main portal
  - Hilton Garden Inn: 759 outlets (Item 20)
  - Home2 Suites: Available on main portal
  - LXR: https://hmd-wp.go-vip.net/wp-content/uploads/2026/06/2026-US-FDD-LXR_2.pdf

- **Typical Investment:** $50M-$213M for 300-room Hilton property
- **FDD Format:** 400+ page PDF with Item 20 outlet counts

#### IHG Brands
- **Download Sources:**
  - ResearchForSale.com: Holiday Inn FDD (2015-2026 editions, 536 pages, April 2026 issue)
  - GetFDD.com: Holiday Inn (effective 04/16/2025, expires 04/16/2026)
  - FranchiseOverview.com: Free download available
  - FranchiseGenius.com: Purchase required

- **Brands:**
  - Holiday Inn: 2,340 outlets (Item 20, 2026 FDD)
  - Holiday Inn Express: 2,340 outlets
  - Holiday Inn Resort
  - Candlewood Suites

- **Typical Investment:** $18.6M - $29.2M
- **URL:** https://researchforsale.com/downloads/holiday-inn-holiday-inn-suites-holiday-inn-resort-fdd/

#### Hyatt Brands
- **FDD Details:**
  - Hyatt Place: 347 locations (Item 20), filed March 29, 2026
  - 404-page PDF
  - Investment: $23.4M - $29.9M
  - Royalty: 5% of Gross Rooms Revenue
  - Ad Fund: 3.5% of gross sales

- **Download Source:** ResearchForSale.com (2015-2026 editions)
- **URL:** https://researchforsale.com/downloads/hyatt-place-hotels-fdd/

#### Choice Hotels Brands
- **Official Contact:**
  - Choice Hotels International
  - 1 Choice Hotels Circle, Suite 400, Rockville, MD 20850
  - Email: development@choicehotels.com

- **Brands:**
  - Comfort Inn: $822K - $3.3M investment (April 2026 FDD)
  - Quality Inn: 1,566 outlets (Item 20, 2026 FDD)
  - Comfort Suites

- **Download Sources:**
  - FranchiMP: https://www.franchimp.com/ (2026 versions available)
  - ResearchForSale: 2016-2026 editions

- **URL:** https://researchforsale.com/downloads/comfort-inn-fdd/

#### Marriott Brands
- **Official Source:** Marriott Hotel Development Portal
- **Direct Downloads (2026 FDDs):**
  - Courtyard: https://www.hotel-development.marriott.com/ResourceFiles/2026-fdd-document/2026-courtyard-fdd-3-31-2026.pdf
  - Element: https://www.hotel-development.marriott.com/ResourceFiles/2026-fdd-document/2026-element-by-marriott-fdd-3-31-2026.pdf

- **2026 Outlet Counts (Item 20):**
  - Marriott Hotels: 369 locations
  - Courtyard: Investment $15.1M - $35.6M
  - Residence Inn: 889 outlets
  - SpringHill Suites: 579 outlets

- **Royalty Structure:** 6% + 2% brand fund contribution

### Free Official FDD Sources (State Databases)

#### California
- **Portal:** CA Department of Financial Protection & Innovation Self Service Portal
- **Search Method:** Type franchise name in 'Legal Name', select "Uniform Franchise Registration"
- **URL:** Available through CA DFPI portal

#### Indiana
- **Portal:** Indiana Secretary of State Securities Portal
- **Search Method:** Select "franchise" under 'Registration Type', type franchisor name
- **Coverage:** All registered franchises

#### Minnesota
- **Portal:** Minnesota Commerce Department Commerce Actions and Regulatory Documents Search
- **Search Method:** Select "Franchise Registrations" under 'Area of Interest'
- **URL:** Available through MN Commerce Dept

#### Wisconsin
- **Portal:** Wisconsin Department of Financial Institutions Franchise Registration Search
- **Search Method:** Type franchisor name under 'Name (Legal or Trade)'
- **Coverage:** All registered franchises

### Third-Party FDD Aggregators
- **Franchimp:** Free credits, extensive database (18,000+ FDDs)
  - URL: https://www.franchimp.com/?page=fdd
- **ClearlyFDD:** Comparative analysis tools, year-over-year FDD comparison
- **FranchiseGenius:** Purchase required
- **ResearchForSale:** Instant PDF downloads, historical editions

---

## 2. County Deed Lookup APIs

### Regrid API
**Service:** National parcel data platform with REST APIs

**Coverage:**
- 150+ million U.S. parcels
- All U.S. counties + Canadian provinces
- Daily ownership updates

**Data Available:**
- Parcel boundaries (GeoJSON)
- Ownership details
- Zoning information
- Assessed values
- Deed records
- Building footprints
- Standardized zoning

**Search Methods:**
- Location coordinates
- Address
- APN (Assessor's Parcel Number)
- Owner name
- Polygon area

**Pricing (2026):**
- **Self-serve API Plans:**
  - Included: 2,000 parcel records + 200,000 tiles/month
  - Overages: $0.10/Standard record, $0.15/Premium record, $0.001/tile

- **App Pricing:**
  - Starter: Free (25 lookups/day)
  - Pro: $10/month or $100/year (1,000 lookups/day, premium fields)
  - Team: $20/user/month (2,000 lookups/day)

- **Enterprise:** Custom packages for bulk/high-volume use
- **Free Trial:** 30-day sandbox

**API Documentation:** https://regrid.com/parcel-api

**Resources:**
- [Regrid Parcel API](https://regrid.com/parcel-api)
- [Property Data API Costs Comparison](https://www.vahorizon.site/blog/property-data-api-costs-for-wholesalers/)

---

### ATTOM Data Solutions API
**Service:** Comprehensive property-centric data covering 160+ million U.S. properties

**Coverage:**
- Residential & commercial real estate nationwide
- Sales history
- Property transfers
- Mortgage data
- Foreclosure transactions
- iBuyer trends

**Data Available:**
- Recorder deed data
- Loan positions
- Sales prices
- Transaction dates
- Price per square foot
- Property characteristics

**API Endpoints:**
- `/property/snapshot` - Property details
- `/sale/snapshot` - Sales history

**Pricing (2026):**
- **Starting Price:** $499/year
- **API Access:** Custom quotes based on:
  - Monthly transactions volume
  - Dataset coverage needed
  - Update frequency
  - Properties returned (per-property billing)
- **Typical Range:** ~$500/month for basic access
- **Free Trial:** 30-day trial available

**Resources:**
- [ATTOM API 2026 Overview](https://zillapi.com/blog/attom-api/)
- [ATTOM Data Pricing 2026](https://marketintelligencetools.com/reports/attom-data-pricing/)
- [Property Transactions Data](https://www.attomdata.com/data/transactions-mortgage-data/)

---

### DataTree by First American
**Service:** Direct-from-county property data platform

**Coverage:**
- 100% of U.S. housing stock
- 7+ billion recorded document images

**Coverage Breakdown:**
- Property ownership: 100%
- Deeds, mortgages, foreclosures: 99%
- Assignments & lien releases: 96%
- Map & parcel boundaries: 99%
- Active real estate listings: 85%

**Data Available:**
- Property ownership records
- Deed images
- Mortgage documents
- Foreclosure records
- Lien releases
- Parcel boundaries
- Active listings

**Pricing (2026):**
- **Quote-based:** No published pricing
- **Online Store Plans:**
  - Basic: $97/month
  - Plus: $147/month
  - Premium: $197/month
- **Enterprise:** Custom per-user, per-document pricing
- **API Access:** Available for larger institutions
- **Batch Export:** Available

**Notes:**
- Premium pricing due to direct-from-county reliability
- Contracts can be complex for smaller entities
- Expensive for high-volume bulk pulls at non-enterprise levels

**Resources:**
- [DataTree Geocoverage](https://web.datatree.com/home/geocoverage)
- [DataTree Review 2026](https://cresoftware.tech/products/datatree/)

---

### County-Specific APIs (Major Hotel Markets)

#### Los Angeles County
**Official Sources:**
- **Assessor:** assessor.lacounty.gov (assessment records, AIN lookup)
- **Registrar-Recorder:** lavote.gov/home/recorder (deeds, mortgages, liens)

**Search Methods:**
- By Name (Grantor/Grantee)
- By Assessor's Identification Number (AIN)
- By Document Number

**API Status:** No public API documented; contact County Recorder for programmatic access

**Data Available:**
- Deeds
- Liens
- Mortgages
- Assessment values
- Parcel maps
- Property characteristics

**Resources:**
- [LA County Property Records 2026](https://www.searchsystems.net/us/ca/county/los-angeles/property-records)
- [NETR Online LA County Index](https://datastore.netronline.com/losangeles)

---

#### New York County (Manhattan)
**System:** ACRIS (Automated City Register Information System)

**Coverage:**
- Manhattan, Bronx, Brooklyn, Queens
- Records back to 1966 for Manhattan
- Last updated: October 8, 2026

**Search Methods:**
- Party name
- BBL (Borough, Block, Lot)
- Document type
- Document ID
- Transaction number

**API Access:**
- **OData Endpoint:** Available via NYC Open Data portal
- **Dataset:** ACRIS DEEDs
- **URL:** https://data.cityofnewyork.us/City-Government/ACRIS-DEEDs/vayk-bjrk
- **Integration:** Excel, Tableau (OData connector)

**Cost:** Free

**Additional Data:**
- Land Records publishes NYC parcel data: 178,247 property records with GIS boundaries

**Resources:**
- [ACRIS Official](https://www.nyc.gov/site/finance/property/acris.page)
- [ACRIS DEEDs Dataset](https://data.cityofnewyork.us/City-Government/ACRIS-DEEDs/vayk-bjrk)

---

#### Miami-Dade County
**Official Sources:**
- **Clerk of Court:** onlineservices.miamidadeclerk.gov (deeds, mortgages, liens)
- **Property Appraiser:** Assessment records, property search

**Search Methods:**
- Address
- Folio number
- Owner name
- ZIP code

**API Options:**
- **Apify Miami-Dade Property Records API:**
  - Address lookup
  - Folio number search
  - Returns: beds, baths, value, last sale, FEMA flood zone, permits, violations, lead score
  - URL: https://apify.com/open-records-data/miami-dade-property-records

**Official Records:**
- Online Records Search System (free)
- In-person requests
- Mail/email requests

**Resources:**
- [Miami-Dade Property Search](https://miamidadepropertysearch.us/)
- [Apify Miami-Dade API](https://apify.com/open-records-data/miami-dade-property-records)

---

#### Cook County (Chicago)
**Official Sources:**
- **Recorder:** cookcountyclerkil.gov/recordings (deeds, mortgages, liens)
- **Supervisor of Assessments:** Assessment records

**Tools:**
- **Cook County Clerk Property Records Search:** https://crs.cookcountyclerkil.gov/Search
  - Indexed through October 8, 2026
  - Search by: PIN, name, address, document number

- **CookViewer 3.0:** Web map solution
  - URL: https://maps.cookcountyil.gov/cookviewer/
  - Links to Treasurer, Assessor, Board of Review data
  - Property comparison tools

**Search Methods:**
- 14-digit PIN
- Property address
- Owner name

**API Status:** No specific API documented; contact Clerk's office for programmatic access

**Resources:**
- [Cook County Property Records 2026](https://www.searchsystems.net/us/il/county/cook/property-records)
- [CookViewer](https://maps.cookcountyil.gov/cookviewer/)

---

#### San Francisco County
**Official Portal:** Expanded in March 2026

**Official Sources:**
- **Assessor-Recorder:** online.sfassessor.org/s/rp-property-search (assessment info)
- **Recorder:** recorder.sfgov.org (deeds, recorded documents)
- **SF Property Information Map (PIM):** sfplanninggis.org/pim/ (parcel maps, zoning)

**Search Tools:**
- **Records Manager Tool:**
  - Documents from 1990 onward
  - Search by: name, document type, document number, APN

- **Recorder Public Index:**
  - Grantor/Grantee name search

**API Status:** Contact Assessor-Recorder office for API access

**Third-Party Services:**
- PropertyShark
- California Property Checker

**Resources:**
- [SF Assessor Property Search](https://californiacountyassessor.org/san-francisco-county-assessor/)
- [SF Property Records Announcement](https://www.sfchronicle.com/sf/article/sf-property-records-19998025.php)

---

## 3. State Liquor License Databases

### Overview
**Key Finding:** No national database exists - each state runs its own database through ABC board, liquor authority, or licensing division.

### States with Online Searchable Databases & APIs

#### New York State
**Authority:** New York State Liquor Authority (SLA)

**Datasets Available:**
- **Current Liquor Authority Active Licenses**
  - Dataset ID: 9s3h-dpkz
  - Last updated: October 22, 2026
  - Includes: Active licenses, Temporary Operating Permits, Additional Bar licenses
  - URL: https://data.ny.gov/Economic-Development/Current-Liquor-Authority-Active-Licenses/9s3h-dpkz

- **Current SLA Pending Licenses**
  - Last updated: September 26, 2026
  - URL: https://data.ny.gov/Economic-Development/Current-SLA-Pending-Licenses/f8i8-k2gm

- **Current SLA Inactive Licenses**
  - URL: https://data.ny.gov/Economic-Development/Current-SLA-Inactive-Licenses/6dg3-2z7i

**API Access:**
- OData endpoint available
- Excel/Tableau integration
- Contact: slaopendata@sla.ny.gov

**Public Query System:**
- Search by: premises/trade name, license number, location, principal name
- URL: https://www.tran.sla.ny.gov/JSP/query/PublicQueryInstructPage.jsp

**Resources:**
- [Current Liquor Authority Active Licenses](https://data.ny.gov/Economic-Development/Current-Liquor-Authority-Active-Licenses/9s3h-dpkz)

---

#### California
**Authority:** Department of Alcoholic Beverage Control (ABC)

**Coverage:** ~97,000 license files, 130,000 license-type rows

**Official Tools:**
- **License Query System:** https://maps.gis.ca.gov/abc/lqs/
  - Free public lookup
  - Search by: license number, business name, address
  - Returns: license type, status, issue date, discipline history
  - Map-based query available

- **Data Export:** Daily bulk CSV export (free)
  - Owner name
  - DBA
  - Premises & mailing address
  - License type & status
  - No contact data included

**API Status:** No official API

**Third-Party Access:**
- Aggregators available (see Multi-State section)

**Resources:**
- [California ABC License Query](https://maps.gis.ca.gov/abc/lqs/)
- [California ABC License Lookup Guide](https://www.liquorready.com/articles/state-guides/california-abc-license-lookup)

---

#### Texas
**Authority:** Texas Alcoholic Beverage Commission (TABC)

**Official Tool:**
- **Public Inquiry System:** tabc.texas.gov
- Searchable online database

**API Access:**
- Socrata API available (confirmed in aggregator documentation)

**Resources:**
- [TABC Official Site](https://tabc.texas.gov)

---

#### Missouri
**Authority:** Missouri Division of Alcohol and Tobacco Control

**Dataset:**
- **Missouri Active Alcohol License Data**
- Last updated: October 9, 2026
- URL: https://data.mo.gov/Regulatory/Missouri-Active-Alcohol-License-Data/yyhn-562y

**API Access:**
- OData endpoint for Excel/Tableau integration

**Resources:**
- [Missouri Active Alcohol License Data](https://data.mo.gov/Regulatory/Missouri-Active-Alcohol-License-Data/yyhn-562y)

---

#### Wisconsin
**Authority:** Department of Revenue

**Tool:**
- **DOR Retail Alcohol Beverage License Search**
- URL: https://www.revenue.wi.gov/Pages/OnlineServices/retail-alcohol-beverage-license-search.aspx
- Searchable database for municipal-issued licenses

---

#### Pennsylvania
**Authority:** Pennsylvania Liquor Control Board (PLCB)

**System:** PLCB+ online regulatory system
- 80+ different license/permit types
- Retail and wholesale licenses searchable
- URL: https://www.pa.gov/agencies/lcb/licensing/search-licenses/

**Third-Party API:**
- Daily-checked API with business name, address, license type, status, issue date
- URL: https://www.newliquorlicenses.com/state/pennsylvania/

**Resources:**
- [PA LCB License Search](https://www.pa.gov/agencies/lcb/licensing/search-licenses/)

---

#### Illinois
**Authority:** Illinois Liquor Control Commission

**Third-Party API:**
- Daily-checked API with business name, address, license type, status, issue date
- URL: https://www.newliquorlicenses.com/state/illinois/

**Official Search:**
- Available through state portal

**Resources:**
- [Illinois Liquor License API](https://www.newliquorlicenses.com/state/illinois/)

---

#### Ohio
**Authority:** Ohio Division of Liquor Control

**Tools:**
- Liquor Permits search for Ohio permits, agencies, brands

**Third-Party Coverage:**
- Weekly feed of new/transferred permits (Ohio, Pennsylvania, Michigan)
- URL: https://liquorleads.net/

---

#### Florida
**Authority:** DBPR Division of Alcoholic Beverages and Tobacco

**Tool:**
- **Licensee Search:** myfloridalicense.com
- Search for licensed individuals/businesses regulated by DBPR

---

#### Colorado
**Authority:** Colorado Department of Revenue - Liquor Enforcement Division

**Tool:**
- **Liquor License Lists:** https://sbg.colorado.gov/liquor-license-lists/

**Third-Party Coverage:**
- Included in multi-state aggregators

---

### Multi-State Aggregators & APIs

#### Apify - Liquor License Aggregators
**US State Liquor License Aggregator:**
- **States Covered:** California (CSV), Texas (Socrata API), New York (Socrata API)
- **Data Fields:** License holder, trade name, license type, status, address, county
- **URL:** https://apify.com/jungle_synthesizer/us-state-liquor-license-aggregator-scraper

**New Liquor License Openings:**
- **States:** New York, Texas, Colorado, Missouri, Chicago
- **Filters:** Issue date, category, city, county, ZIP
- **URLs:**
  - OpenAPI: https://apify.com/offerastudio/liquor-license-openings/api/openapi
  - Python API: https://apify.com/offerastudio/liquor-license-openings/api/python
  - JavaScript API: https://apify.com/offerastudio/liquor-license-openings/api/javascript

**USA Liquor & Alcohol License Scraper:**
- **Coverage:** Multiple states
- **Data:** Owners & addresses
- **URL:** https://apify.com/scrapers_lat/usa-liquor-licenses-scraper

---

### Top Hotel States (Liquor License Priority)

**By Volume:**
- California: Largest spirits market by volume
- New York: High density, complete API coverage
- Texas: API available via Socrata
- Florida: Searchable database
- Pennsylvania: 80+ license types
- Illinois: API coverage via third parties
- Ohio: Weekly feed available
- Colorado: Open data portal

**By Per-Capita Consumption:**
- Delaware: 2.34 gallons per capita (highest)

**Hotel-Specific Licensing Models:**
- Nevada: Resort Hotel license ($5K-$10K annual, covers entire property)
- California: Separate Type 47 per outlet ($100K-$200K each on secondary market)

**Resources:**
- [Hotel Liquor License Guide](https://liquorlicensecost.com/guides/hotel-resort-liquor-license-guide)

---

## 4. UCC Filing Search

### Overview
Uniform Commercial Code (UCC) filings track secured interests in personal property and can reveal financing arrangements for hotel properties.

### State Secretary of State UCC Portals

#### California
**Portal:** CA Secretary of State API Developer Portal
- **URL:** https://calicodev.sos.ca.gov/product
- **Search Portal:** https://bizfileonline.sos.ca.gov/

**API Availability:** Yes
- **API Key Required:** CA_SOS_API_KEY
- **Documentation:** UCC XML API + Implementation Guide

**Pricing:**
- Free nonstandard wildcard search
- Standard searches: $5 (debtor, file number, secured party)
- Master data: $100
- Images: $800
- Combined package: $900

**Resources:**
- [CA SOS API Developer Portal](https://calicodev.sos.ca.gov/product)

---

#### New York
**Portal:** NY Department of State UCC Search
- **URL:** https://appext20.dos.ny.gov/pls/ucc_public/web_search.main_frame

**Access:** Free online search

**API Status:** Portal scraper approach (no official API documented)

**Resources:**
- [NY UCC Search](https://appext20.dos.ny.gov/pls/ucc_public/web_search.main_frame)

---

#### Texas
**Portal:** TX Secretary of State UCC
- **URL:** https://www.sos.state.tx.us/ucc/

**API Availability:** Yes
- **Requirements:**
  - TX_SOSDIRECT_API_KEY
  - TX_SOSDIRECT_ACCOUNT_ID
- **Bulk Download:** Available

**Access:** Paid online access

**Resources:**
- [TX SOS UCC](https://www.sos.state.tx.us/ucc/)

---

#### North Carolina
**Portal:** NC Secretary of State UCC Search
- **URL:** https://www.sosnc.gov/online_services/search/by_title/search_uniform_commercial_code

**Data Current Through:** July 13, 2026

**API Status:** No automated/scripted searches permitted

**Bulk Access:** Data Subscription Services available

**Resources:**
- [NC UCC Search](https://www.sosnc.gov/online_services/search/by_title/search_uniform_commercial_code)

---

#### South Carolina
**Service:** UCC Online with Web Service API

**Requirements:**
- Download and sign Tyler South Carolina Subscriber Agreement

**Features:**
- Filing
- Search
- Document retrieval

**Resources:**
- [SC SOS UCC API](https://scdgs.sc.gov/service/secretary-state-ucc-online-and-web-service-api)

---

#### Nevada
**Service:** UCC Bulk API

**Type:** RESTful API
- Asynchronous submission
- Request tracking
- Retrieval of UCC filings
- Standardized interface

**Resources:**
- [Nevada UCC Info](https://www.nvsos.gov/business/ucc/new-ucc-module-information)

---

#### Oregon
**Portal:** Oregon Secretary of State UCC Search
- **URL:** https://secure.sos.state.or.us/ucc/searchHome.action

---

#### Illinois
**Portal:** IL UCC Search
- **URL:** https://apps.ilsos.gov/uccsearch/

---

### Multi-State UCC Aggregators

#### OpenSOSData
**Coverage:** All 50 states + DC, Puerto Rico, US Virgin Islands

**Data Available:**
- Entity status
- Registered agents
- Officers
- Filing history
- UCC liens (debtor/secured party data)

**URL:** https://opensosdata.com/

---

#### LeadX
**Service:** UCC search via API + enterprise bulk delivery

**Endpoints:**
- Company data
- Contact info
- Reviews
- Enrichment
- UCC filings

**URL:** https://leadx.com/ucc-data/

---

#### UCC Guide
**Service:** National UCC Search & State Filing Directory

**Coverage:** Direct links to all 50 state SOS UCC portals

**Updated:** 2026

**URL:** https://www.uccguide.com/index.php

---

#### GitHub Public Records Scraper
**Service:** 50-state UCC public records intelligence

**Features:**
- Fresh data
- Enriched records
- Scored MCA/financing leads
- Dashboard, REST API, CLI access

**URL:** https://github.com/organvm-iii-ergon/public-record-data-scrapper

---

### Commercial UCC Aggregators

#### LexisNexis
**Product:** UCC Reporter-Digest + Corporate Legal Search

**Pricing (2026):**
- Customized through direct sales
- No published standard pricing
- Large Legal Price Schedule: $99 system access charge (effective Oct 2, 2026)
- Contact: 1-877-394-8826

**Notes:**
- Comprehensive UCC coverage
- Quote-based pricing
- Per-search fees vary by customer segment

**Resources:**
- [LexisNexis Corporate Legal Pricing](https://www.lexisnexis.com/en-us/terms/SACommercial/pricing.page)
- [UCC Reporter-Digest](https://store.lexisnexis.com/en-us/products/ucc-reporter-digest-grpussku10484.html)

---

## Implementation Recommendations

### For Hotel/MDU Verification Pipeline

#### Property Ownership Verification
**Primary Sources:**
1. **Regrid API** (best value for moderate volume)
   - $10/month Pro plan = 1,000 lookups/day
   - Good for daily batch processing

2. **ATTOM API** (comprehensive data)
   - $499/year minimum
   - Better for high-value properties requiring full transaction history

3. **DataTree** (highest reliability)
   - Premium pricing
   - Best for enterprise-level accuracy requirements

**County-Specific:**
- NYC: Use free ACRIS OData API
- CA properties: Use county assessor portals (free)

---

#### Liquor License Verification (Hotels with Bars/Restaurants)
**Strategy:**
1. **New York:** Use free SLA OData API
2. **California:** Daily CSV export (free)
3. **Texas, Missouri:** Socrata API (free)
4. **Multi-state aggregation:** Apify US State Liquor License Aggregator

**Priority States for Hotels:**
- CA, NY, TX, FL, PA, IL, OH, CO

---

#### UCC Filing Research (Ownership Changes, Financing)
**Strategy:**
1. **California:** Use official API ($5/search for standard)
2. **New York:** Free online search (manual or scraper)
3. **Texas:** API available (paid)
4. **Multi-state:** OpenSOSData API (50 states + territories)
5. **Enterprise:** LexisNexis (quote-based)

---

#### FDD Analysis (Location Count Verification)
**Process:**
1. Download FDDs from free state databases (CA, IN, MN, WI)
2. Extract Item 20 outlet counts
3. Cross-reference against Salesforce account lists
4. Use for location count enrichment (MDU segmentation)

**Best Sources:**
- Direct from hotel brand development portals (Marriott, Hilton)
- State databases (free)
- Franchimp (free credits)

---

## Cost Summary by Use Case

### Scenario: 1,000 Hotel Properties/Month

#### Property Ownership Lookup
- **Regrid Pro:** $10/month (1,000 included)
- **ATTOM:** $500+/month (quote required)
- **DataTree Premium:** $197/month + per-document fees

**Recommended:** Regrid Pro ($10/month)

---

#### Liquor License Verification
- **NY, CA, TX, MO:** Free (APIs available)
- **Multi-state aggregator:** Apify (usage-based)

**Recommended:** Direct state APIs (free)

---

#### UCC Filings (50 properties/month)
- **California API:** $250/month (50 × $5)
- **OpenSOSData:** Quote required
- **Manual searches:** Free but labor-intensive

**Recommended:** Mix of free state portals + OpenSOSData for scale

---

#### FDD Downloads (one-time per brand)
- **State databases:** Free
- **Direct from brands:** Free
- **Franchimp:** Free credits

**Recommended:** State databases + direct sources (free)

---

## Data Quality & Coverage Notes

### Regrid vs ATTOM vs DataTree
- **Regrid:** Best value, good coverage, GeoJSON format, daily updates
- **ATTOM:** Most comprehensive, higher cost, best for transaction history
- **DataTree:** Highest accuracy (direct from county), premium pricing

### Liquor License Databases
- **New York:** Best API, OData, actively maintained
- **California:** Best bulk data (CSV), no API
- **Texas:** API available via Socrata
- **Coverage gaps:** Not all states have searchable databases

### UCC Filing Completeness
- **California:** Comprehensive, official API
- **New York:** Complete but manual/scraper access
- **Texas:** API available, paid
- **National aggregators:** Vary in freshness, pay for convenience

### FDD Reliability
- **Official state filings:** 100% accurate, free
- **Brand portals:** Direct source, always current
- **Third-party sites:** Convenient but may charge fees

---

## Contact Information

### For API Access Inquiries

**Regrid:** Contact via https://regrid.com/parcel-api
**ATTOM:** 30-day trial available, contact for enterprise pricing
**DataTree:** Contact First American directly
**OpenSOSData:** https://opensosdata.com/
**LexisNexis:** 1-877-394-8826

### For FDD Questions

**Choice Hotels:** development@choicehotels.com
**Marriott:** hotel-development.marriott.com
**Hilton:** hilton.com/en/corporate/disclosure-documents/
**State Regulators:** Contact individual state business/franchise divisions

### For State Data Questions

**NY SLA:** slaopendata@sla.ny.gov
**CA ABC:** Contact via official portal
**County Recorders:** Contact individual county offices for API access

---

## Last Updated
October 25, 2026

## Next Steps
1. Evaluate API costs against expected monthly volume
2. Set up free trials where available (Regrid, ATTOM)
3. Download FDDs for target hotel brands
4. Test state liquor license APIs for top hotel states
5. Document actual API response formats for integration planning
