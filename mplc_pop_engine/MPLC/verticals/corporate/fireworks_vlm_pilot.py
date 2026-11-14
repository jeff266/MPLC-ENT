#!/usr/bin/env python3
"""
Fireworks (open-source VLM) vs. Claude Sonnet side-by-side comparison, for
the corporate PoP waterfall's image-classification step.

WHY THIS EXISTS (Jeff, 2026-11-14): "where in the engine can I get good
value from calling out Fireworks open source models?" The VLM image/frame
classification calls are the engine's real cost driver (8 call sites across
corporate/healthcare/mdu, $0.0045-$0.0085 each per CLAUDE.md). This pilots
the cheapest plausible swap -- the corporate image-classification call in
production/enrichers/corporate_fixed.py's analyze_image_vlm() -- against a
real Fireworks-hosted open VLM, on your real 42-account ground truth.

MODEL CHOICE (verified 2026-11-14 against Fireworks' own docs/pricing
pages, not guessed from training data):
  - Qwen2.5-VL-32B/72B-Instruct, the obvious first guess, is NOT serverless
    on Fireworks right now -- it requires a dedicated on-demand deployment
    (GPU-hour billing), which is the wrong economics for a low-volume
    per-image classification call. Steered away from it for that reason.
  - DeepSeek V4.1 Flash Vision (accounts/fireworks/models/deepseek-v4p1-flash)
    IS serverless, pay-per-token, vision-capable, and ~10x cheaper than
    Sonnet: $0.30/$1.20 per M tokens vs. Sonnet's $3/$15.
  - GLM 5.3 Flash (accounts/fireworks/models/glm-5p3-flash) is the even
    cheaper serverless vision option: $0.15/$0.50 per M tokens (~20x).
  Both are tried below; which one actually holds up on YOUR images is an
  empirical question this script answers, not something to assume from
  the price sheet.

WHAT THIS DOES NOT DO: it does not change corporate_fixed.py or touch
production in any way. It imports CorporateEnricher and calls its real,
unmodified search_corporate_images() / is_domain_valid() / is_us_relevant()
/ validate_image() methods to get the exact same real candidate images the
production pipeline would see for each ground-truth account, then runs
BOTH the existing analyze_image_vlm() (Sonnet, already costed) and the new
Fireworks call on each one, side by side. No gating/cascade logic yet --
that's the next step, once this shows whether a cheap model agrees with
Sonnet often enough to trust as a first-pass filter.

REQUIRES (all via real network calls, real cost -- this is not a dry run):
  - SERPER_API_KEY, ANTHROPIC_API_KEY, RAPIDAPI_KEY not needed here
    (RapidAPI is video-only) but SERPER_API_KEY and ANTHROPIC_API_KEY are,
    since this calls the real search + real Sonnet classification.
  - FIREWORKS_API_KEY (already written to production/workers/.env this
    session -- 2026-11-14).
  - Network egress to google.serper.dev, api.anthropic.com, and
    api.fireworks.ai. This sandbox's proxy blocks api.fireworks.ai outright
    (confirmed via /__agentproxy/status: "policy denial" on
    api.fireworks.ai:443) -- this script has NOT been executed here. Run
    it wherever you have open egress (your machine or a droplet).
  - A ground-truth fixture: a JSON/CSV list of the 42 corporate accounts
    (name, website, operating_market) -- CLAUDE.md references
    ground_truth/corporate_42_accounts.json but that file isn't actually
    in this repo checkout (confirmed 2026-11-14). Point --ground-truth at
    wherever you keep it, or pass --accounts-csv for an ad-hoc list.

USAGE:
    python3 fireworks_vlm_pilot.py --ground-truth path/to/corporate_42_accounts.json
    python3 fireworks_vlm_pilot.py --accounts-csv path/to/accounts.csv --limit 10

OUTPUT: a per-image comparison table (Sonnet verdict vs. each Fireworks
model's verdict, cost of each) plus a summary: agreement rate, and --
the metric that actually matters here -- how many of Sonnet's real
PROSPECT-qualifying images a given Fireworks model would have REJECTED
(false negatives on the costly side: silently losing real inventory is
worse than a few extra cheap-model false positives that still get caught
by whatever gate comes after it).
"""

