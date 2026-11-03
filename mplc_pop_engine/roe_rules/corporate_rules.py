"""
Corporate ROE segmentation rules.

ENT: 5,000+ global employees AND documented breakroom use case
No defined SB/MM bands in ROE doc.

KNOWN GAPS:
1. No breakroom_documented source exists → All 5k+ route to UNRESOLVED
2. Accounts with 3k-4,999 employees fall between general ENT (3k+)
   and corporate-specific ENT (5k+) → UNRESOLVED
3. Accounts < 3k have no defined corporate SB/MM bands → UNRESOLVED
"""

from typing import Tuple, List
from .base import ROERule, SegmentResult


class CorporateROERule(ROERule):
    """
    Corporate segmentation with ENT-only threshold.

    NOTE: breakroom_documented source does not exist yet.
    All corporate accounts will route to various UNRESOLVED categories.
    """

    @property
    def vertical_name(self) -> str:
        return "Corporations"

    def validate_data(self, account: dict) -> Tuple[bool, List[str]]:
        """Requires employee_count (global headcount)."""
        missing = []

        employee_count = account.get('employee_count') or account.get('Capacity')
        if employee_count is None or employee_count == '':
            missing.append('employee_count')

        if missing:
            return False, missing

        return True, []

    def _segment_impl(self, account: dict) -> SegmentResult:
        """Segment corporate account by employee count and breakroom status."""
        employee_count = account.get('employee_count') or account.get('Capacity')
        breakroom_documented = account.get('breakroom_documented', False)
        is_fortune_500 = account.get('is_fortune_500', False)

        # Convert employee count to int
        if isinstance(employee_count, str):
            try:
                employee_count = int(employee_count.replace(',', ''))
            except (ValueError, AttributeError):
                return SegmentResult(
                    segment='UNRESOLVED',
                    confidence='manual_review',
                    reason=f'Invalid employee_count: {employee_count!r}',
                    missing_data=[],
                    edge_case='INVALID_EMPLOYEE_COUNT_FORMAT'
                )

        # Fortune 500: Discretionary manual assignment
        if is_fortune_500:
            return SegmentResult(
                segment='FORTUNE500',
                confidence='manual_assignment',
                reason='Fortune 500 Tier 1 - discretionary assignment by performance',
                missing_data=[],
                edge_case='FORTUNE500_DISCRETIONARY'
            )

        # ENT: 5,000+ AND breakroom documented
        if employee_count >= 5000 and breakroom_documented:
            return SegmentResult(
                segment='ENT',
                confidence='high',
                reason=f'{employee_count:,} employees + documented breakroom → ENT',
                missing_data=[]
            )

        # UNRESOLVED: 3,000-4,999 (between general ENT and corporate ENT)
        if 3000 <= employee_count < 5000:
            return SegmentResult(
                segment='UNRESOLVED',
                confidence='manual_review',
                reason=f'{employee_count:,} employees falls between general ENT (3k+) and corporate-specific ENT (5k+)',
                missing_data=[],
                edge_case='CORPORATE_3K_TO_5K_GAP'
            )

        # UNRESOLVED: 5,000+ but no breakroom documentation
        if employee_count >= 5000:
            return SegmentResult(
                segment='UNRESOLVED',
                confidence='manual_review',
                reason=f'{employee_count:,} employees meets threshold but missing breakroom documentation',
                missing_data=['breakroom_documented'],
                edge_case='CORPORATE_ENT_MISSING_BREAKROOM'
            )

        # UNRESOLVED: < 3,000 (no defined SB/MM corporate bands)
        return SegmentResult(
            segment='UNRESOLVED',
            confidence='manual_review',
            reason=f'{employee_count:,} employees - no defined SB/MM corporate bands in ROE doc',
            missing_data=[],
            edge_case='NO_CORPORATE_SB_MM_BANDS'
        )
