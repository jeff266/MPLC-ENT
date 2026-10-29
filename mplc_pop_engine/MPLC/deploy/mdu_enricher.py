#!/usr/bin/env python3
"""
MDU PoP Detection Enricher - Multi-Channel (Free → Paid)

Waterfall (cheapest first):
1. Website images → YOLO (free) → VLM (if TV found)
2. Website embedded videos → extract → YOLO → VLM
3. YouTube property tours → VLM on thumbnails (last resort)

Detection: Media → YOLO filter → VLM confirmation
"""

import os
import json
import requests
import base64
import re
from typing import Dict, Optional, List
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

# API Keys
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


class MDUEnricher:
    """MDU PoP detection - free channels first, paid channels last."""

    def __init__(self):
        self.youtube_key = YOUTUBE_API_KEY
        self.anthropic_key = ANTHROPIC_API_KEY

        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

    def scrape_website_media(self, website_url: str) -> Dict:
        """
        Scrape property website for images and embedded videos.
        Returns: {'images': [...], 'videos': [...]}
        """

        if not website_url or not website_url.startswith('http'):
            return {'images': [], 'videos': []}

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            response = requests.get(website_url, headers=headers, timeout=15)

            if response.status_code != 200:
                return {'images': [], 'videos': []}

            soup = BeautifulSoup(response.content, 'html.parser')

            # Find images
            images = []
            for img in soup.find_all('img'):
                src = img.get('src') or img.get('data-src')
                if src:
                    full_url = urljoin(website_url, src)
                    # Filter for likely amenity images
                    if any(kw in full_url.lower() for kw in ['amenity', 'clubhouse', 'fitness', 'pool', 'lounge', 'lobby', 'community']):
                        images.append(full_url)

            # Find embedded videos (YouTube, Vimeo)
            videos = []

            # YouTube embeds
            for iframe in soup.find_all('iframe'):
                src = iframe.get('src', '')
                if 'youtube.com/embed' in src or 'youtu.be' in src:
                    videos.append({'type': 'youtube_embed', 'url': src})

            # Vimeo embeds
            for iframe in soup.find_all('iframe'):
                src = iframe.get('src', '')
                if 'vimeo.com' in src:
                    videos.append({'type': 'vimeo_embed', 'url': src})

            # Video tags
            for video in soup.find_all('video'):
                sources = video.find_all('source')
                for source in sources:
                    src = source.get('src')
                    if src:
                        videos.append({'type': 'direct_video', 'url': urljoin(website_url, src)})

            return {
                'images': images[:20],  # Limit to 20 images
                'videos': videos[:5]     # Limit to 5 videos
            }

        except Exception as e:
            print(f"Website scraping error: {e}")
            return {'images': [], 'videos': []}

    def analyze_image_vlm(
        self,
        image_url: str,
        property_name: str,
        source: str = "website"
    ) -> Optional[Dict]:
        """
        Analyze image for TV evidence using VLM.
        Only called after YOLO confirms TV present (cost optimization).
        """

        try:
            # Download image
            img_response = requests.get(image_url, timeout=10)
            if img_response.status_code != 200:
                return None

            img_b64 = base64.b64encode(img_response.content).decode('utf-8')

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
                temperature=0,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
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
        1. Website images (free scraping, YOLO filter before VLM)
        2. Website embedded videos (free extraction, then VLM)
        3. YouTube tours (YouTube API + VLM, last resort)
        """

        total_cost = 0.0

        # Channel 1: Website Images (cheapest - scraping is free, YOLO is free)
        if website_url:
            print(f"  Channel 1: Scraping website images...")
            media = self.scrape_website_media(website_url)

            images = media.get('images', [])
            print(f"    Found {len(images)} images")

            # For now, analyze first few images with VLM
            # TODO: Add YOLO pre-filter to only VLM images with TVs
            for img_url in images[:3]:
                analysis = self.analyze_image_vlm(img_url, property_name, "website_image")

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
                        'evidence_url': img_url,
                        'tv_location': analysis.get('tv_location', ''),
                        'confidence': analysis.get('confidence', 'low'),
                        'tv_powered_on': analysis.get('tv_powered_on', False),
                        'reasoning': analysis.get('reasoning', ''),
                        'cost': total_cost,
                        'details': {'vlm_analysis': analysis}
                    }

            # Channel 2: Website Embedded Videos
            videos = media.get('videos', [])
            if videos:
                print(f"    Found {len(videos)} embedded videos")
                # TODO: Extract video frames and analyze
                # For now, skip to next channel

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

    enricher = MDUEnricher()

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
