"""
Text Mining Channel — shared across religious and education verticals.

Pipeline:
  1. Use website from CSV if present; else search with Serper
  2. Fetch with requests + BeautifulSoup (no Playwright — lightweight)
  3. Score keywords against TV_KEYWORDS and REJECTION_KEYWORDS
  4. Return TextMineResult with tier/evidence/cost
"""

import re
import sys
import time
import requests
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Ensure repo root is on sys.path for config import
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import config

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

TV_KEYWORDS_HIGH = [
    r"\bflat[ -]?screen\b",
    r"\bbig[ -]?screen\b",
    r"\blarge[ -]?screen\b",
    r"\bwidescreen\b",
    r"\bHDTV\b",
    r"\bHD TV\b",
    r"\bmultiple\s+(?:large\s+)?(?:TV|screen)s?\b",
    r"\blive[\s-]stream(?:ing)?\s+(?:screen|display|monitor|TV)\b",
    r"\boverflow\s+room\b.*\b(?:screen|TV|monitor|display)\b",
    r"\b(?:screen|TV|monitor|display)\b.*\boverflow\s+room\b",
    r"\btelevision\s+(?:ministry|broadcast|lounge|room|area|screen)\b",
    r"\b(?:ministry|broadcast|lounge|room|area|screen)\s+television\b",
]

TV_KEYWORDS_MEDIUM = [
    r"\bTV\s+(?:lounge|room|area|screen|monitor|mounted|in\s+the)\b",
    r"\b(?:lounge|room|area|waiting)\s+TV\b",
    r"\bdisplay\s+screen\b",
    r"\bdigital\s+display\b",
    r"\bAV\s+system\b",
    r"\baudio[\s/]?visual\s+(?:system|equipment|setup)\b",
    r"\b(?:mounted|wall[\s-]mounted)\s+(?:screen|monitor|display)\b",
    r"\b(?:screen|monitor|display)\s+(?:mounted|on\s+the\s+wall)\b",
    r"\bsimultaneous\s+(?:broadcast|viewing)\b",
    r"\blobby\s+(?:screen|TV|monitor|display)\b",
    r"\bwaiting\s+(?:room|area|lounge)\b.*\b(?:TV|screen|display)\b",
    r"\b(?:TV|screen|display)\b.*\bwaiting\s+(?:room|area|lounge)\b",
    r"\bcommon\s+(?:room|area|space)\b.*\b(?:TV|screen|display)\b",
    r"\bstudent\s+(?:lounge|union|center)\b.*\b(?:TV|screen|display)\b",
    r"\bfellowship\s+hall\b.*\b(?:TV|screen|display|projection)\b",
]

REJECTION_KEYWORDS = [
    r"\bprojector\b",
    r"\bpowerpoint\b",
    r"\bsermon\s+slide[s]?\b",
    r"\bpresentation\s+slide[s]?\b",
    r"\bsmartboard\b",
    r"\bwhiteboard\b",
    r"\bclassroom\s+(?:screen|display|projector)\b",
    r"\bchalkboard\b",
]

# Context patterns that veto a snippet regardless of TV keyword match.
# These indicate the snippet is from accommodation/real-estate/theater, not an institution.
_SNIPPET_VETO_PATTERNS = [
    re.compile(r"\bmaster\s+bedroom\b", re.IGNORECASE),
    re.compile(r"\bguest\s+room\b", re.IGNORECASE),
    re.compile(r"\bhotel\s+room\b", re.IGNORECASE),
    re.compile(r"\bcable\s+channels?\b", re.IGNORECASE),
    re.compile(r"\bcheck[\s-]in\b.*\bcheck[\s-]out\b", re.IGNORECASE),
    re.compile(r"\bnightly\s+rate\b", re.IGNORECASE),
    re.compile(r"\bScreenX\b", re.IGNORECASE),      # movie-theater format
    re.compile(r"\bIMAX\b", re.IGNORECASE),
    re.compile(r"\bcinema\b", re.IGNORECASE),
    re.compile(r"\bbroadcast\s+television\s+station\b", re.IGNORECASE),  # TV station list
    re.compile(r"\btelevision\s+station[s]?\s+(?:in|licensed)\b", re.IGNORECASE),
    re.compile(r"\b(?:king|queen|twin)\s+bed\b", re.IGNORECASE),        # hotel/lodging room
    re.compile(r"\bper\s+night\b", re.IGNORECASE),
    re.compile(r"\broom\s+(?:amenities|service)\b", re.IGNORECASE),
]

