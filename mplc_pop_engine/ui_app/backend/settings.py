"""
Settings — store API keys / connection strings in .env, and verify each one
against a real, minimal-cost provider call. Added 2026-11-14 (Jeff: "would it
be good to have a settings page that can store variables and write to the env
file? And functions to verify the keys work") -- the whole-app auth system
just built (auth.py) is the prerequisite this needed, since this endpoint can
write live secrets and main.py's CORS is wide open.

Scope: only the vars actually read by the CURRENT production path (traced by
grep against production/enrichers/*.py, production/workers/*.py, and this
backend's own supabase_client.py) -- not every var that appears anywhere in
the repo. Several candidates are deliberately NOT included here:
  - YOUTUBE_API_KEY: only used by verticals/*/video_channel.py and the
    deploy/ (pre-"production/enrichers") scripts, both superseded. The real
    production YouTube flow (healthcare_unified.py, mdu_unified*.py) goes
    through Serper (search) + RapidAPI (download), no official YouTube Data
    API key at all.
  - APIFY_API_TOKEN, GOOGLE_MAPS_API_KEY, GOOGLE_PLACES_API_KEY,
    SERPAPI_API_KEY: legacy/scratch only (verticals/, scratch/, config.py).
  - JWT_SECRET_KEY: auth-internal, auto-managed by auth.py -- deliberately
    NOT settings-editable. Rotating it silently logs out every user, and
    even a masked preview here is one more place it could leak.
  - UNIFIED_WORKER_PATH: a file path, not a credential.

While tracing this, found that 6 files had a LIVE secret hardcoded directly
at the call site instead of actually reading the matching env var (dead
`os.getenv(...)` sitting unused next to a literal key) -- fixed separately,
see PoP_Detection_Engine_Learnings.md's 2026-11-14 security-incident section.
That's the reason a "verify this key" feature is worth building at all: it
would have caught the RAPIDAPI_KEY mismatch immediately (verify green, real
job still silently using the wrong key) if it had existed before.

Each "secret"-category field's verify() makes the cheapest REAL call that
still proves the key works, researched against each provider's actual
behavior (2026-11-14), not guessed:
  - Anthropic: the real SDK's messages.count_tokens() -- an auth-checked
    endpoint (401 on a bad key), free (token counting only, no generation,
    no billing).
  - Serper: no free/account endpoint exists anywhere in their API -- every
    POST /search call bills one credit regardless of query size. Verify
    costs 1 credit; said explicitly in the result so it's never a silent
    surprise.
  - RapidAPI (youtube-info-download-api, used by healthcare_unified.py /
    mdu_unified*.py): a bogus-job-id call to the SAME /ajax/download.php
    endpoint the real code calls (there's no separate "progress check" the
    key alone can hit without a real job existing) -- a 401/403 means the
    key itself is bad; any other response (bad URL, 200 "success": false,
    etc.) means auth passed. Since the download endpoint is what actually
    costs quota, this does carry a small real cost unlike the FREE pure
    progress-poll CLAUDE.md describes for an in-flight job -- said
    explicitly in the result, same as Serper/GraphIQ.
  - GraphIQ: no free ping endpoint -- verify is organizations/search with
    limit=1 (same auth header the real graphiq_backfill.py uses), which
    costs 1 credit (same caveat as Serper).
  - Supabase (DATABASE_URL / SUPABASE_PASSWORD): reuses supabase_client.py's
    own connection builder and runs SELECT 1. Free.

TESTING CAVEAT (2026-11-14): end-to-end verification in THIS build
environment could only fully exercise the Anthropic path (api.anthropic.com
is allowlisted here; sent a real request with a deliberately invalid key
and got a real 401 back) and the "not configured" path for every provider.
Serper, RapidAPI, and GraphIQ's actual hosts are NOT reachable from this
sandbox (outbound network is allowlisted and doesn't include
google.serper.dev / rapidapi.com / app.graphiq.ai) -- their _verify_*
functions were checked for correct exception handling and response-code
branching, but NOT exercised against the live APIs with a real key, valid
or invalid. Re-verify those three against real keys once this runs
somewhere with open egress (Jeff's machine, a droplet) before trusting
their exact status-code assumptions (e.g. that a bad key gets 401/403
rather than a 200 with an error field in the body).

Writing: whichever of the two .env files (local backend .env, or
production/workers/.env -- same two paths main.py and auth.py already
search) ALREADY defines a key gets the update; a brand-new key is written to
the workers .env, since that's the canonical file the real unified_worker.py
subprocess also reads at its own startup -- so updating a key here takes
effect for the NEXT dispatched enrichment job automatically, no restart
needed. The running backend process's os.environ is also updated
immediately so supabase_client.py (which calls os.getenv fresh on every
connection) and this module's own verify() pick up a change without
restarting this API either.

Masking: GET /settings never returns a raw secret value -- only whether
it's set, which file defines it, and a masked preview (last 4 characters).
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values, set_key

# Same two candidate .env paths main.py / auth.py already search (local
# backend .env first, then the workers' .env) -- this module doesn't
# introduce a third place secrets can live.
_LOCAL_ENV = Path(__file__).parent / ".env"
_WORKERS_ENV = Path(__file__).parent.parent.parent / "MPLC" / "production" / "workers" / ".env"
_ENV_FILES = [_LOCAL_ENV, _WORKERS_ENV]

RAPIDAPI_YOUTUBE_HOST = "youtube-info-download-api.p.rapidapi.com"
GRAPHIQ_BASE_URL = "https://app.graphiq.ai/api/v2"  # same as graphiq_backfill.py

FIELDS: list[dict] = [
    {
        "key": "ANTHROPIC_API_KEY",
        "label": "Anthropic API Key",
        "category": "secret",
        "help": "VLM image/video classification -- used by every vertical enricher.",
    },
    {
        "key": "SERPER_API_KEY",
        "label": "Serper API Key",
        "category": "secret",
        "help": "Image + YouTube search, all verticals.",
    },
    {
        "key": "RAPIDAPI_KEY",
        "label": "RapidAPI Key",
        "category": "secret",
        "help": "YouTube video download (healthcare + MDU video channels).",
    },
    {
        "key": "GRAPHIQ_API_KEY",
        "label": "GraphIQ API Key",
        "category": "secret",
        "help": "Employee-count / firmographic enrichment (Step 1 EDGAR join).",
    },
    {
        "key": "DATABASE_URL",
        "label": "Supabase Connection String",
        "category": "connection",
        "help": "Full postgres:// URL. Takes priority over SUPABASE_PASSWORD if both are set.",
    },
    {
        "key": "SUPABASE_PASSWORD",
        "label": "Supabase Password",
        "category": "connection",
        "help": "Used to build the connection string if DATABASE_URL isn't set.",
    },
    {
        "key": "ENABLE_YOUTUBE",
        "label": "Enable YouTube Channel",
        "category": "flag",
        "help": "Per-vertical paid-channel toggle (healthcare, mdu). Same default-on"
                " semantics as enrichment.CHANNEL_ENV_VARS -- unset/anything but"
                " \"false\" means on.",
    },
    {
        "key": "ENABLE_IMAGE_SEARCH",
        "label": "Enable Image Search Channel",
        "category": "flag",
        "help": "Per-vertical paid-channel toggle (healthcare, corporate).",
    },
]
FIELDS_BY_KEY = {f["key"]: f for f in FIELDS}
VERIFIABLE_KEYS = {"ANTHROPIC_API_KEY", "SERPER_API_KEY", "RAPIDAPI_KEY", "GRAPHIQ_API_KEY",
                   "DATABASE_URL", "SUPABASE_PASSWORD"}


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return f"{'•' * max(len(value) - 4, 4)}{value[-4:]}"


def _file_defining(key: str) -> Optional[Path]:
    for path in _ENV_FILES:
        if path.exists() and dotenv_values(path).get(key):
            return path
    return None


def list_settings() -> list[dict]:
    out = []
    for field in FIELDS:
        key = field["key"]
        value = os.getenv(key)
        defining_file = _file_defining(key)
        is_flag = field["category"] == "flag"
        out.append({
            **field,
            "is_set": bool(value),
            "value": value if is_flag else None,  # flags aren't secret -- show them plainly
            "masked_value": None if is_flag else (_mask(value) if value else None),
            "source_file": defining_file.name if defining_file else None,
            "verifiable": key in VERIFIABLE_KEYS,
        })
    return out


class UnknownSetting(ValueError):
    pass


def set_setting(key: str, value: str) -> dict:
    if key not in FIELDS_BY_KEY:
        raise UnknownSetting(
            f"'{key}' is not a managed setting. Managed keys: {sorted(FIELDS_BY_KEY)}"
        )
    target = _file_defining(key) or _WORKERS_ENV
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.touch()
    set_key(str(target), key, value)
    os.environ[key] = value  # live for the rest of THIS process too, no restart needed
    return {"key": key, "source_file": target.name}


class VerifyResult:
    def __init__(self, ok: bool, detail: str, cost_note: str = "Free"):
        self.ok = ok
        self.detail = detail
        self.cost_note = cost_note

    def to_dict(self) -> dict:
        return {"ok": self.ok, "detail": self.detail, "cost_note": self.cost_note}


def _verify_anthropic() -> VerifyResult:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return VerifyResult(False, "ANTHROPIC_API_KEY is not set.")
    try:
        import anthropic
    except ImportError:
        return VerifyResult(False, "The 'anthropic' package isn't installed in this backend.")
    try:
        client = anthropic.Anthropic(api_key=key)
        result = client.messages.count_tokens(
            model="claude-sonnet-4-5-20250929",  # same model string used by the real enrichers
            messages=[{"role": "user", "content": "ping"}],
        )
        return VerifyResult(True, f"Key is valid (count_tokens: {result.input_tokens} tokens).")
    except anthropic.AuthenticationError as e:
        return VerifyResult(False, f"Authentication failed: {e}")
    except Exception as e:
        return VerifyResult(False, f"Unexpected error: {e}")


def _verify_serper() -> VerifyResult:
    key = os.getenv("SERPER_API_KEY")
    if not key:
        return VerifyResult(False, "SERPER_API_KEY is not set.")
    import requests
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": "test", "num": 1},
            timeout=15,
        )
    except requests.RequestException as e:
        return VerifyResult(False, f"Request failed: {e}",
                             cost_note="Not charged -- the request never reached Serper (network/connection failure)")
    if resp.status_code == 403:
        return VerifyResult(False, "Authentication failed (403) -- key is invalid or disabled.",
                             cost_note="Likely not charged -- a 403 reads as an auth rejection before billing, "
                                        "but this wasn't confirmed against a real invalid key (this sandbox's "
                                        "network allowlist blocks google.serper.dev outbound, so only the "
                                        "response-handling logic was tested, not the live behavior)")
    if resp.status_code != 200:
        return VerifyResult(False, f"Unexpected response: HTTP {resp.status_code} -- {resp.text[:200]}",
                             cost_note="1 credit")
    return VerifyResult(True, "Key is valid (search returned results).", cost_note="1 credit")


def _verify_rapidapi() -> VerifyResult:
    key = os.getenv("RAPIDAPI_KEY")
    if not key:
        return VerifyResult(False, "RAPIDAPI_KEY is not set.")
    import requests
    try:
        resp = requests.get(
            f"https://{RAPIDAPI_YOUTUBE_HOST}/ajax/download.php",
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": RAPIDAPI_YOUTUBE_HOST, "accept": "application/json"},
            # A real, short, public video -- same param shape the real code sends.
            params={"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw", "format": "480", "max_duration": 1},
            timeout=20,
        )
    except requests.RequestException as e:
        return VerifyResult(False, f"Request failed: {e}",
                             cost_note="Not charged -- the request never reached RapidAPI (network/connection failure)")
    if resp.status_code in (401, 403):
        return VerifyResult(False, f"Authentication failed (HTTP {resp.status_code}) -- key is invalid.",
                             cost_note="Not charged on an auth failure")
    if resp.status_code != 200:
        return VerifyResult(False, f"Unexpected response: HTTP {resp.status_code} -- {resp.text[:200]}",
                             cost_note="May have been charged -- see RapidAPI dashboard")
    # A 200 here (success or a clean "rejected: too long"/duplicate-style error) means the
    # RapidAPI gateway authenticated this key and routed the request through to the
    # underlying API -- that's what "the key works" means for this endpoint.
    return VerifyResult(True, "Key is valid (RapidAPI gateway authenticated and routed the request).",
                         cost_note="Charged like a real download call -- this isn't a free progress-check, "
                                    "unlike polling an in-flight job's own progress_url")


def _verify_graphiq() -> VerifyResult:
    key = os.getenv("GRAPHIQ_API_KEY")
    if not key:
        return VerifyResult(False, "GRAPHIQ_API_KEY is not set.")
    import requests
    try:
        resp = requests.get(
            f"{GRAPHIQ_BASE_URL}/organizations/search",
            headers={"X-API-Key": key},  # same header graphiq_backfill.py's GraphIQClient uses
            params={"name": "Anthropic", "limit": 1},
            timeout=20,
        )
    except requests.RequestException as e:
        return VerifyResult(False, f"Request failed: {e}",
                             cost_note="Not charged -- the request never reached GraphIQ (network/connection failure)")
    if resp.status_code in (401, 403):
        return VerifyResult(False, f"Authentication failed (HTTP {resp.status_code}) -- key is invalid.",
                             cost_note="Not charged on an auth failure")
    if resp.status_code != 200:
        return VerifyResult(False, f"Unexpected response: HTTP {resp.status_code} -- {resp.text[:200]}",
                             cost_note="1 credit")
    return VerifyResult(True, "Key is valid (search returned results).", cost_note="1 credit")


def _verify_supabase() -> VerifyResult:
    from . import supabase_client
    try:
        with supabase_client._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return VerifyResult(True, "Connected and ran SELECT 1 successfully.")
    except supabase_client.SupabaseUnavailable as e:
        return VerifyResult(False, str(e))
    except Exception as e:
        return VerifyResult(False, f"Connection failed: {e}")


_VERIFIERS = {
    "ANTHROPIC_API_KEY": _verify_anthropic,
    "SERPER_API_KEY": _verify_serper,
    "RAPIDAPI_KEY": _verify_rapidapi,
    "GRAPHIQ_API_KEY": _verify_graphiq,
    "DATABASE_URL": _verify_supabase,
    "SUPABASE_PASSWORD": _verify_supabase,
}


def verify_setting(key: str) -> dict:
    if key not in _VERIFIERS:
        raise UnknownSetting(f"'{key}' has no verify check. Verifiable keys: {sorted(_VERIFIERS)}")
    return _VERIFIERS[key]().to_dict()
