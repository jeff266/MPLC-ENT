#!/usr/bin/env python3
"""
YouTube Building Tour Video Search for MDU PoP Detection

Searches YouTube for apartment community tour videos and extracts them
for PoP detection analysis.

Input: Community name + city/state
Output: YouTube video URLs with tour videos showing common areas
"""

import re
import csv
import json
import time
import logging
import requests
from typing import List, Dict, Optional
from urllib.parse import quote_plus

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


class YouTubeTourSearcher:
    """Search YouTube for apartment building tour videos."""

    def __init__(self, serper_api_key: str):
        self.serper_api_key = serper_api_key

    def search_tour_videos(self, community_name: str, city: str = None, state: str = None) -> List[Dict]:
        """
        Search for building tour videos on YouTube.

        Args:
            community_name: e.g., "Avalon Walnut Creek"
            city: "Walnut Creek"
            state: "California"

        Returns:
            List of video results with URLs and metadata
        """
        # Build search queries - try multiple patterns
        queries = self._build_queries(community_name, city, state)

        all_videos = []
        for query in queries:
            videos = self._search_youtube(query)
            all_videos.extend(videos)

            # Stop if we found good results
            if len(all_videos) >= 3:
                break

            time.sleep(0.5)

        # Deduplicate by video ID
        seen_ids = set()
        unique_videos = []
        for video in all_videos:
            video_id = video.get('video_id')
            if video_id and video_id not in seen_ids:
                seen_ids.add(video_id)
                unique_videos.append(video)

        return unique_videos

    def _build_queries(self, community_name: str, city: str = None, state: str = None) -> List[str]:
        """Build search query variations."""
        queries = []

        # Primary: Community name + "apartment tour"
        queries.append(f'"{community_name}" apartment tour')

        # Add location if available
        if city:
            queries.append(f'"{community_name}" {city} tour')

        # Add "virtual tour" variant
        queries.append(f'"{community_name}" virtual tour')

        # Try without quotes (broader search)
        queries.append(f'{community_name} apartments video tour')

        return queries[:2]  # Limit to top 2 queries

    def _search_youtube(self, query: str) -> List[Dict]:
        """Execute YouTube search via Serper."""
        log.debug(f"  Searching: {query}")

        try:
            response = requests.post(
                'https://google.serper.dev/videos',
                headers={
                    'X-API-KEY': self.serper_api_key,
                    'Content-Type': 'application/json'
                },
                json={
                    'q': query,
                    'gl': 'us',
                    'num': 10
                },
                timeout=30
            )

            response.raise_for_status()
            data = response.json()

            videos = []

            if 'videos' in data:
                for video in data['videos'][:5]:  # Top 5 results
                    # Extract video ID from link
                    link = video.get('link', '')
                    video_id = self._extract_video_id(link)

                    if not video_id:
                        continue

                    # Filter for likely tour videos
                    title = video.get('title', '').lower()
                    if not self._is_tour_video(title):
                        continue

                    videos.append({
                        'video_id': video_id,
                        'video_url': f"https://www.youtube.com/watch?v={video_id}",
                        'title': video.get('title'),
                        'channel': video.get('channel'),
                        'duration': video.get('duration'),
                        'published': video.get('date'),
                        'thumbnail': video.get('imageUrl'),
                        'query': query,
                    })

            return videos

        except Exception as e:
            log.error(f"  Serper error: {e}")
            return []

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract YouTube video ID from URL."""
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return None

    def _is_tour_video(self, title: str) -> bool:
        """Check if video title suggests it's a building tour."""
        tour_keywords = [
            'tour', 'walk through', 'walkthrough', 'virtual tour',
            'video tour', 'apartment tour', 'community tour',
            'model', 'inside', 'interior'
        ]

        # Must have at least one tour keyword
        has_tour_keyword = any(keyword in title for keyword in tour_keywords)

        # Exclude non-tour videos
        exclude_keywords = [
            'review only', 'exterior only', 'drone',
            'neighborhood tour', 'area tour', 'city tour'
        ]

        has_exclude = any(keyword in title for keyword in exclude_keywords)

        return has_tour_keyword and not has_exclude


def process_reit_properties(input_csv: str, output_csv: str, serper_api_key: str):
    """Process REIT properties and find YouTube tour videos."""

    # Read properties
    with open(input_csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        properties = list(reader)

    log.info(f"Loaded {len(properties)} properties from {input_csv}")

    searcher = YouTubeTourSearcher(serper_api_key)

    results = []
    cost = 0.0
    videos_found = 0

    for i, prop in enumerate(properties, 1):
        community_name = prop['community_name']
        city = prop.get('city')
        state = prop.get('state')

        log.info(f"[{i}/{len(properties)}] Searching: {community_name}")

        # Search for videos
        videos = searcher.search_tour_videos(community_name, city, state)

        if videos:
            log.info(f"  Found {len(videos)} tour videos")
            videos_found += len(videos)

            # Add each video as a separate row
            for video in videos:
                results.append({
                    'reit': prop['reit'],
                    'community_name': community_name,
                    'city': city,
                    'state': state,
                    'property_url': prop.get('property_url'),
                    'video_url': video['video_url'],
                    'video_title': video['title'],
                    'video_channel': video['channel'],
                    'video_duration': video['duration'],
                })

        else:
            log.info(f"  No tour videos found")
            # Still add property without video
            results.append({
                'reit': prop['reit'],
                'community_name': community_name,
                'city': city,
                'state': state,
                'property_url': prop.get('property_url'),
                'video_url': None,
                'video_title': None,
                'video_channel': None,
                'video_duration': None,
            })

        # Cost: 2 queries per property (video search) × $0.001
        cost += 0.002

        # Rate limiting
        time.sleep(0.5)

        # Progress checkpoint
        if i % 20 == 0:
            log.info(f"  Progress: {i}/{len(properties)} ({i/len(properties)*100:.1f}%)")
            log.info(f"  Videos found: {videos_found}")
            log.info(f"  Cost so far: ${cost:.3f}")

    # Summary
    properties_with_videos = len([r for r in results if r['video_url']])

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Properties processed: {len(properties)}")
    print(f"Properties with videos: {properties_with_videos} ({properties_with_videos/len(properties)*100:.1f}%)")
    print(f"Total videos found: {videos_found}")
    print(f"Total cost: ${cost:.3f}")

    # Write CSV
    fieldnames = [
        'reit', 'community_name', 'city', 'state', 'property_url',
        'video_url', 'video_title', 'video_channel', 'video_duration'
    ]

    with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nWrote to: {output_csv}")
    print("Ready for video PoP detection!")

    return results


def main():
    import os
    import argparse

    parser = argparse.ArgumentParser(description='Search YouTube for apartment tour videos')
    parser.add_argument('--input', default='all_reit_properties.csv', help='Input CSV with properties')
    parser.add_argument('--output', default='reit_properties_with_videos.csv', help='Output CSV')
    parser.add_argument('--limit', type=int, help='Limit number of properties to process')

    args = parser.parse_args()

    serper_api_key = os.getenv('SERPER_API_KEY')
    if not serper_api_key:
        print("ERROR: SERPER_API_KEY not set")
        exit(1)

    # Optional: limit for testing
    if args.limit:
        with open(args.input, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            properties = list(reader)[:args.limit]

        temp_input = 'temp_limited.csv'
        with open(temp_input, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
            writer.writeheader()
            writer.writerows(properties)

        process_reit_properties(temp_input, args.output, serper_api_key)
    else:
        process_reit_properties(args.input, args.output, serper_api_key)


if __name__ == '__main__':
    main()