# Domains where snippets cannot be PoP evidence for an institutional account.
# Entertainment platforms and real estate listing sites are the main culprits:
# - Entertainment: snippets reference movies/shows, not physical displays
# - Real estate: snippets mention "flat screen TV" in a listed house near the account
_EXCLUDED_SNIPPET_DOMAINS = {
    # Streaming / entertainment
    "spotify.com", "apple.com", "music.apple.com",
    "primevideo.com", "amazon.com", "netflix.com", "hulu.com",
    "youtube.com", "youtu.be", "vimeo.com",
    "itunes.apple.com", "play.google.com",
    "imdb.com", "rottentomatoes.com",
    # Real estate (TV mention is a home feature, not the institution)
    "compass.com", "zillow.com", "redfin.com", "realtor.com",
    "trulia.com", "homes.com", "homesnap.com", "apartments.com",
    "coldwellbanker.com", "century21.com", "kw.com", "remax.com",
    "har.com", "ntreis.com",
    # Job boards (TV mentioned in office amenities, not customer-facing space)
    "indeed.com", "glassdoor.com", "linkedin.com",
    # Social platforms — TV mentions are for shows/events, not institutional displays
    "instagram.com", "twitter.com", "x.com", "tiktok.com",
    "facebook.com", "fb.com",
    # Local business directories — snippet is the directory listing, not the institution
    "yelp.com", "foursquare.com", "yellowpages.com",
    # Hospitality / hotel booking — TV is a room amenity, not institutional display
    "tripadvisor.com", "booking.com", "expedia.com", "hotels.com",
    "marriott.com", "hilton.com", "hyatt.com", "ihg.com",
    "kayak.com", "priceline.com", "hoteltonight.com", "airbnb.com",
    "vrbo.com",
    # Retail / product pages — TV mentioned as product for sale
    "bestbuy.com", "target.com", "walmart.com", "costco.com", "bhphotovideo.com",
    "newegg.com", "adorama.com", "lg.com", "samsung.com", "sony.com",
}

# Keep for backward compat (referenced in _serper_find_website)
_KNOWN_BOGUS_WEBSITES = {
    "outlook.com", "yahoo.com", "gmail.com", "hotmail.com",
    "google.com", "facebook.com", "linkedin.com",
}

# Patterns compiled once
_TV_HIGH = [re.compile(p, re.IGNORECASE) for p in TV_KEYWORDS_HIGH]
_TV_MED  = [re.compile(p, re.IGNORECASE) for p in TV_KEYWORDS_MEDIUM]
_REJ     = [re.compile(p, re.IGNORECASE) for p in REJECTION_KEYWORDS]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 12          # seconds for requests
PLAYWRIGHT_EXECUTABLE = "/opt/pw-browsers/chromium"   # pre-installed in cloud env
MIN_STATIC_LENGTH = 200       # chars — if less, try Playwright fallback


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class TextMineResult:
    tier: str                      # PROSPECT / SUSPECT / REJECTED
    evidence_description: str
    source_url: str
    keywords_matched: list         # matched strings
    rejection_keywords: list       # rejection strings that fired
    channel: str = "text_mining"
    cost_usd: float = 0.0
    pages_scraped: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Serper URL discovery (cheap — 1 credit)
# ---------------------------------------------------------------------------

_TV_SEARCH_TERMS = (
    '"big screen" OR "flat screen" OR "overflow room" OR "A/V system" OR '
    '"large screen TV" OR "flat screen TV" OR "television" OR "simulcast"'
)

_KNOWN_BOGUS_WEBSITES = {
    "outlook.com", "yahoo.com", "gmail.com", "hotmail.com",
    "google.com", "facebook.com", "linkedin.com",
}


