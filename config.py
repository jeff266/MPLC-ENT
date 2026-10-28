"""
Configuration for MPLC PoP Detection Engine

Secrets are loaded from environment variables — never hardcode keys here.
Add secrets via the Claude Code environment settings (Secrets tab).
"""

import os
from pathlib import Path

# ==============================================================================
# API CREDENTIALS  (set these as environment secrets)
# ==============================================================================
SERPER_API_KEY        = os.getenv("SERPER_API_KEY", "")
SERPAPI_API_KEY       = os.getenv("SERPAPI_API_KEY", "")
ANTHROPIC_API_KEY     = os.getenv("ANTHROPIC_API_KEY", "")
APIFY_API_TOKEN       = os.getenv("APIFY_API_TOKEN", "")
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
GOOGLE_MAPS_API_KEY   = os.getenv("GOOGLE_MAPS_API_KEY", "")

# ==============================================================================
# COST LIMITS (CIRCUIT BREAKER)
# ==============================================================================
MAX_COST_USD        = 20.0   # Dollar cap per run
MAX_SERPER_CREDITS  = 500    # Serper credit cap per run

# ==============================================================================
# PATHS
# ==============================================================================
PROJECT_ROOT = Path(__file__).parent
CACHE_DIR    = PROJECT_ROOT / "cache"
LOGS_DIR     = PROJECT_ROOT / "logs"
OUTPUT_DIR   = PROJECT_ROOT / "output"

for dir_path in [CACHE_DIR, LOGS_DIR, OUTPUT_DIR]:
    dir_path.mkdir(exist_ok=True, parents=True)

# ==============================================================================
# SERPER COSTS (credits per query type)
# ==============================================================================
SERPER_COSTS = {
    "search": 1,
    "places": 1,
    "images": 1,
}

# ==============================================================================
# ANTHROPIC MODELS
# ==============================================================================
VLM_MODEL   = "claude-sonnet-4-5-20250929"
TEXT_MODEL  = "claude-haiku-4"

# ==============================================================================
# VERTICAL-SPECIFIC URL DISCOVERY ROUTING
# ==============================================================================
VERTICAL_URL_STRATEGY = {
    "Restaurants, Clubs, Pubs": {
        "yelp": True,
        "google_places": True,
        "tripadvisor": False,
        "careers": False,
    },
    "Short-term Lodging": {
        "yelp": True,
        "google_places": True,
        "tripadvisor": True,
        "careers": False,
    },
    "Corporations": {
        "yelp": False,
        "google_places": False,
        "tripadvisor": False,
        "careers": True,
    },
    "Health Care Services": {
        "yelp": True,
        "google_places": True,
        "tripadvisor": False,
        "careers": True,
    },
    "MDU": {
        "yelp": False,
        "google_places": True,
        "tripadvisor": False,
        "careers": False,
        "apartments_com": True,
    },
    "Communal Living Facilities": {
        "yelp": False,
        "google_places": True,
        "tripadvisor": False,
        "careers": False,
    },
}

DEFAULT_URL_STRATEGY = {
    "yelp": True,
    "google_places": True,
    "tripadvisor": False,
    "careers": False,
}

# ==============================================================================
# TEXT SCRAPING CONFIGURATION
# ==============================================================================
MAX_PAGES_PER_SITE  = 10
PLAYWRIGHT_TIMEOUT  = 20000   # ms
CRAWL_DELAY         = 0.5     # seconds between requests

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
]

# ==============================================================================
# YOLO CONFIGURATION
# ==============================================================================
YOLO_MODEL                 = str(PROJECT_ROOT / "models" / "yolo11n.pt")
YOLO_CONFIDENCE_THRESHOLD  = 0.25
YOLO_TARGET_CLASSES        = ["tv"]
YOLO_CONTEXT_CLASSES       = ["couch", "dining table", "chair", "refrigerator", "person", "bed"]
YOLO_PERSONAL_CONTEXT      = ["laptop", "keyboard", "mouse", "desk"]

# ==============================================================================
# EVIDENCE STRENGTH MAPPING
# ==============================================================================
EVIDENCE_STRENGTH_THRESHOLDS = {
    "Very Strong":    90,
    "Strong":         75,
    "Medium":         50,
    "Weak":           25,
    "Not Applicable":  0,
}

# ==============================================================================
# CACHE SETTINGS
# ==============================================================================
CACHE_EXPIRY_DAYS = 30
CACHE_ENABLED     = True
