"""
State Name Mapper - Normalizes state names to abbreviations

Fixes the mismatch between:
- Accounts CSV: "California", "New York", "Texas"
- Procurement DB: "CA", "NY", "TX"
"""

STATE_MAPPING = {
    # Full name -> Abbreviation
    'Alabama': 'AL',
    'Alaska': 'AK',
    'Arizona': 'AZ',
    'Arkansas': 'AR',
    'California': 'CA',
    'Colorado': 'CO',
    'Connecticut': 'CT',
    'Delaware': 'DE',
    'Florida': 'FL',
    'Georgia': 'GA',
    'Hawaii': 'HI',
    'Idaho': 'ID',
    'Illinois': 'IL',
    'Indiana': 'IN',
    'Iowa': 'IA',
    'Kansas': 'KS',
    'Kentucky': 'KY',
    'Louisiana': 'LA',
    'Maine': 'ME',
    'Maryland': 'MD',
    'Massachusetts': 'MA',
    'Michigan': 'MI',
    'Minnesota': 'MN',
    'Mississippi': 'MS',
    'Missouri': 'MO',
    'Montana': 'MT',
    'Nebraska': 'NE',
    'Nevada': 'NV',
    'New Hampshire': 'NH',
    'New Jersey': 'NJ',
    'New Mexico': 'NM',
    'New York': 'NY',
    'North Carolina': 'NC',
    'North Dakota': 'ND',
    'Ohio': 'OH',
    'Oklahoma': 'OK',
    'Oregon': 'OR',
    'Pennsylvania': 'PA',
    'Rhode Island': 'RI',
    'South Carolina': 'SC',
    'South Dakota': 'SD',
    'Tennessee': 'TN',
    'Texas': 'TX',
    'Utah': 'UT',
    'Vermont': 'VT',
    'Virginia': 'VA',
    'Washington': 'WA',
    'West Virginia': 'WV',
    'Wisconsin': 'WI',
    'Wyoming': 'WY',
}

# Reverse mapping (abbreviation -> full name)
ABBREV_TO_STATE = {abbrev: name for name, abbrev in STATE_MAPPING.items()}


def normalize_state_name(state_name: str) -> str:
    """
    Normalize state name to abbreviation.

    Args:
        state_name: State name (full or abbreviation)

    Returns:
        State abbreviation (e.g., "CA", "NY", "TX")

    Examples:
        >>> normalize_state_name("California")
        'CA'
        >>> normalize_state_name("CA")
        'CA'
        >>> normalize_state_name("New York")
        'NY'
    """
    if not state_name:
        return None

    state_clean = state_name.strip()

    # Already an abbreviation
    if state_clean in ABBREV_TO_STATE:
        return state_clean

    # Convert full name to abbreviation
    if state_clean in STATE_MAPPING:
        return STATE_MAPPING[state_clean]

    # Try case-insensitive match
    for full_name, abbrev in STATE_MAPPING.items():
        if full_name.lower() == state_clean.lower():
            return abbrev

    # Return as-is if no match (could be country, empty, etc.)
    return state_clean


def expand_state_abbrev(state_abbrev: str) -> str:
    """
    Expand state abbreviation to full name.

    Args:
        state_abbrev: State abbreviation (e.g., "CA")

    Returns:
        Full state name (e.g., "California")

    Examples:
        >>> expand_state_abbrev("CA")
        'California'
        >>> expand_state_abbrev("NY")
        'New York'
    """
    if not state_abbrev:
        return None

    state_clean = state_abbrev.strip().upper()
    return ABBREV_TO_STATE.get(state_clean, state_abbrev)


def is_valid_state(state_input: str) -> bool:
    """
    Check if state input is valid (either full name or abbreviation).

    Args:
        state_input: State name or abbreviation

    Returns:
        True if valid state, False otherwise
    """
    if not state_input:
        return False

    state_clean = state_input.strip()
    return (state_clean in STATE_MAPPING or
            state_clean in ABBREV_TO_STATE or
            state_clean.lower() in [s.lower() for s in STATE_MAPPING.keys()])


if __name__ == '__main__':
    # Test the mapper
    test_cases = [
        "California",
        "CA",
        "New York",
        "NY",
        "texas",
        "TX",
        "Florida",
        "",
        None,
    ]

    print("State Name Mapper Tests")
    print("=" * 50)
    for test in test_cases:
        normalized = normalize_state_name(test)
        print(f"{str(test):20s} -> {normalized}")
