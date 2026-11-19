#!/usr/bin/env python3
"""
One-time config-generation helper for the Custom Vertical Builder.

Turns Jeff's plain-English channel description (e.g. "photos of the gym or
break room at corporate HQ") into the structured config
SerperImageEvidenceChannel / YouTubeVideoEvidenceChannel /
WebsiteScrapeEvidenceChannel need (query templates, target/excluded
spaces). Called exactly ONCE per channel, at vertical-setup time when Jeff
saves a channel's description via the backend API -- never per account --
per the explicit mechanism decision in Custom_Vertical_Builder_Design.md
§2 ("One-time LLM call at vertical setup (recommended)"). Runtime cost per
account enriched is therefore unaffected; this call's own cost is logged
separately into CustomVerticalChannel.config_generated_cost, not folded
into the per-account cost_breakdown buckets.

The result is meant to be reviewed and hand-edited by Jeff afterward (see
design doc §2's note: "Jeff can see and hand-edit the generated config
afterward rather than only trusting the LLM's first pass") -- this module
only produces the first draft.
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

CLAUDE_INPUT_COST_PER_TOKEN = 0.000003
CLAUDE_OUTPUT_COST_PER_TOKEN = 0.000015

VALID_CHANNEL_TYPES = {"serper_image", "youtube_video", "website_scrape"}


@dataclass
class GeneratedChannelConfig:
    """What gets stored as a CustomVerticalChannel row's config_json (plus
    config_generated_cost, stored alongside it, not inside it)."""
    query_templates: List[str] = field(default_factory=list)
    target_spaces: List[str] = field(default_factory=list)
    excluded_spaces: List[str] = field(default_factory=list)
    cost: float = 0.0
    raw_model_output: Optional[str] = None  # kept for audit/debugging, not shown to the VLM

    def to_json(self) -> str:
        return json.dumps({
            "query_templates": self.query_templates,
            "target_spaces": self.target_spaces,
            "excluded_spaces": self.excluded_spaces,
        })


_PROMPT_TEMPLATE = """You are configuring an automated evidence-detection channel for a sales
prospecting tool called MPLC's PoP Detection Engine. The tool looks for
photo/video evidence that a business has a public TV playing content in a
customer-facing space (not a private office, not a staff-only area).

A user described what this particular channel should look for, in their
own words:

"{description}"

The channel type is: {channel_type}
({channel_type_note})