def _serper_search(query: str) -> Optional[dict]:
    """Make a Serper /search call and return the JSON response."""
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": config.SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": 10},
            timeout=15,
        )
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def _account_name_tokens(account_name: str) -> list[str]:
    """
    Return significant tokens from the account name for snippet attribution checks.
    Strips common generic words so "First Baptist Church" → ["first", "baptist"].
    A snippet must contain at least one of these tokens to be attributed to the account.
    """
    stopwords = {
        "the", "a", "an", "of", "and", "at", "in", "for", "to", "by",
        "church", "school", "college", "university", "inc", "llc", "ltd",
        "association", "foundation", "academy",
    }
    tokens = re.findall(r"[a-z]+", account_name.lower())
    meaningful = [t for t in tokens if t not in stopwords and len(t) > 2]
    return meaningful[:4]  # cap at 4 to avoid over-filtering


def _serper_av_snippet_search(
    account_name: str, state: str
) -> tuple[list[str], list[str]]:
    """
    Search Serper for AV/TV keywords near the account name.
    Returns (tv_snippet_hits, source_urls).

    Only counts a snippet as a hit if:
    - The source URL is not an excluded domain (entertainment, real estate, hospitality)
    - The match is a HIGH-signal keyword (not bare "TV" or "television")
    - The snippet or title mentions at least one meaningful token from the account name
      (prevents nearby hotel/venue results from being attributed to the searched account)
    - The snippet contains no veto patterns (hotel rooms, cinema formats, etc.)
    """
    query = f'"{account_name}" {state} {_TV_SEARCH_TERMS}'
    data = _serper_search(query)
    if not data:
        return [], []

    name_tokens = _account_name_tokens(account_name)

    tv_hits = []
    source_urls = []
    for result in data.get("organic", []):
        snippet = result.get("snippet", "")
        title   = result.get("title", "")
        link    = result.get("link", "")
        if not snippet or not link:
            continue

        # Skip excluded domains (entertainment, real estate, hospitality, retail)
        domain = urlparse(link).netloc.lower().lstrip("www.")
        if any(excl in domain for excl in _EXCLUDED_SNIPPET_DOMAINS):
            continue
        # Also skip any domain that looks like a hotel/inn/resort/motel property
        # (e.g. quality-inn-62864.allhotelsillinois.com, bestwestern-chicago.com)
        if re.search(r"(?:hotel|motel|inn(?:suite)?|resort|lodge|suites)\b", domain):
            continue

        # Veto hospitality/cinema/TV-station context regardless of TV keyword match
        combined = f"{title} {snippet}"
        if any(pat.search(combined) for pat in _SNIPPET_VETO_PATTERNS):
            continue

        # Attribution check: snippet+title must mention at least one meaningful
        # token from the account name so we don't credit nearby venues.
        # If the account name is too short/generic to produce any tokens (e.g. "A",
        # "NPU"), require the exact account name to appear in the snippet.
        combined_lower = combined.lower()
        if name_tokens:
            if not any(tok in combined_lower for tok in name_tokens):
                continue
        else:
            # Degenerate name (e.g. "A", "NPU") — skip snippet attribution entirely.
            # Single letters and short abbreviations match in every English sentence
            # so Serper snippets are unattributable; skip them (website scraping may still work).
            continue

        # Only count HIGH-signal keyword matches in snippets
        # (medium-signal like bare "TV" is too noisy without a scraped page for context)
        high_hits = [m for pat in _TV_HIGH for m in [pat.search(snippet)] if m]
        if high_hits:
            tv_hits.append(snippet[:150])
            source_urls.append(link)

    return tv_hits, source_urls


