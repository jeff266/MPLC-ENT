#!/usr/bin/env python3
"""
Execution runner for config-driven custom verticals.

Loads a custom vertical's enabled channels in step_order, runs them against
one account with early exit on the first PROSPECT -- the same convention
every hardcoded vertical (healthcare_unified.py, corporate_fixed.py,
mdu_unified.py) already implements by hand, per
Custom_Vertical_Builder_Design.md §5. Writes the same Evidence Persistence
Schema CLAUDE.md requires, so Stage 4/5 (evidence labeling, outcome
routing) work on a custom vertical's output unchanged.

This module is pure orchestration: it does not touch the DB directly (the
caller passes in plain channel-config rows, already loaded) and does not
instantiate channels itself for a channel_type it doesn't recognize -- it
raises, rather than silently skipping a misconfigured step, per CLAUDE.md's
"stop and flag explicitly rather than improvising around a schema
mismatch."
"""

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "production" / "channels"))
from base import AccountContext, ChannelResult, EvidenceChannel  # noqa: E402
from serper_image_channel import SerperImageEvidenceChannel  # noqa: E402
from youtube_video_channel import YouTubeVideoEvidenceChannel  # noqa: E402
from website_scrape_channel import WebsiteScrapeEvidenceChannel  # noqa: E402


@dataclass
class ChannelConfigRow:
    """Plain mirror of a CustomVerticalChannel DB row -- kept decoupled
    from SQLAlchemy so this module has no backend/ dependency and can be
    unit-tested with mocks, consistent with this engagement's "no live API
    keys in this environment" constraint (verified via logic tests, not
    live end-to-end calls)."""
    step_order: int
    channel_type: str   # "serper_image" | "youtube_video" | "website_scrape"
    enabled: bool
    config_json: Optional[str]  # JSON: query_templates, target_spaces, excluded_spaces


# Default VLM/YOLO/scrape wiring for website_scrape -- target_object_classes
# and gallery_page_keywords aren't part of the LLM-generated config schema
# (config_from_description.py only produces query_templates/target/excluded
# spaces), so a reasonable TV-detection default is used here. A vertical
# that needs different YOLO classes can still construct
# WebsiteScrapeEvidenceChannel directly and bypass this factory.
_WEBSITE_SCRAPE_DEFAULT_CLASSES = ["tv", "tvmonitor"]
_WEBSITE_SCRAPE_DEFAULT_GALLERY_KEYWORDS = ["gallery", "amenities", "amenity", "photos", "tour"]


