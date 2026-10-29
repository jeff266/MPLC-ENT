#!/usr/bin/env python3
"""
Corporate PoP Detection Enricher - FIXED

Improvements:
- Better error logging
- Image validation before VLM
- Track failed vs successful analysis
- More detailed error messages
- Skip broken image URLs
"""

import os
import json
import requests
import base64
import imghdr
import io
import time
from typing import Dict, Optional
from PIL import Image

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
        """Search for corporate office images via Serper API."""

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
                    print(f"  Serper API error: {response.status_code}")
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
                print(f"  Image search error: {e}")
                continue

        return all_images if all_images else None

    def validate_image(self, image_url: str, timeout: int = 10) -> Optional[bytes]:
        """
        Download and validate image before sending to VLM.
        Returns image bytes if valid, None if invalid.
        """
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(image_url, headers=headers, timeout=timeout, stream=True)

            if response.status_code != 200:
                print(f"    Image download failed: HTTP {response.status_code}")
                return None

            # Get content
            content = response.content

            # Check size (skip if too small or too large)
            size_kb = len(content) / 1024
            if size_kb < 5:  # Skip tiny images (< 5KB)
                print(f"    Image too small: {size_kb:.1f}KB")
                return None
            if size_kb > 5000:  # Skip huge images (> 5MB)
                print(f"    Image too large: {size_kb:.1f}KB")
                return None

            # Validate it's actually an image
            img_format = imghdr.what(None, h=content)
            if not img_format:
                print(f"    Not a valid image format")
                return None

            # Try to open with PIL to verify it's not corrupted
            try:
                img = Image.open(io.BytesIO(content))
                img.verify()
            except Exception as e:
                print(f"    Corrupted image: {e}")
                return None

            return content

        except requests.Timeout:
            print(f"    Image download timeout")
            return None
        except Exception as e:
            print(f"    Image validation error: {str(e)[:50]}")
            return None

    def analyze_image_vlm(
        self,
        image_content: bytes,
        company_name: str,
        source: str = "image_search"
    ) -> Optional[Dict]:
        """Analyze validated image for TV evidence using VLM."""

        try:
            img_b64 = base64.b64encode(image_content).decode('utf-8')

            # Detect format
            img_format = imghdr.what(None, h=image_content)
            if img_format == 'png':
                media_type = "image/png"
            elif img_format == 'gif':
                media_type = "image/gif"
            elif img_format in ['jpeg', 'jpg']:
                media_type = "image/jpeg"
            elif img_format == 'webp':
                media_type = "image/webp"
            else:
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

CRITICAL EXCLUSIONS:
- Menu boards (restaurant-style displays)
- Logo displays / brand signage
- Black screens (powered off)
- Meeting room displays
- Computer monitors at desks
- Digital wayfinding screens
- Reception desk monitors

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

            # Parse response
            text_content = next(
                (block.text for block in response.content if hasattr(block, 'text')),
                None
            )

            if not text_content:
                print(f"    VLM: No text response")
                return None

            # Extract JSON
            json_start = text_content.find('{')
            json_end = text_content.rfind('}') + 1

            if json_start == -1 or json_end == 0:
                print(f"    VLM: No JSON in response")
                return None

            result = json.loads(text_content[json_start:json_end])

            # Calculate cost
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost = (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0)

            result['cost'] = cost
            return result

        except Exception as e:
            error_str = str(e)
            if "400" in error_str or "invalid_request_error" in error_str:
                print(f"    VLM: Image processing error (400)")
                print(f"    Full error: {error_str[:200]}")
            elif "overloaded" in error_str.lower():
                print(f"    VLM: API overloaded, retrying...")
                time.sleep(2)
                return None  # Could retry here
            else:
                print(f"    VLM error: {error_str[:200]}")
            return None

    def enrich_account(self, company_name: str) -> Dict:
        """
        Enrich corporate account with PoP detection.
        Returns dict with tier, channel, evidence_url, cost, etc.
        """

        total_cost = 0.0

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

        # Track analysis results
        images_analyzed = 0
        images_failed = 0

        # Analyze images with VLM
        for i, img in enumerate(images[:10], 1):  # Analyze up to 10 images
            print(f"    Analyzing image {i}/{min(len(images), 10)}...", end=" ")

            # Step 1: Validate image
            image_content = self.validate_image(img['url'])
            if not image_content:
                images_failed += 1
                continue

            print("valid,", end=" ")

            # Step 2: VLM analysis
            analysis = self.analyze_image_vlm(
                image_content,
                company_name,
                "serper_image_search"
            )

            if not analysis:
                images_failed += 1
                print("analysis failed")
                continue

            images_analyzed += 1
            total_cost += analysis.get('cost', 0.0)

            # Check for valid TV evidence
            if analysis['tv_detected'] and \
               analysis['is_entertainment_tv'] and \
               analysis['is_communal_space'] and \
               analysis['confidence'] in ['high', 'medium'] and \
               not analysis.get('is_menu_board', False) and \
               not analysis.get('is_logo_display', False) and \
               not analysis.get('is_black_screen', False):

                print(f"PROSPECT!")
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
                        'vlm_analysis': analysis,
                        'images_analyzed': images_analyzed,
                        'images_failed': images_failed
                    }
                }
            else:
                print("no TV")

        # No TV evidence found
        return {
            'tier': 'REJECTED',
            'channel': 'serper_images',
            'evidence_url': '',
            'confidence': 'none',
            'cost': total_cost,
            'details': {
                'reason': f'No TV evidence found',
                'images_found': len(images),
                'images_analyzed': images_analyzed,
                'images_failed': images_failed
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
