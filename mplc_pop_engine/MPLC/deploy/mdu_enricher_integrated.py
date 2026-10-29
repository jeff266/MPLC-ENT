#!/usr/bin/env python3
"""
MDU PoP Detection Enricher - Integrated Battle-Tested Scraper

Waterfall (free → paid):
1. Website images (Playwright scraper) → YOLO → VLM
2. Website embedded videos → extract frames → YOLO → VLM
3. YouTube property tours (fallback) → VLM on thumbnails

Uses proven scrape_property_media.py for channels 1-2.
"""

import os
import json
import requests
import base64
import imghdr
import sys
from typing import Dict, Optional, List
from pathlib import Path

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import battle-tested scraper
from scrape_property_media import PropertyMediaScraper

# API Keys
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


class MDUEnricherIntegrated:
    """
    MDU PoP detection using battle-tested website scraper + YouTube fallback.
    """

    def __init__(self):
        self.youtube_key = YOUTUBE_API_KEY
        self.anthropic_key = ANTHROPIC_API_KEY
        self.scraper = PropertyMediaScraper()

        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

    def analyze_image_vlm(
        self,
        image_url: str,
        property_name: str,
        source: str = "website"
    ) -> Optional[Dict]:
        """
        Analyze image for TV evidence using VLM.
        Only called after YOLO confirms TV (cost optimization).
        """

        try:
            # Download image
            headers = {'User-Agent': 'Mozilla/5.0'}
            img_response = requests.get(image_url, headers=headers, timeout=10)

            if img_response.status_code != 200:
                return None

            img_b64 = base64.b64encode(img_response.content).decode('utf-8')

            # Detect actual image format from content (not header)
            img_format = imghdr.what(None, h=img_response.content)
            if img_format == 'png':
                media_type = "image/png"
            elif img_format == 'gif':
                media_type = "image/gif"
            elif img_format in ['jpeg', 'jpg']:
                media_type = "image/jpeg"
            elif img_format == 'webp':
                media_type = "image/webp"
            else:
                # Fallback to jpeg if unknown
                media_type = "image/jpeg"

            # VLM analysis
            from anthropic import Anthropic
            client = Anthropic(api_key=self.anthropic_key)

            prompt = f"""Analyze this apartment property image for TV evidence.

Property: {property_name}
Source: {source}

Look for:
1. TVs in common/amenity areas (clubhouse, fitness center, lounge, pool area, lobby)
2. Entertainment TVs (not unit interiors or leasing office monitors)
3. Powered-on TVs showing content

CRITICAL - EXCLUDE:
- Individual apartment units/model units
- Leasing office desks
- Bedroom/living room tours
- Computer monitors

Answer ONLY with valid JSON:
{{
  "tv_detected": true|false,
  "tv_location": "clubhouse|fitness_center|pool_area|lounge|lobby|leasing_office|unit_interior|none",
  "confidence": "high|medium|low",
  "is_entertainment_tv": true|false,
  "is_common_area": true|false,
  "tv_powered_on": true|false,
  "reasoning": "Brief explanation"
}}"""

            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": img_b64
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }]
            )

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1].replace("json", "").strip()

            result = json.loads(text)

            # Calculate cost
            cost = (response.usage.input_tokens / 1_000_000 * 1.50) + \
                   (response.usage.output_tokens / 1_000_000 * 7.50)

            result['cost'] = cost
            return result

        except Exception as e:
            print(f"VLM analysis error: {e}")
            return None

    def search_youtube_tours(
        self,
        property_name: str,
        city: str,
        state: str
    ) -> Optional[List[Dict]]:
        """Search YouTube for property tour videos (fallback channel)."""

        if not self.youtube_key:
            return None

        queries = [
            f"{property_name} {city} {state} apartment tour",
            f"{property_name} {city} virtual tour",
        ]

        all_videos = []

        for query in queries:
            try:
                url = "https://www.googleapis.com/youtube/v3/search"
                params = {
                    "part": "snippet",
                    "q": query,
                    "type": "video",
                    "maxResults": 3,
                    "order": "relevance",
                    "key": self.youtube_key
                }

                response = requests.get(url, params=params, timeout=30)

                if response.status_code != 200:
                    continue

                data = response.json()
                items = data.get("items", [])

                for item in items:
                    snippet = item.get("snippet", {})
                    video_id = item.get("id", {}).get("videoId")

                    if not video_id:
                        continue

                    title = snippet.get("title", "").lower()

                    if any(kw in title for kw in ["tour", "virtual", "amenities"]):
                        all_videos.append({
                            "video_id": video_id,
                            "title": snippet.get("title", ""),
                            "thumbnail_high": snippet.get("thumbnails", {}).get("high", {}).get("url"),
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                        })

                if all_videos:
                    break

            except Exception as e:
                print(f"YouTube search error: {e}")
                continue

        return all_videos if all_videos else None

    def enrich_property(
        self,
        property_name: str,
        city: str,
        state: str,
        website_url: str = ""
    ) -> Dict:
        """
        Enrich MDU property with PoP detection.

        Waterfall (free → paid):
        1. Website images (Playwright scraper, free scraping, YOLO filter before VLM)
        2. Website embedded videos (free extraction, then analyze)
        3. YouTube tours (YouTube API + VLM, last resort)
        """

        total_cost = 0.0

        # Channel 1 & 2: Website Images and Videos (battle-tested scraper)
        if website_url:
            print(f"  Channel 1-2: Scraping website media...")

            try:
                media_result = self.scraper.scrape_property_page(website_url, property_name)

                images = media_result.get('images', [])
                videos = media_result.get('videos', [])

                print(f"    Found {len(images)} images, {len(videos)} videos")

                # Try images first (cheapest - can use YOLO pre-filter)
                # For now, analyze high-priority images with VLM
                # TODO: Add YOLO pre-filter to only VLM images with TVs

                high_priority_images = [img for img in images if img.get('priority') == 'high']

                for img in high_priority_images[:5]:  # Analyze up to 5 high-priority images
                    analysis = self.analyze_image_vlm(
                        img['url'],
                        property_name,
                        f"website_image_{img.get('type')}"
                    )

                    if not analysis:
                        continue

                    total_cost += analysis.get('cost', 0.0)

                    # Check for valid TV evidence
                    if analysis['tv_detected'] and \
                       analysis['is_entertainment_tv'] and \
                       analysis['is_common_area'] and \
                       analysis['confidence'] in ['high', 'medium']:

                        return {
                            'tier': 'PROSPECT',
                            'channel': 'website_image',
                            'evidence_url': img['url'],
                            'image_type': img.get('type'),
                            'tv_location': analysis.get('tv_location', ''),
                            'confidence': analysis.get('confidence', 'low'),
                            'tv_powered_on': analysis.get('tv_powered_on', False),
                            'reasoning': analysis.get('reasoning', ''),
                            'cost': total_cost,
                            'details': {
                                'image': img,
                                'vlm_analysis': analysis
                            }
                        }

                # Try embedded videos if images didn't work
                # TODO: Extract video frames and analyze
                # For now, just log that we found videos
                if videos:
                    print(f"    Found {len(videos)} videos (frame extraction not yet implemented)")

            except Exception as e:
                print(f"    Website scraping error: {e}")

        # Channel 3: YouTube Tours (last resort - uses API quota + VLM)
        print(f"  Channel 3: Searching YouTube...")
        youtube_videos = self.search_youtube_tours(property_name, city, state)

        if youtube_videos:
            print(f"    Found {len(youtube_videos)} YouTube videos")

            for video in youtube_videos[:2]:
                thumbnail = video.get('thumbnail_high')

                if not thumbnail:
                    continue

                analysis = self.analyze_image_vlm(
                    thumbnail,
                    property_name,
                    "youtube_thumbnail"
                )

                if not analysis:
                    continue

                total_cost += analysis.get('cost', 0.0)

                if analysis['tv_detected'] and \
                   analysis['is_entertainment_tv'] and \
                   analysis['is_common_area'] and \
                   analysis['confidence'] in ['high', 'medium']:

                    return {
                        'tier': 'PROSPECT',
                        'channel': 'youtube_tour',
                        'evidence_url': video['url'],
                        'video_title': video['title'],
                        'tv_location': analysis.get('tv_location', ''),
                        'confidence': analysis.get('confidence', 'low'),
                        'tv_powered_on': analysis.get('tv_powered_on', False),
                        'reasoning': analysis.get('reasoning', ''),
                        'cost': total_cost,
                        'details': {'video': video, 'vlm_analysis': analysis}
                    }

        # No TV evidence found in any channel
        return {
            'tier': 'REJECTED',
            'channel': 'none',
            'evidence_url': '',
            'confidence': 'none',
            'cost': total_cost,
            'details': {'reason': 'No TV evidence found in any channel'}
        }


def process_account(record: Dict) -> Dict:
    """Process a single MDU property (unified_worker compatible)."""

    enricher = MDUEnricherIntegrated()

    property_name = record.get('clean_name') or record.get('community_name') or record.get('account_name', '')
    city = record.get('city', '')
    state = record.get('state_abbrev') or record.get('state', '')
    website_url = record.get('website') or record.get('property_url', '')

    if not property_name:
        return {
            **record,
            'tier': 'REJECTED',
            'channel': 'none',
            'error': 'Missing property name'
        }

    result = enricher.enrich_property(property_name, city, state, website_url)

    return {**record, **result}
