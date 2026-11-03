"""
General ROE segmentation rules (default fallback).

Used for verticals without specific rules defined.
Segments by US employee headcount only.
"""

from typing import Tuple, List
from .base import ROERule, SegmentResult


class GeneralROERule(ROERule):
    """
    General segmentation: SB 0-999, MM 1,000-2,999, ENT 3,000+

    Based on US employee headcount only.
    """

    @property
    def vertical_name(self) -> str:
        return "General"

    def validate_data(self, account: dict) -> Tuple[bool, List[str]]:
        """Requires employee_count field."""
        employee_count = account.get('employee_count') or account.get('Capacity')

        if employee_count is None or employee_count == '':
            return False, ['employee_count']

        return True, []

    def _segment_impl(self, account: dict) -> SegmentResult:
        """Segment by general thresholds."""
        employee_count = account.get('employee_count') or account.get('Capacity')

        # Convert to int if string
        if isinstance(employee_count, str):
            try:
                employee_count = int(employee_count.replace(',', ''))
            except (ValueError, AttributeError):
                return SegmentResult(
                    segment='UNRESOLVED',
                    confidence='manual_review',
                    reason=f'Invalid employee_count value: {employee_count!r}',
                    missing_data=[],
                    edge_case='INVALID_EMPLOYEE_COUNT_FORMAT'
                )

        # SB: 0-999
        if employee_count < 1000:
            return SegmentResult(
                segment='SB',
                confidence='high',
                reason=f'{employee_count:,} employees → SB (0-999)',
                missing_data=[]
            )

        # MM: 1,000-2,999
        elif employee_count < 3000:
            return SegmentResult(
                segment='MM',
                confidence='high',
                reason=f'{employee_count:,} employees → MM (1,000-2,999)',
                missing_data=[]
            )

        # ENT: 3,000+
        else:
            return SegmentResult(
                segment='ENT',
                confidence='high',
                reason=f'{employee_count:,} employees → ENT (3,000+)',
                missing_data=[]
            )