import argparse
import base64
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests

# Import the REAL production enricher rather than re-implementing its
# pipeline -- so "what images does this account actually produce" is
# identical to what corporate_fixed.py would do in production.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "production" / "enrichers"))
from corporate_fixed import CorporateEnricher  # noqa: E402

FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY")
FIREWORKS_ENDPOINT = "https://api.fireworks.ai/inference/v1/chat/completions"

# model id -> (input $/M tokens, output $/M tokens) -- from Fireworks'
# own pricing pages, verified 2026-11-14 (see module docstring).
FIREWORKS_MODELS = {
    "deepseek-v4.1-flash": {
        "id": "accounts/fireworks/models/deepseek-v4p1-flash",
        "input_per_m": 0.30,
        "output_per_m": 1.20,
    },
    "glm-5.3-flash": {
        "id": "accounts/fireworks/models/glm-5p3-flash",
        "input_per_m": 0.15,
        "output_per_m": 0.50,
    },
}

# Same cost formula shape as corporate_fixed.py's analyze_image_vlm() for
# Sonnet (input/1M*3.0 + output/1M*15.0) -- just with each Fireworks
# model's own per-token rate substituted in, so the two sides of the
# comparison are priced the same way.
SONNET_INPUT_PER_M = 3.00
SONNET_OUTPUT_PER_M = 15.00


def _media_type_for(image_content: bytes) -> str:
    try:
        import imghdr  # Python < 3.13
    except ModuleNotFoundError:
        # Removed in Python 3.13 (PEP 594) -- reuse the same shim
        # corporate_fixed.py and the other enrichers already depend on
        # (production/enrichers/image_sniff.py), already on sys.path from
        # this module's own corporate_fixed import above.
        import image_sniff as imghdr
    fmt = imghdr.what(None, h=image_content)
    return {
        "png": "image/png", "gif": "image/gif",
        "jpeg": "image/jpeg", "jpg": "image/jpeg", "webp": "image/webp",
    }.get(fmt, "image/jpeg")


def analyze_image_vlm_fireworks(
    image_content: bytes, company_name: str, source: str, model_key: str,
) -> Optional[dict]:
    """Same prompt and expected JSON shape as corporate_fixed.py's
    CorporateEnricher.analyze_image_vlm() -- the ONLY thing that differs
    from the production Sonnet call is which model answers it, so any
    difference in verdict is attributable to the model, not the prompt."""
    if not FIREWORKS_API_KEY:
        raise RuntimeError("FIREWORKS_API_KEY not set")

    model = FIREWORKS_MODELS[model_key]
    media_type = _media_type_for(image_content)
    img_b64 = base64.b64encode(image_content).decode("utf-8")

    # Prompt copied verbatim from corporate_fixed.py's analyze_image_vlm()
    # (2026-11-14) -- deliberately NOT paraphrased, so this is a model
    # swap, not a model-and-prompt swap.
    prompt = f"""Analyze this corporate office image for TV evidence.

Company: {company_name}
Source: {source}

Look for TVs in employee-accessible communal spaces:
- Gym/fitness center
- Cafeteria/break room
- Employee lounge/common area
- Lobby (if clearly for employee use)

TV must be:
1. In a space where employees gather
2. Entertainment/information TV (showing content when on)
3. NOT in meeting rooms or private offices

CRITICAL EXCLUSIONS:
- Menu boards (restaurant-style displays)
- Logo displays / brand signage
- Black screens (powered off)
- Meeting room displays
- Computer monitors at desks
- Digital wayfinding screens
- Reception desk monitors

Answer ONLY with valid JSON:
{{
  "tv_detected": true|false,
  "tv_location": "gym|cafeteria|employee_lounge|break_room|lobby|none",
  "confidence": "high|medium|low",
  "is_entertainment_tv": true|false,
  "is_communal_space": true|false,
  "tv_powered_on": true|false,
  "is_menu_board": false,
  "is_logo_display": false,
  "is_black_screen": false,
  "reasoning": "Brief explanation"
}}"""

    try:
        response = requests.post(
            FIREWORKS_ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {FIREWORKS_API_KEY}",
            },
            json={
                "model": model["id"],
                "max_tokens": 300,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{media_type};base64,{img_b64}"
                        }},
                    ],
                }],
            },
            timeout=30,
        )
    except requests.RequestException as e:
        return {"error": str(e), "error_type": type(e).__name__}

    if response.status_code != 200:
        return {"error": f"Fireworks API error {response.status_code}: {response.text[:200]}"}

    data = response.json()
    text_content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})

    cost = (
        usage.get("prompt_tokens", 0) / 1_000_000 * model["input_per_m"]
        + usage.get("completion_tokens", 0) / 1_000_000 * model["output_per_m"]
    )

    # Same defensive JSON extraction corporate_fixed.py uses for Sonnet --
    # a model can wrap JSON in prose/markdown fences despite instructions.
    try:
        start = text_content.index("{")
        end = text_content.rindex("}") + 1
        result = json.loads(text_content[start:end])
    except (ValueError, json.JSONDecodeError):
        return {"error": f"Could not parse JSON from response: {text_content[:200]}", "cost": cost}

    result["cost"] = cost
    result["raw_model"] = model["id"]
    return result


