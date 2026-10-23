"""
Test Serper Places API to see if it returns reviews
Check current API structure and what fields are available
"""

import requests
import json
import config

# Test with a known sports bar
test_query = "Twin Peaks Restaurant New York"

print("="*80)
print("TESTING SERPER PLACES API FOR REVIEWS")
print("="*80)
print(f"Query: {test_query}")
print()

# Try Serper Places endpoint
headers = {
    "X-API-KEY": config.SERPER_API_KEY,
    "Content-Type": "application/json"
}

payload = {
    "q": test_query,
    "gl": "us"
}

print("Calling Serper Places API...")
response = requests.post(
    "https://google.serper.dev/places",
    json=payload,
    headers=headers,
    timeout=10
)

if response.status_code == 200:
    data = response.json()

    print(f"✓ Response received")
    print()
    print("="*80)
    print("AVAILABLE FIELDS:")
    print("="*80)

    # Show top-level fields
    print(f"Top-level keys: {list(data.keys())}")
    print()

    # Check if places returned
    places = data.get('places', [])
    if places:
        print(f"Number of places returned: {len(places)}")
        print()
        print("="*80)
        print("FIRST PLACE DATA STRUCTURE:")
        print("="*80)

        first_place = places[0]
        print(json.dumps(first_place, indent=2))

        # Check specifically for reviews
        print()
        print("="*80)
        print("REVIEWS CHECK:")
        print("="*80)

        if 'reviews' in first_place:
            reviews = first_place['reviews']
            print(f"✓ Reviews field present: {len(reviews)} reviews")

            if reviews:
                print()
                print("Sample review:")
                print("-"*80)
                print(json.dumps(reviews[0], indent=2))
        else:
            print("❌ No 'reviews' field in place data")
            print()
            print("Available fields in place:")
            for key in first_place.keys():
                print(f"  - {key}")
    else:
        print("❌ No places returned")
        print()
        print("Full response:")
        print(json.dumps(data, indent=2))

else:
    print(f"❌ Error: HTTP {response.status_code}")
    print(response.text)

print()
print("="*80)
print("CONCLUSION:")
print("="*80)
print("If reviews field present: Use Serper Places API (ToS-compliant, no extra API needed)")
print("If reviews field absent: Need Google Places Details API (requires separate API key)")
