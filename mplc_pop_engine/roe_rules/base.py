"""
Base class for ROE segmentation rules.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple, List


@dataclass
class SegmentResult:
    """Result of ROE segmentation for one account."""
    segment: str              # SB | MM | ENT | UNRESOLVED | GOV | FORTUNE500
    confidence: str           # high | medium | low | manual_review | manual_assignment
    reason: str               # Human-readable explanation
    missing_data: List[str]   # Fields needed but unavailable
    edge_case: Optional[str] = None  # Known gap description (if applicable)


class ROERule(ABC):
    """
    Base class for vertical-specific ROE segmentation rules.

    Subclasses MUST implement:
    - vertical_name: Property returning vertical name
    - validate_data: Check if account has required fields
    - segment: Classify account into SB/MM/ENT

    All implementations MUST return SegmentResult for ALL code paths.
    No None fallthrough allowed.
    """

    @property
    @abstractmethod
    def vertical_name(self) -> str:
        """Name of vertical this rule applies to."""
        pass

    @abstractmethod
    def validate_data(self, account: dict) -> Tuple[bool, List[str]]:
        """
        Check if account has required data for segmentation.

        Args:
            account: Account record dict

        Returns:
            (is_valid, missing_fields)
            - is_valid: True if all required fields present
            - missing_fields: List of missing field names
        """
        pass

    @abstractmethod
    def _segment_impl(self, account: dict) -> SegmentResult:
        """
        Internal segmentation logic - only called after validate_data passes.

        Subclasses implement this instead of segment() directly.
        """
        pass

    def segment(self, account: dict) -> SegmentResult:
        """
        Classify account into SB/MM/ENT segment.

        This method enforces validation before segmentation.
        Subclasses should implement _segment_impl instead.

        Args:
            account: Dict with vertical-specific fields

        Returns:
            SegmentResult with segment classification
        """
        # Validate data first
        is_valid, missing_fields = self.validate_data(account)

        if not is_valid:
            return SegmentResult(
                segment='UNRESOLVED',
                confidence='manual_review',
                reason=f'Missing required data for {self.vertical_name} segmentation',
                missing_data=missing_fields,
                edge_case='MISSING_REQUIRED_DATA'
            )

        # Call implementation
        return self._segment_impl(account)
