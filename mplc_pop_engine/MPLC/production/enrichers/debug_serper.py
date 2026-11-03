#!/usr/bin/env python3
"""Debug Serper API to see what videos it returns."""

import os
import requests

SERPER_API_KEY = os.getenv("SERPER_API_KEY")

property_name = "Avalon Walnut Creek"
city = "Walnut Creek"
state = "CA"

queries = [
    f'"{property_name}" {city} {state} apartment tour',
    f'"{property_name}" virtual tour amenities',
    f"{property_name} apartment amenities"
]

for query in queries:
    print(f"\n{'='*80}")
    print(f"Query: {query}")
    print('='*80)

    url = "https://google.serper.dev/videos"
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {"q": query, "num": 10}

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        continue

    data = response.json()
    videos = data.get("videos", [])

    print(f"Found {len(videos)} total videos")

    for i, video in enumerate(videos, 1):
        link = video.get("link", "")
        title = video.get("title", "")

        print(f"\n{i}. {title}")
        print(f"   URL: {link}")

        # Check YouTube filter
        is_youtube = "youtube.com/watch" in link or "youtu.be/" in link
        print(f"   Is YouTube: {is_youtube}")

        # Check keyword filter
        title_lower = title.lower()
        has_keywords = any(kw in title_lower for kw in ["tour", "virtual", "amenities", "apartment", "clubhouse"])
        print(f"   Has keywords: {has_keywords}")

        # Check property name
        property_core = "walnut creek"
        has_property = property_core in title_lower
        print(f"   Has '{property_core}': {has_property}")

        passes_all = is_youtube and has_keywords and has_property
        print(f"   ✓ PASSES all filters" if passes_all else f"   ✗ FAILS filters")
