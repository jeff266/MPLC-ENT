"""
Healthcare ROE segmentation rules.

Outpatient-only: Use general bands (SB 0-999, MM 1k-2,999, ENT 3k+)
Any inpatient: NEVER SB (MM 0-2,999, ENT 3k+)

KNOWN GAP: No facility_type source exists.
All healthcare accounts route to UNRESOLVED until source added.
"""

from typing import Tuple, List
from .base import ROERule, SegmentResult


class HealthcareROERule(ROERule):
    """
    Healthcare segmentation with inpatient/outpatient distinction.

    NOTE: facility_type source does not exist yet.
    All accounts will route to UNRESOLVED / NO_FACILITY_TYPE_SOURCE.
    """

    @property
    def vertical_name(self) -> str:
        return "Health Care Services"

    def validate_data(self, account: dict) -> Tuple[bool, List[str]]:
        """Requires employee_count and facility_type."""
        missing = []

        employee_count = account.get('employee_count') or account.get('Capacity')
        if employee_count is None or employee_count == '':
            missing.append('employee_count')

        facility_type = account.get('facility_type')
        if not facility_type:
            missing.append('facility_type')

        if missing:
            return False, missing

        return True, []

    def _segment_impl(self, account: dict) -> SegmentResult:
        """
        Segment healthcare account by facility type and employee count.

        NOTE: This implementation will not run until facility_type source exists.
        validate_data() will fail first, routing to UNRESOLVED.
        """
        facility_type = account.get('facility_type', '').lower()
        employee_count = account.get('employee_count') or account.get('Capacity')

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

        # Outpatient-only: Use general bands
        if facility_type == 'outpatient':
            if employee_count < 1000:
                return SegmentResult(
                    segment='SB',
                    confidence='high',
                    reason=f'Outpatient, {employee_count:,} employees → SB',
                    missing_data=[]
                )
            elif employee_count < 3000:
                return SegmentResult(
                    segment='MM',
                    confidence='high',
                    reason=f'Outpatient, {employee_count:,} employees → MM',
                    missing_data=[]
                )
            else:
                return SegmentResult(
                    segment='ENT',
                    confidence='high',
                    reason=f'Outpatient, {employee_count:,} employees → ENT',
                    missing_data=[]
                )

        # Any inpatient component: NEVER SB
        elif 'inpatient' in facility_type:
            if employee_count < 3000:
                return SegmentResult(
                    segment='MM',
                    confidence='high',
                    reason=f'Inpatient, {employee_count:,} employees → MM (never SB for inpatient)',
                    missing_data=[]
                )
            else:
                return SegmentResult(
                    segment='ENT',
                    confidence='high',
                    reason=f'Inpatient, {employee_count:,} employees → ENT',
                    missing_data=[]
                )

        # Unrecognized facility_type value
        else:
            return SegmentResult(
                segment='UNRESOLVED',
                confidence='manual_review',
                reason=f'Unrecognized facility_type value: {facility_type!r}',
                missing_data=[],
                edge_case='UNKNOWN_FACILITY_TYPE_VALUE'
            )
