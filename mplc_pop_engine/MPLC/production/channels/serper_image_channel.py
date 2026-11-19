#!/usr/bin/env python3
"""
Serper Image Search Evidence Channel — vertical-agnostic.

Built for the Custom Vertical Builder (see
claude/Custom_Vertical_Builder_Design.md in the MPLC project), reusing the
exact Serper-call / download / VLM mechanics already proven in
production/enrichers/corporate_fixed.py's search_corporate_images() /
validate_image() / analyze_image_vlm() -- same endpoint, same request shape,
same cost constant -- but config-driven (query templates + target/excluded
spaces passed in at construction) instead of corporate-hardcoded text, and
with entity matching delegated to the shared, hardened
production/workers/entity_verification.py module instead of corporate's own
weaker domain-substring check (is_domain_valid/domains_match). That
substitution is the explicit requirement from Jeff's 2026-11-18 scoping
("we need to make sure we have true entity resolution... too many false
positives previously") -- not an incidental choice.

Conforms to channels/base.py's EvidenceChannel interface so it's
interchangeable in a vertical's channel list.
"""

import base64
import io
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

import requests

try:
    import imghdr
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).parent.parent / "enrichers"))
    import image_sniff as imghdr

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from base import AccountContext, ChannelResult, EvidenceChannel  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent / "workers"))
from entity_verification import verify_entity_match  # noqa: E402

# Same constant as healthcare_unified.py/corporate_fixed.py -- see those
# files' own comments for the Serper plan math this is tied to. Duplicated
# here (not imported) because this channel must not depend on either
# existing enricher file; it is meant to eventually REPLACE both verticals'
# copies (design doc §5 step 5), not take on a dependency pointing back at
# them.
SERPER_COST_PER_CALL = 0.001
CLAUDE_INPUT_COST_PER_TOKEN = 0.000003
CLAUDE_OUTPUT_COST_PER_TOKEN = 0.000015


