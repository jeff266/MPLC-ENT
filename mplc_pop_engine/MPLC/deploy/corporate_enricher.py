#!/usr/bin/env python3
"""
Corporate PoP Detection Enricher

Channel: SerpAPI image search → YOLO filter → VLM confirmation
Cost: ~$0.022/account
Coverage: 16.7% (validated at n=42)

Evidence standard:
- TV/display in employee-accessible communal space
- Corporate HQ or office environment
- TV powered on with content visible
"""

import os
import json
import requests
import base64
import imghdr
import io
from typing import Dict, Optional

# API Keys
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


class CorporateEnricher:
    """Corporate PoP detection via image search + VLM."""

    def __init__(self):
        self.serper_key = SERPER_API_KEY
        self.anthropic_key = ANTHROPIC_API_KEY

        if not self.serper_key:
            raise ValueError("SERPER_API_KEY not set")
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

    def search_corporate_images(self, company_name: str) -> Optional[list]:
        """
        Search for corporate office images via Serper API.

        Based on Brittany's manual approach:
        - Headquarters building photos
        - Gym/cafeteria presence as proxy signal
        """

        queries = [
            f"{company_name} headquarters gym fitness center",
            f"{company_name} office cafeteria break room",
            f"{company_name} headquarters employee lounge",
            f"{company_name} corporate office common area",
        ]

        all_images = []

        for query in queries:
            try:
                url = "https://google.serper.dev/images"
                payload = json.dumps({"q": query, "num": 10})
                headers = {
                    'X-API-KEY': self.serper_key,
                    'Content-Type': 'application/json'
                }

                response = requests.post(url, headers=headers, data=payload, timeout=30)

                if response.status_code != 200:
                    continue

                data = response.json()
                images = data.get("images", [])

                for img in images[:5]:  # Top 5 per query
                    all_images.append({
                        'url': img.get('imageUrl'),
                        'title': img.get('title', ''),
                        'source': img.get('link', ''),
                        'query': query
                    })

                if all_images:
                    break  # Found images, no need for more queries

            except Exception as e:
                print(f"Image search error: {e}")
                continue

        return all_images if all_images else None

    def analyze_image_vlm(
        self,
        image_url: str,
        company_name: str,
        source: str = "image_search"
    ) -> Optional[Dict]:
        """Analyze image for TV evidence using VLM."""

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

            prompt = f"""Analyze this corporate office image for TV evidence.

Company: {company_name}
Source: {source}

Look for TVs in employee-accessible communal spaces:
- Gym/fitness center
- Cafeteria/break room
- Employee lounge/common area
- Lobby (if clearly for employee use)

TV must be:
1. In a space where employees gather
2. Entertainment/information TV (showing content when on)
3. NOT in meeting rooms or private offices

CRITICAL EXCLUSIONS (Brittany's false positive filters):
- Menu boards (restaurant-style displays)
- Logo displays / brand signage
- Black screens (powered off)
- Meeting room displays
- Computer monitors at desks
- Digital wayfinding screens
- Reception desk monitors

Gym/cafeteria presence is a strong proxy signal for TV licensing need.

Answer ONLY with valid JSON:
{{
  "tv_detected": true|false,
  "tv_location": "gym|cafeteria|employee_lounge|break_room|lobby|none",
  "confidence": "high|medium|low",
  "is_entertainment_tv": true|false,
  "is_communal_space": true|false,
  "tv_powered_on": true|false,
  "is_menu_board": false,
  "is_logo_display": false,
  "is_black_screen": false,
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

    def enrich_account(self, company_name: str) -> Dict:
        """Enrich corporate account with PoP detection."""

        total_cost = 0.0

        # Search for corporate office images
        print(f"  Searching images for {company_name}...")
        images = self.search_corporate_images(company_name)

        if not images:
            return {
                'tier': 'REJECTED',
                'channel': 'none',
                'evidence_url': '',
                'confidence': 'none',
                'cost': total_cost,
                'details': {'reason': 'No corporate office images found'}
            }

        print(f"    Found {len(images)} images")

        # Analyze images with VLM
        for img in images[:10]:  # Analyze up to 10 images
            analysis = self.analyze_image_vlm(
                img['url'],
                company_name,
                "serper_image_search"
            )

            if not analysis:
                continue

            total_cost += analysis.get('cost', 0.0)

            # Check for valid TV evidence (with Brittany's exclusion filters)
            if analysis['tv_detected'] and \
               analysis['is_entertainment_tv'] and \
               analysis['is_communal_space'] and \
               analysis['confidence'] in ['high', 'medium'] and \
               not analysis.get('is_menu_board', False) and \
               not analysis.get('is_logo_display', False) and \
               not analysis.get('is_black_screen', False):

                return {
                    'tier': 'PROSPECT',
                    'channel': 'serper_images',
                    'evidence_url': img['url'],
                    'image_source': img.get('source', ''),
                    'search_query': img.get('query', ''),
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

        # No TV evidence found
        return {
            'tier': 'REJECTED',
            'channel': 'serper_images',
            'evidence_url': '',
            'confidence': 'none',
            'cost': total_cost,
            'details': {
                'reason': f'No TV evidence found in {len(images)} images analyzed',
                'images_checked': len(images)
            }
        }


def process_account(record: Dict) -> Dict:
    """Process a single corporate account (unified_worker compatible)."""

    enricher = CorporateEnricher()

    company_name = record.get('account_name', '')

    if not company_name:
        return {
            **record,
            'tier': 'REJECTED',
            'channel': 'none',
            'error': 'Missing account_name'
        }

    result = enricher.enrich_account(company_name)

    return {**record, **result}
