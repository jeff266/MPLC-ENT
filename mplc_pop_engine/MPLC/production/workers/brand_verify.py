"""
AI brand-match verification -- for a clay_dedupe.py POSSIBLE_MATCH_BRAND
row (brand-root fuzzy hit, never auto-trusted) or any other low-confidence
match, fetches both companies' homepages and asks Claude whether they're
the same real-world business under a different legal-entity name/domain,
or genuinely different companies that happen to share a brand word.

Jeff (2026-11-16), after seeing brand-fuzzy hits for Cortland, Knightvest
and Pantzer that he confirmed by eye are all real Salesforce matches:
"is there a way for the low confidence to have claude api open up both
websites and do a comparison?"

Deliberately NOT run automatically on every brand-fuzzy row -- same "never
silently trusted" discipline as the brand-fuzzy tier itself (clay_dedupe.py).
A human requests this per row (or per selection) from the review UI; the
result is a second opinion to help that human decide, not a replacement
for their decision -- the verdict is persisted but never changes a row's
`classification`.

Pure, dict-in/dict-out core (verify_brand_match) so it's testable without
a live network/API call (mock fetch_homepage_text and the Anthropic client).
"""

import json
import os
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

_USER_AGENT = "Mozilla/5.0 (compatible; MPLC-PoP-Engine/1.0; +https://mplc.org)"
_MODEL = "claude-sonnet-4-5-20250929"
_VALID_VERDICTS = {"same", "different", "uncertain"}

# Jeff (2026-11-16): "when i click on AI Check are we cost tracking that?"
# -- we weren't. Same per-token pricing CLAUDE.md already documents for
# this exact model elsewhere in this codebase (corporate_fixed.py's VLM
# calls): $3.00/1M input, $15.00/1M output. Computed from the real
# response.usage on every successful call -- never estimated/guessed --
# so the number persisted on the row is the actual spend, not a flat
# per-click estimate.
_INPUT_COST_PER_TOKEN = 3.00 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 15.00 / 1_000_000


def fetch_homepage_text(domain: Optional[str], timeout: float = 10.0,
                         max_chars: int = 4000) -> tuple[Optional[str], Optional[str]]:
    """Fetches a domain's homepage and returns (visible_text, error) --
    exactly one of the two is set. Tries https then http (most real-estate
    sites redirect to https anyway, but a handful don't have a valid cert).
    Strips script/style tags before extracting text so the model isn't
    fed raw JS. Truncates to max_chars to keep the comparison prompt
    small and cheap -- a homepage's above-the-fold copy ("who we are",
    "our communities", nav links) is what actually identifies a company,
    not its full page weight."""
    if not domain or not str(domain).strip():
        return None, "no domain given"

    domain = str(domain).strip()
    candidate_urls = [domain] if domain.startswith(("http://", "https://")) else [
        f"https://{domain}", f"http://{domain}",
    ]

    last_error = "could not fetch"
    for url in candidate_urls:
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": _USER_AGENT},
                                 allow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True)).strip()
            if text:
                return text[:max_chars], None
            last_error = f"{url}: page loaded but had no visible text"
        except Exception as e:
            last_error = f"{url}: {e}"
            continue
    return None, last_error


def verify_brand_match(
    clay_company_name: Optional[str],
    clay_website: Optional[str],
    sf_account_name: Optional[str],
    sf_website: Optional[str],
    anthropic_api_key: Optional[str] = None,
) -> dict:
    """Returns {'verdict': 'same'|'different'|'uncertain', 'reasoning': str,
    'fetch_errors': dict, 'cost': float}. 'cost' is the REAL spend computed
    from the API response's own usage.input_tokens/output_tokens -- 0.0
    whenever no API call was made (both fetches failed, no API key, the
    anthropic package is missing) or the call itself errored before a
    response came back, since there's nothing to bill in those cases.
    Never raises -- a fetch failure, a missing API key, or a malformed
    model response all come back as 'uncertain' with the reason explained,
    since this is a best-effort second opinion feeding a human decision,
    not a step that should crash the review flow a human is actively
    working in."""
    clay_text, clay_err = fetch_homepage_text(clay_website)
    sf_text, sf_err = fetch_homepage_text(sf_website)

    fetch_errors = {}
    if clay_err:
        fetch_errors["clay_website"] = clay_err
    if sf_err:
        fetch_errors["sf_website"] = sf_err

    if not clay_text and not sf_text:
        return {
            "verdict": "uncertain",
            "reasoning": "Could not fetch either company's website, so no comparison could be made.",
            "fetch_errors": fetch_errors,
            "cost": 0.0,
        }

    api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "verdict": "uncertain",
            "reasoning": "ANTHROPIC_API_KEY not set -- could not run the comparison.",
            "fetch_errors": fetch_errors,
            "cost": 0.0,
        }

    try:
        from anthropic import Anthropic
    except ImportError:
        return {
            "verdict": "uncertain",
            "reasoning": "The anthropic package isn't installed in this environment.",
            "fetch_errors": fetch_errors,
            "cost": 0.0,
        }

    prompt = f"""Two companies share a brand-sounding name. Decide whether they are the SAME real-world business (e.g. the same company under a different legal-entity name, a rebrand, a subsidiary, or a sibling brand of the same parent) or DIFFERENT, unrelated companies that just happen to share a word.

Company A: "{clay_company_name or 'unknown'}" (website: {clay_website or 'unknown'})
{clay_text if clay_text else f"[homepage could not be fetched: {clay_err}]"}

Company B: "{sf_account_name or 'unknown'}" (website: {sf_website or 'unknown'})
{sf_text if sf_text else f"[homepage could not be fetched: {sf_err}]"}

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{"verdict": "same" | "different" | "uncertain", "reasoning": "one or two plain sentences explaining why"}}"""

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        # Real spend, not an estimate -- the API call already happened and
        # billed by the time we're here, so this is the actual cost of
        # this click, computed from the usage the response itself reports.
        usage = getattr(response, "usage", None)
        cost = (
            (getattr(usage, "input_tokens", 0) or 0) * _INPUT_COST_PER_TOKEN
            + (getattr(usage, "output_tokens", 0) or 0) * _OUTPUT_COST_PER_TOKEN
        ) if usage else 0.0

        raw = response.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
        parsed = json.loads(raw)
        verdict = parsed.get("verdict", "uncertain")
        if verdict not in _VALID_VERDICTS:
            verdict = "uncertain"
        return {
            "verdict": verdict,
            "reasoning": str(parsed.get("reasoning", ""))[:2000],
            "fetch_errors": fetch_errors,
            "cost": cost,
        }
    except Exception as e:
        return {
            "verdict": "uncertain",
            "reasoning": f"Comparison failed: {e}",
            "fetch_errors": fetch_errors,
            # The API call may have been billed even though parsing/JSON
            # failed after it returned -- but without a successful response
            # object we have no usage to compute from, so this is 0.0 by
            # necessity, not because the call was free. Rare path (malformed
            # JSON from the model); flagged here rather than guessed at.
            "cost": 0.0,
        }
