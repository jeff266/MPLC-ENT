#!/usr/bin/env python3
"""
Standard CSV Schema Definition

Defines the canonical field names expected by the batch processor.
All input CSVs are translated to this schema before processing.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class StandardSchema:
    """Standard field names for batch processing."""

    # Required fields
    ACCOUNT_ID = 'account_id'
    ACCOUNT_NAME = 'account_name'

    # Location fields (for Yelp search)
    STREET = 'street'
    CITY = 'city'
    STATE = 'state'
    ZIP = 'zip'
    COUNTRY = 'country'

    # Segmentation fields
    SEGMENT = 'segment'  # MM/ENT
    INDUSTRY = 'industry'
    VERTICAL = 'vertical'  # corporate/healthcare/auto/etc

    # Contact fields
    PHONE = 'phone'
    WEBSITE = 'website'

    # Employee/capacity fields
    EMPLOYEE_COUNT = 'employee_count'
    CAPACITY = 'capacity'
    CAPACITY_TYPE = 'capacity_type'

    # Owner/status fields
    ACCOUNT_OWNER = 'account_owner'
    ACCOUNT_STATUS = 'account_status'
    OPERATING_MARKET = 'operating_market'


# Common field name variations (for translation)
FIELD_MAPPINGS = {
    # Account ID variations
    'account_id': ['account_id', '18 Digit Account ID', 'Account ID', 'salesforce_id'],

    # Account name variations
    'account_name': ['account_name', 'Account Name', 'name', 'business_name', 'company_name'],

    # Address variations
    'street': ['street', 'Account Street', 'account_street', 'address', 'street_address'],
    'city': ['city', 'Account City', 'account_city', 'Account State/Province (text only)'],
    'state': ['state', 'Account State/Province', 'Account State', 'account_state', 'province', 'region'],
    'zip': ['zip', 'Account Zip/Postal Code', 'account_zip', 'postal_code', 'zipcode', 'Account Zip/Postal Code'],
    'country': ['country', 'Account Country', 'account_country', 'Account Country (text only)'],

    # Segment/classification
    'segment': ['segment', 'Segment', 'roe_segment', 'classification'],
    'industry': ['industry', 'Industry', 'Account Sub Industry'],
    'vertical': ['vertical', 'Vertical', 'business_vertical'],

    # Contact
    'phone': ['phone', 'Phone', 'telephone', 'phone_number'],
    'website': ['website', 'Website', 'url', 'domain', 'Combined website', 'combined website'],

    # Employee count
    'employee_count': ['employee_count', 'Employee Count', 'employees', 'headcount', 'Employee Count (2)'],
    'capacity': ['capacity', 'Capacity', 'size'],
    'capacity_type': ['capacity_type', 'Capacity Type'],

    # Owner/status
    'account_owner': ['account_owner', 'Account Owner', 'owner', 'sales_rep'],
    'account_status': ['account_status', 'Account Status', 'status'],
    'operating_market': ['operating_market', 'Operating Market', 'market'],
}


def get_standard_fields() -> List[str]:
    """Get list of all standard field names."""
    return [
        StandardSchema.ACCOUNT_ID,
        StandardSchema.ACCOUNT_NAME,
        StandardSchema.STREET,
        StandardSchema.CITY,
        StandardSchema.STATE,
        StandardSchema.ZIP,
        StandardSchema.COUNTRY,
        StandardSchema.SEGMENT,
        StandardSchema.INDUSTRY,
        StandardSchema.VERTICAL,
        StandardSchema.PHONE,
        StandardSchema.WEBSITE,
        StandardSchema.EMPLOYEE_COUNT,
        StandardSchema.CAPACITY,
        StandardSchema.CAPACITY_TYPE,
        StandardSchema.ACCOUNT_OWNER,
        StandardSchema.ACCOUNT_STATUS,
        StandardSchema.OPERATING_MARKET,
    ]


def get_required_fields() -> List[str]:
    """Get list of required fields (minimum for processing)."""
    return [
        StandardSchema.ACCOUNT_ID,
        StandardSchema.ACCOUNT_NAME,
    ]


def get_recommended_fields() -> List[str]:
    """Get list of recommended fields for best results."""
    return [
        StandardSchema.ACCOUNT_ID,
        StandardSchema.ACCOUNT_NAME,
        StandardSchema.CITY,
        StandardSchema.STATE,
        StandardSchema.SEGMENT,
        StandardSchema.INDUSTRY,
    ]