def _vlm_prompt_from_spaces(target_spaces: List[str], excluded_spaces: List[str]):
    """Builds the callable vlm_classification_prompt WebsiteImageEvidenceChannel
    expects, from the same target/excluded-spaces vocabulary the other two
    channel types use -- so all three channel types are configured with
    one consistent concept, per Jeff's original request to "define search
    terms or descriptions... webscraping... ways to scrape in general" as
    one coherent configuration surface, not three unrelated ones."""
    targets = ", ".join(target_spaces) or "a communal space"
    excludes = ", ".join(excluded_spaces) or "none specified"

    def _prompt(property_name: str, yolo_confidence: float) -> str:
        return f"""Analyze this image for TV evidence relevant to {property_name}.

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
    return _prompt


def build_channel(row: ChannelConfigRow) -> EvidenceChannel:
    """Instantiates the real EvidenceChannel for one config row. Raises
    ValueError for an unrecognized channel_type or missing config -- never
    silently returns a no-op channel, since that would show up as a false
    REJECTED rather than a visible configuration error."""
    if not row.config_json:
        raise ValueError(
            f"Channel step {row.step_order} ({row.channel_type}) has no generated config -- "
            "run config generation before enabling this channel."
        )
    cfg: Dict[str, Any] = json.loads(row.config_json)
    query_templates = cfg.get("query_templates", [])
    target_spaces = cfg.get("target_spaces", [])
    excluded_spaces = cfg.get("excluded_spaces", [])

    if row.channel_type == "serper_image":
        return SerperImageEvidenceChannel(
            query_templates=query_templates,
            target_spaces=target_spaces,
            excluded_spaces=excluded_spaces,
        )
    if row.channel_type == "youtube_video":
        return YouTubeVideoEvidenceChannel(
            query_templates=query_templates,
            target_spaces=target_spaces,
            excluded_spaces=excluded_spaces,
        )
    if row.channel_type == "website_scrape":
        return WebsiteScrapeEvidenceChannel(
            target_object_classes=_WEBSITE_SCRAPE_DEFAULT_CLASSES,
            gallery_page_keywords=_WEBSITE_SCRAPE_DEFAULT_GALLERY_KEYWORDS,
            vlm_classification_prompt=_vlm_prompt_from_spaces(target_spaces, excluded_spaces),
        )
    raise ValueError(f"Unknown channel_type '{row.channel_type}'")


def build_channels(channel_rows: List[ChannelConfigRow]) -> List[EvidenceChannel]:
    """Filters to enabled rows, sorts by step_order, and builds each
    channel ONCE. Call this once per vertical per batch (run_vertical_for_
    accounts does this) and reuse the result across every account --
    never rebuild per account.

    This matters beyond construction overhead: YouTubeVideoEvidenceChannel
    lazy-loads its YOLO model on first use and caches it on the instance
    (self._yolo_model) specifically so a batch pays that load cost once.
    Calling build_channel() fresh for every account defeats that cache
    entirely -- the model gets reloaded from disk on every single account.
    Found during a 2026-11-18 optimization pass; the original per-account
    build_channel() call inside run_vertical_for_account is kept below
    only as a standalone single-row builder other callers can still use
    directly."""
    ordered_rows = sorted(
        (r for r in channel_rows if r.enabled),
        key=lambda r: r.step_order,
    )
    # Fail fast on a bad/missing config for ANY row before running a
    # single account -- a setup error, not a per-account failure, so it
    # shouldn't surface only after burning cost on account #1.
    return [build_channel(row) for row in ordered_rows]


def run_vertical_for_account(
    vertical_key: str,
    channels: List[EvidenceChannel],
    ctx: AccountContext,
) -> Dict[str, Any]:
    """Runs one account through a custom vertical's ALREADY-BUILT, ordered
    channel list with early exit on PROSPECT. Takes built EvidenceChannel
    instances (from build_channels(), built once per batch), not raw DB
    rows -- see build_channels()'s docstring for why rebuilding per
    account is wrong. Returns an Evidence Persistence Schema record
    (CLAUDE.md) -- same shape whether a channel hit, all channels
    REJECTED, or a channel errored (errors are tracked separately, per
    CLAUDE.md QA requirement #2: failed calls are not a clean REJECTED).
    """
    cost_breakdown: Dict[str, float] = {}
    channel_errors: List[Dict[str, str]] = []
    rejections: List[Dict[str, Any]] = []

    for channel in channels:
        try:
            result: ChannelResult = channel.search_evidence(ctx)
        except Exception as e:
            # A genuine exception during a live call (network error, etc.)
            # is excluded from the coverage denominator per CLAUDE.md QA
            # requirement #2 -- logged, not counted as REJECTED.
            channel_errors.append({"channel": channel.name, "error": str(e)})
            continue

        bucket_key = result.channel
        cost_breakdown[bucket_key] = cost_breakdown.get(bucket_key, 0.0) + result.cost

        if result.tier == "PROSPECT":
            return {
                "account_name": ctx.account_name,
                "channel": result.channel,
                "tier": "PROSPECT",
                "evidence_photo_location": result.evidence.get("evidence_photo_location", ""),
                "evidence_description": result.evidence.get("evidence_description", ""),
                "yolo_confidence": result.evidence.get("yolo_confidence"),
                "vlm_confidence": result.evidence.get("vlm_confidence", ""),
                "source_url": result.evidence.get("source_url", ""),
                "space_type": result.evidence.get("space_type", ""),
                "tv_powered_on": result.evidence.get("tv_powered_on", False),
                "cost": sum(cost_breakdown.values()),
                "vertical": vertical_key,
                "additional_metadata": {
                    "cost_breakdown": cost_breakdown,
                    "channel_errors": channel_errors,
                    "details": result.details,
                },
            }

        rejections.append({"channel": channel.name, "reason": result.details.get("reason", "")})

    return {
        "account_name": ctx.account_name,
        "channel": "",
        "tier": "REJECTED",
        "evidence_photo_location": "",
        "evidence_description": "; ".join(f"{r['channel']}: {r['reason']}" for r in rejections),
        "yolo_confidence": None,
        "vlm_confidence": "",
        "source_url": "",
        "space_type": "",
        "tv_powered_on": False,
        "cost": sum(cost_breakdown.values()),
        "vertical": vertical_key,
        "additional_metadata": {
            "cost_breakdown": cost_breakdown,
            "channel_errors": channel_errors,
            "rejections": rejections,
        },
    }


def run_vertical_for_accounts(
    vertical_key: str,
    channel_rows: List[ChannelConfigRow],
    accounts: List[AccountContext],
    progress_every: int = 25,
) -> List[Dict[str, Any]]:
    """Batch convenience wrapper -- same shape unified_worker.py already
    expects to log per CLAUDE.md's "Track costs" workflow item. Builds
    the channel list ONCE (see build_channels()) and reuses it for every
    account, rather than rebuilding per account."""
    channels = build_channels(channel_rows)
    records = []
    start = time.time()
    for i, ctx in enumerate(accounts, start=1):
        records.append(run_vertical_for_account(vertical_key, channels, ctx))
        if progress_every and i % progress_every == 0:
            elapsed = time.time() - start
            print(f"[{vertical_key}] {i}/{len(accounts)} accounts, {elapsed:.0f}s elapsed", file=sys.stderr)
    return records