Produce a JSON object with exactly these fields:
{{
  "query_templates": [list of 2-4 search query templates, each a string
    that may use the placeholders {{account_name}}, {{city}}, {{state}},
    {{country}} -- these get filled in per-account at runtime. Templates
    should be the kind of query a person would type into Google Images or
    YouTube search to find photos/video of the described space for a named
    business. Do not include quotes around placeholder names.],
  "target_spaces": [list of 1-4 short plain-English space names that
    COUNT as a match for this channel -- e.g. "gym", "break room",
    "waiting area". Derive these directly from the user's description.],
  "excluded_spaces": [list of 1-4 short plain-English space names that
    should NOT count, even if a TV is visible there -- e.g. "private
    office", "meeting room", "patient room". Include common false-positive
    spaces for this kind of business even if the user didn't mention them.]
}}

Answer with ONLY the JSON object, no other text."""

_CHANNEL_TYPE_NOTES = {
    "serper_image": "This channel searches Google Images via Serper and analyzes results with a vision model.",
    "youtube_video": "This channel searches YouTube via Serper, downloads matching videos, extracts frames, and analyzes them with YOLO + a vision model.",
    "website_scrape": "This channel scrapes the business's own website (gallery/amenity pages) for photos and analyzes them with YOLO + a vision model. Query templates are unused for this channel type -- target_spaces/excluded_spaces are still used to build its VLM prompt.",
}


def generate_channel_config(
    description: str,
    channel_type: str,
    anthropic_api_key: Optional[str] = None,
) -> GeneratedChannelConfig:
    """The one-time call. Raises ValueError for an unrecognized
    channel_type (caught by the backend API, not swallowed here -- a typo
    in channel_type shouldn't silently produce an empty config)."""
    if channel_type not in VALID_CHANNEL_TYPES:
        raise ValueError(f"Unknown channel_type '{channel_type}', expected one of {sorted(VALID_CHANNEL_TYPES)}")

    api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)

    prompt = _PROMPT_TEMPLATE.format(
        description=description,
        channel_type=channel_type,
        channel_type_note=_CHANNEL_TYPE_NOTES[channel_type],
    )

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    cost = (response.usage.input_tokens * CLAUDE_INPUT_COST_PER_TOKEN
            + response.usage.output_tokens * CLAUDE_OUTPUT_COST_PER_TOKEN)
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        # Don't guess at a partial config -- surface the failure so the
        # API layer can tell Jeff to retry/hand-write it, consistent with
        # CLAUDE.md's "flag explicitly rather than improvising around a
        # schema mismatch."
        raise ValueError(f"Model did not return valid JSON config: {e}\nRaw output: {text}") from e

    return GeneratedChannelConfig(
        query_templates=parsed.get("query_templates", []),
        target_spaces=parsed.get("target_spaces", []),
        excluded_spaces=parsed.get("excluded_spaces", []),
        cost=cost,
        raw_model_output=text,
    )


@dataclass
class GeneratedMatchKeywords:
    """What gets stored as CustomVertical.match_keywords_json (plus
    match_keywords_generated_cost, stored alongside it, same split as
    GeneratedChannelConfig above)."""
    keywords: List[str] = field(default_factory=list)
    cost: float = 0.0
    raw_model_output: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps({"keywords": self.keywords})


_MATCH_KEYWORDS_PROMPT_TEMPLATE = """You are configuring account routing for a sales prospecting tool called
MPLC's PoP Detection Engine. A new custom vertical called "{display_name}"
was just defined, with these evidence-channel descriptions (what the
person is looking for photo/video evidence of):

{channel_descriptions}

Your job: produce a list of plain keyword/phrase strings that would
plausibly appear in a Salesforce "Industry" field value or a company's
account name for a business that belongs to this vertical. These keywords
will be used for a cheap, free, case-insensitive substring match against
every account's industry text and account name -- NOT for a search query,
and NOT for anything shown to a vision model. Think "what words would a
CRM industry picklist or a company name contain for this kind of
business," not "what would I search Google Images for."

Keep each keyword short (1-4 words), avoid overly generic single words
that would match too broadly (e.g. avoid "center" or "services" alone),
and include common synonyms/variants a real Salesforce export might use.

Produce a JSON object with exactly this field:
{{
  "keywords": [list of 3-10 short keyword/phrase strings]
}}

Answer with ONLY the JSON object, no other text."""


def generate_match_keywords(
    display_name: str,
    channel_descriptions: List[str],
    anthropic_api_key: Optional[str] = None,
) -> GeneratedMatchKeywords:
    """The one-time call behind CustomVertical.match_keywords_json --
    same "generate once, hand-editable afterward" principle as
    generate_channel_config above, just producing industry-match
    keywords for the separate, additive custom-vertical tagger
    (pipeline_runner.match_custom_verticals()) instead of a channel's
    search/VLM config. Never called per account -- only when Jeff clicks
    "Generate match keywords" (or "Regenerate") in Settings."""
    if not channel_descriptions:
        raise ValueError(
            "Can't generate match keywords for a vertical with no channels yet -- "
            "add at least one channel (with a description) first."
        )

    api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)

    prompt = _MATCH_KEYWORDS_PROMPT_TEMPLATE.format(
        display_name=display_name,
        channel_descriptions="\n".join(f"- {d}" for d in channel_descriptions),
    )

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    cost = (response.usage.input_tokens * CLAUDE_INPUT_COST_PER_TOKEN
            + response.usage.output_tokens * CLAUDE_OUTPUT_COST_PER_TOKEN)
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON for match keywords: {e}\nRaw output: {text}") from e

    keywords = parsed.get("keywords", [])
    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        raise ValueError(f"Model's 'keywords' field was not a list of strings: {keywords!r}")

    return GeneratedMatchKeywords(keywords=keywords, cost=cost, raw_model_output=text)
