#!/usr/bin/env python3
"""
Website Scrape Evidence Channel adapter — vertical-agnostic.

This is a thin adapter, NOT a reimplementation. The original design doc
(claude/Shared_Channel_Architecture_Design.md §3/§9) already found that
production/channels/website_image_channel.py's WebsiteImageEvidenceChannel
is vertical-agnostic and well-built -- it just predates base.py's
EvidenceChannel interface, so it takes (property_name, website_url,
temp_dir) positionally and returns a plain dict instead of taking an
AccountContext and returning a ChannelResult. Per the explicit decision in
Custom_Vertical_Builder_Design.md §1/§4, that proven 1148-line file is left
completely untouched -- this file only translates calling convention and
return shape so it can sit in a custom vertical's channel list alongside
SerperImageEvidenceChannel and YouTubeVideoEvidenceChannel.

Entity verification note: WebsiteImageEvidenceChannel scrapes the account's
OWN website (ctx.website), so a false-positive here is a different failure
mode than Serper/YouTube's "found someone else's TV" -- there is no
candidate "other entity" to confuse it with. The design doc's §9 MDU
website-URL-correctness fix (confirming the URL actually belongs to this
specific property before trusting a scrape, important for REIT-owned
multi-property portfolios) is a separate, not-yet-built concern tracked in
Custom_Vertical_Builder_Design.md §7 step 3 -- out of scope for this
adapter, which assumes ctx.website is already correct for ctx.account_name.
"""

import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Union

sys.path.insert(0, str(Path(__file__).parent))
from base import AccountContext, ChannelResult, EvidenceChannel  # noqa: E402
from website_image_channel import WebsiteImageEvidenceChannel  # noqa: E402


class WebsiteScrapeEvidenceChannel(EvidenceChannel):
    name = "website_scrape"

    def __init__(
        self,
        target_object_classes: List[str],
        gallery_page_keywords: List[str],
        vlm_classification_prompt: Union[str, Callable],
        anthropic_api_key: Optional[str] = None,
        yolo_model_path: Optional[Path] = None,
        exclude_image_keywords: Optional[List[str]] = None,
        min_yolo_confidence: float = 0.2,
    ):
        # All config here is handed straight through to the real,
        # untouched channel -- this class adds no detection logic of its
        # own, only the EvidenceChannel-shaped wrapper around it.
        self._inner = WebsiteImageEvidenceChannel(
            target_object_classes=target_object_classes,
            gallery_page_keywords=gallery_page_keywords,
            vlm_classification_prompt=vlm_classification_prompt,
            anthropic_api_key=anthropic_api_key,
            yolo_model_path=yolo_model_path,
            exclude_image_keywords=exclude_image_keywords,
            min_yolo_confidence=min_yolo_confidence,
        )

    def search_evidence(self, ctx: AccountContext) -> ChannelResult:
        if not ctx.website:
            return ChannelResult.rejected(self.name, "No website URL on account", cost=0.0)

        with tempfile.TemporaryDirectory() as tmp:
            raw = self._inner.search_evidence(
                property_name=ctx.account_name,
                website_url=ctx.website,
                temp_dir=Path(tmp),
            )

            if raw["tier"] != "PROSPECT" or raw["evidence"] is None:
                return ChannelResult.rejected(
                    self.name,
                    raw.get("rejection_reason") or "No TV evidence found on website",
                    cost=raw.get("cost", 0.0),
                )

            ev = raw["evidence"]  # ImageEvidence dataclass: url, file_path, hash,
            # yolo_class, yolo_confidence, vlm_result, source_method
            vlm_result = ev.vlm_result or {}
            return ChannelResult(
                tier="PROSPECT",
                channel=self.name,
                cost=raw.get("cost", 0.0),
                evidence={
                    "source_url": ev.url,
                    "evidence_photo_location": str(ev.file_path),
                    "evidence_description": vlm_result.get("reasoning", ""),
                    "space_type": vlm_result.get("tv_location") or vlm_result.get("space_type"),
                    "tv_powered_on": bool(vlm_result.get("tv_powered_on", True)),
                    "vlm_confidence": vlm_result.get("confidence", "low"),
                    "yolo_confidence": ev.yolo_confidence,
                },
                details={
                    "yolo_class": ev.yolo_class,
                    "source_method": ev.source_method,
                    "images_found": raw.get("images_found", 0),
                    "images_analyzed": raw.get("images_analyzed", 0),
                },
            )