def sonnet_qualifies(analysis: dict) -> bool:
    """Exact qualification check from corporate_fixed.py's enrich_account()
    (2026-11-14) -- reused so 'would this have been a PROSPECT' means the
    same thing on both sides of the comparison."""
    return bool(
        analysis.get("tv_detected")
        and analysis.get("is_entertainment_tv")
        and analysis.get("is_communal_space")
        and analysis.get("confidence") in ("high", "medium")
        and not analysis.get("is_menu_board", False)
        and not analysis.get("is_logo_display", False)
        and not analysis.get("is_black_screen", False)
    )


def load_accounts(args) -> list[dict]:
    if args.ground_truth:
        with open(args.ground_truth) as f:
            data = json.load(f)
        # Accept either a bare list or {"accounts": [...]}
        accounts = data if isinstance(data, list) else data.get("accounts", [])
    elif args.accounts_csv:
        with open(args.accounts_csv, newline="") as f:
            accounts = list(csv.DictReader(f))
    else:
        raise SystemExit("Pass --ground-truth (JSON) or --accounts-csv.")

    normalized = []
    for a in accounts:
        normalized.append({
            "company_name": a.get("company_name") or a.get("account_name") or a.get("name"),
            "website": a.get("website") or a.get("official_website") or "",
            "operating_market": a.get("operating_market") or "United States",
        })
    if args.limit:
        normalized = normalized[: args.limit]
    return normalized


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", help="Path to ground-truth JSON (list of accounts, or {accounts: [...]})")
    parser.add_argument("--accounts-csv", help="Path to a CSV with company_name/website/operating_market columns")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N accounts (for a quick/cheap smoke test)")
    parser.add_argument("--models", nargs="+", default=list(FIREWORKS_MODELS.keys()),
                         choices=list(FIREWORKS_MODELS.keys()),
                         help="Which Fireworks models to compare against Sonnet")
    args = parser.parse_args()

    if not FIREWORKS_API_KEY:
        raise SystemExit("FIREWORKS_API_KEY not set in the environment.")

    accounts = load_accounts(args)
    print(f"Running comparison on {len(accounts)} account(s), models: {args.models}\n")

    enricher = CorporateEnricher(enable_image_search=True)

    rows = []
    for acct in accounts:
        company_name = acct["company_name"]
        print(f"=== {company_name} ===")
        images, search_cost = enricher.search_corporate_images(company_name, acct["operating_market"])
        if not images:
            print("  No images found, skipping.\n")
            continue

        for img in images[:10]:
            is_valid_domain, domain_reason, validation_cost = enricher.is_domain_valid(
                img["url"], company_name,
                official_website=acct["website"],
                image_title=img.get("title", ""),
                page_url=img.get("source", ""),
            )
            if not is_valid_domain:
                continue
            if not enricher.is_us_relevant(img["url"], img.get("title", ""), acct["operating_market"]):
                continue
            image_content = enricher.validate_image(img["url"])
            if not image_content:
                continue

            sonnet_result = enricher.analyze_image_vlm(image_content, company_name, "serper_image_search")
            if not sonnet_result:
                continue
            sonnet_pass = sonnet_qualifies(sonnet_result)

            row = {
                "company_name": company_name,
                "image_url": img["url"],
                "sonnet_pass": sonnet_pass,
                "sonnet_cost": sonnet_result.get("cost", 0.0),
                "sonnet_confidence": sonnet_result.get("confidence"),
            }

            for model_key in args.models:
                fw_result = analyze_image_vlm_fireworks(image_content, company_name, "serper_image_search", model_key)
                if fw_result is None or "error" in fw_result:
                    row[f"{model_key}_pass"] = None
                    row[f"{model_key}_error"] = fw_result.get("error") if fw_result else "no result"
                else:
                    row[f"{model_key}_pass"] = sonnet_qualifies(fw_result)
                    row[f"{model_key}_cost"] = fw_result.get("cost", 0.0)
                    row[f"{model_key}_confidence"] = fw_result.get("confidence")
                time.sleep(0.5)  # be polite to the API

            rows.append(row)
            verdict = "PROSPECT" if sonnet_pass else "reject"
            print(f"  [{verdict}] Sonnet=${row['sonnet_cost']:.5f}  " +
                  "  ".join(f"{k}={row.get(k+'_pass')}" for k in args.models))

        print()

    if not rows:
        print("No candidate images were analyzed -- nothing to compare.")
        return

    # ---- Summary ----
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    n = len(rows)
    sonnet_prospects = sum(1 for r in rows if r["sonnet_pass"])
    print(f"Images analyzed: {n}  |  Sonnet PROSPECT rate: {sonnet_prospects}/{n}")
    print(f"Sonnet total cost: ${sum(r['sonnet_cost'] for r in rows):.4f}\n")

    for model_key in args.models:
        valid_rows = [r for r in rows if r.get(f"{model_key}_pass") is not None]
        if not valid_rows:
            print(f"{model_key}: no successful responses (check {model_key}_error above)")
            continue
        agree = sum(1 for r in valid_rows if r[f"{model_key}_pass"] == r["sonnet_pass"])
        # The costly error: Sonnet said PROSPECT, this model said reject --
        # a real lead this model would have silently thrown away.
        false_negatives = sum(1 for r in valid_rows if r["sonnet_pass"] and not r[f"{model_key}_pass"])
        false_positives = sum(1 for r in valid_rows if not r["sonnet_pass"] and r[f"{model_key}_pass"])
        total_cost = sum(r.get(f"{model_key}_cost", 0.0) for r in valid_rows)
        sonnet_cost_same_set = sum(r["sonnet_cost"] for r in valid_rows)

        print(f"--- {model_key} ({FIREWORKS_MODELS[model_key]['id']}) ---")
        print(f"  Agreement with Sonnet: {agree}/{len(valid_rows)} ({100*agree/len(valid_rows):.1f}%)")
        print(f"  False negatives (missed a real PROSPECT): {false_negatives}/{len(valid_rows)}")
        print(f"  False positives (flagged a reject):        {false_positives}/{len(valid_rows)}")
        print(f"  Cost: ${total_cost:.4f} vs. Sonnet's ${sonnet_cost_same_set:.4f} on the same images "
              f"({(sonnet_cost_same_set/total_cost):.1f}x cheaper)" if total_cost else "  Cost: $0.00 (no successful calls)")
        print()

    out_path = Path("fireworks_vlm_pilot_results.json")
    out_path.write_text(json.dumps(rows, indent=2))
    print(f"Full per-image results written to {out_path.resolve()}")


if __name__ == "__main__":
    main()
