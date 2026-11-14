"""
Shared evidence-channel interface.

Migration step 1 of the Shared Channel Architecture design
(see claude/Shared_Channel_Architecture_Design.md in the MPLC project).
This file is pure interface — no behavior change to any existing enricher.
Nothing imports or uses this yet; it's the foundation the channel
extractions (video, image-search, procurement, federal-contracts,
Google Places) will be built against.

Every EvidenceChannel.search_evidence() implementation MUST call the
shared production/workers/entity_verification.py module before returning
a PROSPECT/SUSPECT result -- entity matching is not a per-channel config
option (see design doc §8). This module does not import that one (to
avoid a channels <-> workers circular dependency); each concrete channel
imports it directly, the same way healthcare_unified.py already does.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AccountContext:
    """Everything a channel needs to know about the account it's searching
    for evidence about. One instance built per account per vertical run;
    never mutated by a channel -- channels read it and return a
    ChannelResult, they don't write back into the context."""

    account_name: str
    city: str = ""
    state: str = ""
    country: str = "United States"
    operating_market: str = "United States"
    website: str = ""
    segment: str = ""
    industry: Optional[str] = None   # feeds entity_verification's category-incompatibility layer
    vertical: str = ""               # "healthcare" | "corporate" | "mdu" | ...
    # Vertical-specific fields a channel's config may read (e.g. facility_type
    # for healthcare's pediatric/senior-living split). Channels built for one
    # vertical should document which extra keys they expect; this is
    # intentionally untyped so adding a new vertical never requires editing
    # this shared dataclass.
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelResult:
    """What every channel returns, regardless of what kind of evidence it
    looks for. `evidence` holds the channel-specific payload (an
    ImageEvidence, a VideoEvidence, a ContractEvidence, ...) -- this base
    module doesn't define those, each channel module defines its own and
    this field just carries it through to the caller untyped."""

    tier: str                        # "PROSPECT" | "SUSPECT" | "REJECTED"
    channel: str                     # channel name for the evidence_persistence schema's `channel` field
    evidence: Optional[Any] = None
    cost: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def rejected(cls, channel: str, reason: str, cost: float = 0.0) -> "ChannelResult":
        """Convenience for the common case: no evidence found, or entity
        verification failed. Keeps the rejection reason in `details` so
        it survives into the evidence-persistence record for later
        debugging (per CLAUDE.md's QA requirement to exclude errors from
        the denominator, not just log a silent REJECTED)."""
        return cls(tier="REJECTED", channel=channel, cost=cost, details={"reason": reason})


class EvidenceChannel(ABC):
    """One evidence-gathering mechanism (video, image search, a database
    lookup, ...), vertical-agnostic. A vertical's "recipe" (see design doc
    §4) is an ordered list of these, each constructed with that vertical's
    own query templates / VLM prompt / space vocabulary as config -- never
    a per-vertical subclass. Subclassing per vertical is how the three
    enrichers ended up with duplicated implementations in the first place."""

    name: str  # e.g. "youtube_video_yolo", "state_procurement", "google_places_photos"

    @abstractmethod
    def search_evidence(self, ctx: AccountContext) -> ChannelResult:
        """Look for evidence for this one account. Must not raise for an
        ordinary "nothing found" case -- return ChannelResult.rejected(...)
        instead. Letting a real exception propagate is fine (and
        expected) for a genuine bug; the caller's channel-list loop is
        responsible for catching, logging, and excluding failed calls from
        the coverage denominator (CLAUDE.md QA requirement #2), not this
        method."""
        raise NotImplementedError