def _serper_find_website(account_name: str, city: str, state: str) -> Optional[str]:
    """Return the most likely website URL for an account via Serper search."""
    query = f"{account_name} {city} {state} official website"
    data = _serper_search(query)
    if not data:
        return None
    organic = data.get("organic", [])
    if not organic:
        return None
    # Skip social media / directories and known bogus websites
    skip_domains = {"yelp.com", "facebook.com", "linkedin.com", "yellowpages.com",
                    "google.com", "whitepages.com", "bbb.org", "tripadvisor.com",
                    "umc.org", "sbc.net", "lcms.org", "elca.org",  # denomination directories
                    } | _KNOWN_BOGUS_WEBSITES
    for result in organic:
        link = result.get("link", "")
        domain = urlparse(link).netloc.lower().lstrip("www.")
        if not any(skip in domain for skip in skip_domains):
            return link
    # Fallback: first result regardless
    return organic[0].get("link")


# ---------------------------------------------------------------------------
# Page scraping
# ---------------------------------------------------------------------------

def _fetch_text_requests(url: str) -> Optional[str]:
    """Fetch URL with requests + BeautifulSoup. Fast, works for static sites."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "head"]):
            tag.decompose()
        return " ".join(soup.get_text(separator=" ").split())
    except Exception:
        return None


def _fetch_text_playwright(url: str) -> Optional[str]:
    """Fetch URL with Playwright for JS-rendered sites. Slower but complete."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                executable_path=PLAYWRIGHT_EXECUTABLE,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            text = page.inner_text("body")
            browser.close()
        return " ".join(text.split()) if text else None
    except Exception:
        return None


def _fetch_text(url: str) -> Optional[str]:
    """Fetch text from a URL. Tries requests first; falls back to Playwright for JS sites."""
    text = _fetch_text_requests(url)
    if not text or len(text) < MIN_STATIC_LENGTH:
        text = _fetch_text_playwright(url)
    return text


def _subpages(base_url: str, keywords: list[str]) -> list[str]:
    """Build a list of high-value subpage URLs to scrape based on vertical keywords."""
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    candidates = []
    for kw in keywords:
        candidates.append(f"{root}/{kw}")
    return candidates[:4]  # cap at 4 additional pages


RELIGIOUS_SUBPAGES = ["about", "facilities", "campus", "visitor", "worship"]
EDUCATION_SUBPAGES = ["campus-life", "student-union", "dining", "recreation", "facilities"]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_text(text: str) -> tuple[list[str], list[str]]:
    """Return (tv_hits, rejection_hits). Veto patterns hard-cancel the result."""
    # If the page text itself reads like a hotel or cinema, reject immediately
    if any(pat.search(text) for pat in _SNIPPET_VETO_PATTERNS):
        return [], ["[veto: hospitality/cinema context detected]"]

    tv_hits = []
    for pat in _TV_HIGH + _TV_MED:
        m = pat.search(text)
        if m:
            # Grab 80-char context around the match
            start = max(0, m.start() - 40)
            end   = min(len(text), m.end() + 40)
            tv_hits.append(text[start:end].strip())

    rejection_hits = []
    for pat in _REJ:
        m = pat.search(text)
        if m:
            rejection_hits.append(m.group(0))

    return tv_hits, rejection_hits