class SerperImageEvidenceChannel(EvidenceChannel):
    name = "serper_image_search"

    def __init__(
        self,
        query_templates: List[str],
        target_spaces: List[str],
        excluded_spaces: List[str],
        serper_key: Optional[str] = None,
        anthropic_key: Optional[str] = None,
        max_queries: int = 4,
        images_per_query: int = 5,
    ):
        """
        query_templates: e.g. ["{account_name} {city} {state} lobby",
            "{account_name} facility common area"] -- formatted per-account
            with AccountContext fields via str.format(**ctx_dict), same
            placeholder convention the config-generation helper produces.
        target_spaces / excluded_spaces: plain-English space names folded
            into the VLM prompt (see _vlm_prompt below) -- this is what
            makes the channel vertical-specific without a vertical
            subclass, per base.py's design note.
        """
        self.query_templates = query_templates
        self.target_spaces = target_spaces
        self.excluded_spaces = excluded_spaces
        self.serper_key = serper_key or os.getenv("SERPER_API_KEY")
        self.anthropic_key = anthropic_key or os.getenv("ANTHROPIC_API_KEY")
        self.max_queries = max_queries
        self.images_per_query = images_per_query

    def _format_queries(self, ctx: AccountContext) -> List[str]:
        fmt_args = {
            "account_name": ctx.account_name,
            "city": ctx.city,
            "state": ctx.state,
            "country": ctx.country,
        }
        out = []
        for template in self.query_templates[: self.max_queries]:
            try:
                out.append(template.format(**fmt_args))
            except (KeyError, IndexError):
                # A template referencing a field this ctx doesn't have
                # (e.g. {city} on an account with no city) shouldn't crash
                # the whole channel -- skip it, don't guess a value.
                continue
        return out

    def _search_images(self, ctx: AccountContext) -> tuple[list, float]:
        cost = 0.0
        all_images = []
        for query in self._format_queries(ctx):
            try:
                response = requests.post(
                    "https://google.serper.dev/images",
                    headers={"X-API-KEY": self.serper_key, "Content-Type": "application/json"},
                    data=json.dumps({"q": query, "num": 10}),
                    timeout=30,
                )
                cost += SERPER_COST_PER_CALL  # billed whether or not the call succeeds
                if response.status_code != 200:
                    continue
                images = response.json().get("images", [])
                for img in images[: self.images_per_query]:
                    all_images.append({
                        "url": img.get("imageUrl"),
                        "title": img.get("title", ""),
                        "source": img.get("link", ""),
                        "query": query,
                    })
                if all_images:
                    break  # same early-exit-on-first-hit convention as corporate_fixed.py
            except requests.RequestException:
                continue
        return all_images, cost

    def _download_and_validate(self, image_url: str) -> Optional[bytes]:
        try:
            response = requests.get(image_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10, stream=True)
            if response.status_code != 200:
                return None
            content = response.content
            size_kb = len(content) / 1024
            if size_kb < 5 or size_kb > 5000:
                return None
            if not imghdr.what(None, h=content):
                return None
            Image.open(io.BytesIO(content)).verify()
            return content
        except Exception:
            return None

    def _vlm_prompt(self, ctx: AccountContext) -> str:
        targets = ", ".join(self.target_spaces) or "a communal space"
        excludes = ", ".join(self.excluded_spaces) or "none specified"
        return f"""Analyze this image for TV evidence relevant to {ctx.account_name}.

Target spaces (look for TVs here): {targets}
Excluded spaces (do NOT count a TV found here): {excludes}

TV must be:
1. In one of the target spaces above
2. An entertainment/information TV showing content, not a menu board, logo
   display, black/powered-off screen, meeting-room display, or desk monitor

Answer ONLY with valid JSON:
{{
  "tv_detected": true|false,
  "tv_location": "<one of the target spaces, or none>",
  "confidence": "high|medium|low",
  "tv_powered_on": true|false,
  "reasoning": "Brief explanation"
}}"""

    def _analyze_vlm(self, image_content: bytes, ctx: AccountContext) -> tuple[Optional[dict], float]:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=self.anthropic_key)
            img_format = imghdr.what(None, h=image_content) or "jpeg"
            media_type = {"png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(
                img_format, "image/jpeg"
            )
            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                       "data": base64.b64encode(image_content).decode()}},
                        {"type": "text", "text": self._vlm_prompt(ctx)},
                    ],
                }],
            )
            cost = (response.usage.input_tokens * CLAUDE_INPUT_COST_PER_TOKEN
                    + response.usage.output_tokens * CLAUDE_OUTPUT_COST_PER_TOKEN)
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.strip("`").lstrip("json").strip()
            return json.loads(text), cost
        except Exception:
            return None, 0.0

    def search_evidence(self, ctx: AccountContext) -> ChannelResult:
        total_cost = 0.0
        images, search_cost = self._search_images(ctx)
        total_cost += search_cost
        if not images:
            return ChannelResult.rejected(self.name, "No images found", cost=total_cost)

        for img in images:
            content = self._download_and_validate(img["url"])
            if content is None:
                continue
            vlm_result, vlm_cost = self._analyze_vlm(content, ctx)
            total_cost += vlm_cost
            if not vlm_result or not vlm_result.get("tv_detected") or not vlm_result.get("tv_powered_on"):
                continue

            # Entity verification is NOT optional and NOT a per-channel ad
            # hoc check (design doc §8) -- the shared, hardened cascade
            # decides, using the LLM arbitration tier for ambiguous cases
            # (the Heritage-Crossing-style collision this was built for).
            verdict = verify_entity_match(
                account_name=ctx.account_name,
                account_industry=ctx.industry,
                account_state=ctx.state,
                account_website=ctx.website,
                evidence_url=img["source"],
                evidence_title=img["title"],
                use_llm_arbitration=True,
            )
            total_cost += verdict.get("details", {}).get("llm_arbitration", {}).get("cost", 0.0)
            if not verdict["match"]:
                continue

            return ChannelResult(
                tier="PROSPECT",
                channel=self.name,
                cost=total_cost,
                evidence={
                    "source_url": img["source"],
                    "evidence_photo_location": img["url"],
                    "evidence_description": vlm_result.get("reasoning", ""),
                    "space_type": vlm_result.get("tv_location"),
                    "tv_powered_on": bool(vlm_result.get("tv_powered_on")),
                    "vlm_confidence": vlm_result.get("confidence", "low"),
                },
                details={"entity_match": verdict},
            )

        return ChannelResult.rejected(self.name, "No validated TV evidence found", cost=total_cost)
