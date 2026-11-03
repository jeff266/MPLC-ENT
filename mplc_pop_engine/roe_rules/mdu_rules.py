"""
MDU ROE segmentation rules.

Segments by location count (not employee count):
- SB: <= 10 locations
- MM: 5-25 locations (overlaps with SB at 5-10)
- ENT: 25+ locations

KNOWN GAP: Exactly 25 locations satisfies both MM (5-25) and ENT (25+).
"""

from typing import Tuple, List
from .base import ROERule, SegmentResult


class MDUROERule(ROERule):
    """
    MDU segmentation by location count.

    NOTE: 25 locations is an edge case - satisfies both MM and ENT.
    """

    @property
    def vertical_name(self) -> str:
        return "Multi-Dwelling Units"

    def validate_data(self, account: dict) -> Tuple[bool, List[str]]:
        """Requires location_count field."""
        missing = []

        location_count = account.get('location_count')
        if location_count is None or location_count == '':
            missing.append('location_count')

        if missing:
            return False, missing

        return True, []

    def _segment_impl(self, account: dict) -> SegmentResult:
        """Segment MDU account by location count."""
        location_count = account.get('location_count')

        # Convert to int if string
        if isinstance(location_count, str):
            try:
                location_count = int(location_count.replace(',', ''))
            except (ValueError, AttributeError):
                return SegmentResult(
                    segment='UNRESOLVED',
                    confidence='manual_review',
                    reason=f'Invalid location_count: {location_count!r}',
                    missing_data=[],
                    edge_case='INVALID_LOCATION_COUNT_FORMAT'
                )

        # SB: <= 10 locations
        if location_count <= 10:
            return SegmentResult(
                segment='SB',
                confidence='high',
                reason=f'{location_count} locations → SB (≤10)',
                missing_data=[]
            )

        # UNRESOLVED: Exactly 25 (satisfies both MM and ENT)
        elif location_count == 25:
            return SegmentResult(
                segment='UNRESOLVED',
                confidence='manual_review',
                reason='25 locations satisfies both MM (5-25) and ENT (25+) definitions',
                missing_data=[],
                edge_case='MDU_25_LOCATION_OVERLAP'
            )

        # MM: 11-24 locations (after handling 25 edge case)
        elif location_count < 25:
            return SegmentResult(
                segment='MM',
                confidence='high',
                reason=f'{location_count} locations → MM (5-25, excluding 25)',
                missing_data=[]
            )

        # ENT: 26+ locations
        else:
            return SegmentResult(
                segment='ENT',
                confidence='high',
                reason=f'{location_count} locations → ENT (25+)',
                missing_data=[]
            )