def _tier(tv_hits: list, rejection_hits: list) -> str:
    """Map hit counts to a tier."""
    high_hits = sum(1 for _ in tv_hits[:len(_TV_HIGH)])  # rough count
    if len(tv_hits) == 0:
        return "REJECTED"
    # Heavy rejection signal overrides moderate TV signal
    if len(rejection_hits) > 1 and len(tv_hits) <= 2:
        return "SUSPECT"
    if len(tv_hits) >= 2 or any(pat.search(" ".join(tv_hits)) for pat in _TV_HIGH):
        return "PROSPECT"
    return "SUSPECT"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def mine_website(
    account_name: str,
    website_url: Optional[str] = None,
    city: str = "",
    state: str = "",
    vertical: str = "",
    serper_fallback: bool = True,
) -> TextMineResult:
    """
    Mine for TV evidence using two strategies:
      1. Serper snippet search — query Google for AV keywords near the account name.
         Cheaper and more reliable than scraping; Google's index already contains
         reviews, PDFs, newsletters that mention TVs.
      2. Website scraping — if Serper finds no AV snippets, scrape the account's
         website for facility/about pages.

    Args:
        account_name:    Account name
        website_url:     Pre-known URL from CSV (used for scraping step only)
        city, state:     Location for Serper queries
        vertical:        Controls which subpages to probe ("religious" or "education")
        serper_fallback: Use Serper; disable only for testing
    """
    cost = 0.0
    all_tv_hits: list[str] = []
    all_rej_hits: list[str] = []
    best_url = website_url or ""
    pages_scraped = 0

    # Normalize website URL — add https:// if missing scheme
    if website_url:
        domain = urlparse(website_url).netloc
        if not domain:                           # no scheme, just a bare domain
            website_url = f"https://{website_url}"
        # Discard clearly bogus website values
        domain = urlparse(website_url).netloc.lower().lstrip("www.")
        if any(bogus in domain for bogus in _KNOWN_BOGUS_WEBSITES):
            website_url = None
    found_url = website_url

    # ------------------------------------------------------------------
    # Step 1: Serper snippet search (primary — uses Google's full index)
    # ------------------------------------------------------------------
    if serper_fallback and config.SERPER_API_KEY:
        tv_snippets, snippet_urls = _serper_av_snippet_search(account_name, state)
        cost += 0.001  # 1 Serper credit
        all_tv_hits.extend(tv_snippets)
        if snippet_urls:
            best_url = snippet_urls[0]

        # If Serper found strong evidence, stop here — no scraping needed
        if len(all_tv_hits) >= 2:
            tier = _tier(all_tv_hits, all_rej_hits)
            return TextMineResult(
                tier=tier,
                evidence_description=f"Serper snippet: \"{all_tv_hits[0][:120]}\"",
                source_url=best_url,
                keywords_matched=all_tv_hits[:5],
                rejection_keywords=[],
                cost_usd=cost,
                pages_scraped=0,
            )

    # ------------------------------------------------------------------
    # Step 2: Find website URL if not already known
    # ------------------------------------------------------------------
    if not found_url and serper_fallback and config.SERPER_API_KEY:
        found_url = _serper_find_website(account_name, city, state)
        cost += 0.001
        best_url = found_url or best_url

    if not found_url:
        tier = _tier(all_tv_hits, all_rej_hits)
        if tier == "REJECTED":
            return TextMineResult(
                tier="REJECTED",
                evidence_description="No website URL and no Serper AV snippets found",
                source_url="",
                keywords_matched=[],
                rejection_keywords=[],
                cost_usd=cost,
                error="no_website_url",
            )

    # ------------------------------------------------------------------
    # Step 3: Scrape facility subpages (secondary)
    # ------------------------------------------------------------------
    subpage_list = RELIGIOUS_SUBPAGES if vertical == "religious" else EDUCATION_SUBPAGES
    urls_to_scrape = ([found_url] if found_url else []) + _subpages(found_url or "", subpage_list)

    for url in urls_to_scrape:
        if not url:
            continue
        text = _fetch_text(url)
        if not text:
            continue
        pages_scraped += 1
        tv_hits, rej_hits = _score_text(text)
        if tv_hits:
            best_url = url
        all_tv_hits.extend(tv_hits)
        all_rej_hits.extend(rej_hits)
        if len(all_tv_hits) >= 3:
            break
        time.sleep(0.3)

    # ------------------------------------------------------------------
    # Step 4: Build result
    # ------------------------------------------------------------------
    tier = _tier(all_tv_hits, all_rej_hits)

    if all_tv_hits:
        snippet = all_tv_hits[0][:120]
        rej_note = f" (possible projection-only: {', '.join(all_rej_hits[:2])})" if all_rej_hits else ""
        desc = f"Text evidence: \"{snippet}\"{rej_note}"
    else:
        desc = "No TV/display keywords found in text search or website scraping"

    return TextMineResult(
        tier=tier,
        evidence_description=desc,
        source_url=best_url,
        keywords_matched=all_tv_hits[:5],
        rejection_keywords=all_rej_hits[:3],
        cost_usd=cost,
        pages_scraped=pages_scraped,
    )
