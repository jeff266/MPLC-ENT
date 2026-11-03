#!/usr/bin/env python3
"""
Corporate PoP Detection - Unified Multi-Channel Pipeline

Architecture: Waterfall with early exit (like Healthcare)
- Channel 1: Image Search + Multi-Layer Validation
- Channel 2: YouTube Video + YOLO + VLM

Each channel tries to find evidence. First success returns PROSPECT.
This eliminates the single-channel limitation and increases recall.

Multi-Layer Validation (prevents false positives):
- Layer 1: Static Rules (stock photos, CDNs) - FREE
- Layer 2: Salesforce Official Website Match - FREE
- Layer 3: Trusted News + Sonnet Verification - $0.0011/image
- Layer 4: Sonnet Domain Validation - $0.0011/image

Expected: 15-30% PROSPECT rate with near-zero false positives
Cost: ~$0.015-0.025 per account
"""

import os
import json
import requests
import base64
import imghdr
import io
import time
import tempfile
import cv2
from pathlib import Path
from typing import Dict, Optional, List
from urllib.parse import urlparse
from PIL import Image
import re

# API Keys
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")


class CorporateEnricherUnified:
    """Corporate PoP detection with multi-channel waterfall pipeline."""

    def __init__(self):
        self.serper_key = SERPER_API_KEY
        self.anthropic_key = ANTHROPIC_API_KEY
        self.rapidapi_key = RAPIDAPI_KEY

        if not self.serper_key:
            raise ValueError("SERPER_API_KEY not set")
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        if not self.rapidapi_key:
            raise ValueError("RAPIDAPI_KEY not set")

    # ========== DOMAIN VALIDATION HELPERS ==========

    def extract_domain(self, url: str) -> str:
        """Extract clean domain from URL."""
        domain = urlparse(url).netloc.lower()
        # Remove www and common subdomains
        domain = re.sub(r'^(www\d?\.|media\.|careers\.|about\.|blog\.|images\.|static\.)', '', domain)
        return domain

    def domain_plausibly_matches_company(self, domain: str, company_name: str) -> bool:
        """Quick sanity check: could this domain belong to this company?"""
        company_clean = company_name.lower().replace(',', '').replace('.', '').replace('inc', '').replace('llc', '').replace('corp', '').replace('corporation', '').strip()
        company_words = [w for w in company_clean.split() if len(w) > 3]
        return any(word in domain for word in company_words)

    def domains_match(self, domain1: str, domain2: str) -> bool:
        """Check if two domains match (fuzzy matching)."""
        d1 = self.extract_domain(domain1) if '://' in domain1 else domain1.lower()
        d2 = self.extract_domain(domain2) if '://' in domain2 else domain2.lower()
        return d1 == d2 or d1 in d2 or d2 in d1

    def validate_with_sonnet(self, domain: str, company_name: str, official_website: str,
                            page_url: str = "", context: str = "",
                            validation_type: str = "domain") -> dict:
        """Use Sonnet to validate domain-company relationship or image authenticity."""
        try:
            if not hasattr(self, '_anthropic_client'):
                from anthropic import Anthropic
                self._anthropic_client = Anthropic(api_key=self.anthropic_key)

            if validation_type == "news_image":
                prompt = f"""You are validating an image from a trusted news source.

Company: {company_name}
Image URL: {domain}
News site: {page_url}
{f"Context: {context}" if context else ""}

Your task:
Determine if the IMAGE URL is a real photo of {company_name}'s facilities/operations,
or if it's a stock photo (Getty, Shutterstock, etc.) used to illustrate the article.

Consider:
- Is the image URL from a stock photo service (gettyimages, shutterstock, istockphoto)?
- Is it from the news site's own photo archive (likely real)?
- Does the URL suggest it's an AP/Reuters wire photo (likely real)?

Respond in EXACTLY this format:
VERDICT: YES (real photo) / NO (stock photo)
CONFIDENCE: HIGH/MEDIUM/LOW
REASONING: [One clear sentence explaining your decision]"""
            else:
                prompt = f"""Validate whether this domain belongs to this company.

Company: {company_name}
Domain to validate: {domain}
Official website from our records: {official_website or "Not available"}
{f"Page URL: {page_url}" if page_url else ""}
{f"Context: {context}" if context else ""}

Your task:
1. Determine if {domain} is owned by/represents {company_name}
2. Watch for companies with similar names or abbreviations

Consider:
- Does the domain match the company's known web presence?
- Is this a different company with a similar name/abbreviation?
- Does the official website match our domain?

Examples:
- "USI" + "usiweston.com" = NO (Ultimate Sports Institute gym, not USI insurance)
- "Bank of the West" + "westbankclub.com" = NO (West Bank Club, not Bank of the West)

Respond in EXACTLY this format:
VERDICT: YES/NO
CONFIDENCE: HIGH/MEDIUM/LOW
REASONING: [One clear sentence explaining your decision]"""

            response = self._anthropic_client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}]
            )

            content = response.content[0].text

            # Parse response
            verdict = "NO"
            confidence = "LOW"
            reasoning = "Unable to parse response"

            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('VERDICT:'):
                    verdict = line.split(':', 1)[1].strip().upper()
                elif line.startswith('CONFIDENCE:'):
                    confidence = line.split(':', 1)[1].strip().upper()
                elif line.startswith('REASONING:'):
                    reasoning = line.split(':', 1)[1].strip()

            # Calculate cost
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost = (input_tokens * 0.000003) + (output_tokens * 0.000015)

            return {
                'valid': verdict == "YES" and confidence in ["HIGH", "MEDIUM"],
                'confidence': confidence,
                'reasoning': reasoning,
                'cost': cost
            }

        except Exception as e:
            print(f"    Sonnet validation error: {e}")
            return {
                'valid': False,
                'confidence': 'LOW',
                'reasoning': f'Validation error: {str(e)[:50]}',
                'cost': 0.0
            }

    def is_domain_valid(self, image_url: str, company_name: str, official_website: str = "",
                       image_title: str = "", page_url: str = "") -> tuple[bool, str, float]:
        """Multi-layer domain validation. Returns (is_valid, reason, cost)."""

        total_cost = 0.0
        domain = urlparse(image_url).netloc.lower()
        domain_base = re.sub(r'^(www\d?\.|media\.|careers\.|about\.|blog\.|images\.|static\.)', '', domain)
        page_domain = urlparse(page_url).netloc.lower() if page_url else domain

        company_clean = company_name.lower().replace(',', '').replace('.', '').replace('inc', '').replace('llc', '').replace('corp', '').replace('corporation', '').strip()
        company_words = set(company_clean.split())

        # Initialize Anthropic client
        if not hasattr(self, '_anthropic_client'):
            from anthropic import Anthropic
            self._anthropic_client = Anthropic(api_key=self.anthropic_key)

        # ========== LAYER 1: STATIC RULES (FREE) ==========

        # REJECT: Stock photo sites
        stock_photo_domains = ['gettyimages.com', 'shutterstock.com', 'istockphoto.com',
                               'adobestock.com', 'dreamstime.com', 'depositphotos.com']
        for stock_domain in stock_photo_domains:
            if stock_domain in domain or stock_domain in image_url.lower():
                return False, f"Stock photo site ({stock_domain})", 0.0

        # REJECT: Generic CDNs
        generic_cdn_domains = ['squarespace-cdn.com', 'squarespace.com', 'cloudinary.com',
                               'amazonaws.com', 's3.amazonaws.com', 'wixstatic.com',
                               'contentstack.io', 'imgix.net', 'cloudfront.net',
                               'creativecirclecdn.com', 'files.edl.io']
        for cdn_domain in generic_cdn_domains:
            if cdn_domain in domain:
                return False, f"Generic CDN ({cdn_domain})", 0.0

        # REJECT: Third-party sites
        third_party_indicators = ['fitness', 'gym', 'architect', 'design', 'construction',
                                  'flooring', 'equipment', 'wellness', 'healthclub']
        for indicator in third_party_indicators:
            if indicator in domain:
                return False, f"Third-party {indicator} site", 0.0

        # REJECT: Local directories
        local_guide_indicators = ['.guide', 'yelp.com', 'yellowpages.com', 'foursquare.com']
        for guide in local_guide_indicators:
            if guide in domain:
                return False, "Local directory", 0.0

        # REJECT: Social media CDNs
        social_cdn_domains = ['lookaside.instagram.com', 'lookaside.fbsbx.com', 'scontent.']
        for social_cdn in social_cdn_domains:
            if social_cdn in domain:
                return False, "Social media CDN", 0.0

        # ========== LAYER 2: SALESFORCE OFFICIAL WEBSITE MATCH (FREE) ==========

        if official_website:
            official_domain = self.extract_domain(official_website)
            if self.domain_plausibly_matches_company(official_domain, company_name):
                if self.domains_match(domain, official_domain):
                    return True, f"Official domain match (Salesforce: {official_domain})", 0.0

        # ========== LAYER 3: TRUSTED NEWS + SONNET VERIFICATION ($0.0011) ==========

        trusted_news_domains = {
            'bizj.us': 'Business Journals',
            'bizjournals.com': 'Business Journals',
            'businessjournals.com': 'Business Journals',
            'law.com': 'Law.com',
            'journalrecord.com': 'Journal Record',
            'detroitnews.com': 'Detroit News',
            'azcentral.com': 'Arizona Central'
        }

        for news_domain, news_name in trusted_news_domains.items():
            if news_domain in page_domain:
                title_lower = (image_title or "").lower()
                url_lower = (page_url or "").lower()
                if any(word in title_lower or word in url_lower for word in company_words if len(word) > 3):
                    context = f"News article from {news_name}"
                    if image_title:
                        context += f" - Article title: {image_title}"

                    validation = self.validate_with_sonnet(
                        domain=image_url,
                        company_name=company_name,
                        official_website=official_website,
                        page_url=page_url,
                        context=context,
                        validation_type="news_image"
                    )

                    total_cost += validation['cost']

                    if validation['valid']:
                        return True, f"Trusted news ({news_name}) verified by Sonnet", total_cost
                    else:
                        return False, f"Trusted news but Sonnet rejected: {validation['reasoning']}", total_cost

        # ========== LAYER 4: SONNET DOMAIN VALIDATION ($0.0011) ==========

        for word in company_words:
            if len(word) > 3 and word in domain_base:
                validation = self.validate_with_sonnet(
                    domain=domain_base,
                    company_name=company_name,
                    official_website=official_website,
                    page_url=page_url,
                    context=f"Domain contains company word '{word}' but needs verification"
                )

                total_cost += validation['cost']

                if validation['valid']:
                    return True, f"Domain verified by Sonnet (matched: {word})", total_cost
                else:
                    return False, f"Domain fuzzy match rejected by Sonnet: {validation['reasoning']}", total_cost

        return False, "Unverified domain (no match found)", total_cost

    def is_us_relevant(self, image_url: str, image_title: str, operating_market: str = "United States") -> bool:
        """Check if image is from correct geographic market."""
        if operating_market != "United States":
            return True

        international_indicators = [
            'india', 'china', 'uk', 'united kingdom', 'germany', 'france',
            'japan', 'australia', 'canada', 'mexico', 'brazil', 'singapore',
            'bengaluru', 'bangalore', 'london', 'beijing', 'tokyo',
            'emea', 'apac', 'latam', 'asia pacific', 'european',
        ]

        url_lower = image_url.lower()
        title_lower = image_title.lower()

        for indicator in international_indicators:
            if indicator in url_lower or indicator in title_lower:
                return False

        return True

    def validate_image(self, image_url: str, timeout: int = 10) -> Optional[bytes]:
        """Download and validate image before VLM."""
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(image_url, headers=headers, timeout=timeout, stream=True)

            if response.status_code != 200:
                return None

            content = response.content
            size_kb = len(content) / 1024

            if size_kb < 5 or size_kb > 5000:
                return None

            img_format = imghdr.what(None, h=content)
            if not img_format:
                return None

            try:
                img = Image.open(io.BytesIO(content))
                img.verify()
            except:
                return None

            return content

        except:
            return None

    # ========== CHANNEL 1: IMAGE SEARCH ==========

    def search_corporate_images(self, company_name: str, operating_market: str = "United States") -> Optional[list]:
        """Search for corporate office images via Serper API."""

        queries = [
            f"{company_name} USA headquarters gym fitness center" if operating_market == "United States" else f"{company_name} headquarters gym fitness center",
            f"{company_name} office cafeteria break room",
            f"{company_name} United States headquarters employee lounge" if operating_market == "United States" else f"{company_name} headquarters employee lounge",
            f"{company_name} corporate office common area",
        ]

        all_images = []

        # TRY ALL QUERIES (no early exit)
        for query in queries:
            try:
                url = "https://google.serper.dev/images"
                payload = json.dumps({"q": query, "num": 10})  # Get 10 per query
                headers = {
                    'X-API-KEY': self.serper_key,
                    'Content-Type': 'application/json'
                }

                response = requests.post(url, headers=headers, data=payload, timeout=30)

                if response.status_code != 200:
                    continue

                data = response.json()
                images = data.get("images", [])

                for img in images[:10]:  # Top 10 per query
                    all_images.append({
                        'url': img.get('imageUrl'),
                        'title': img.get('title', ''),
                        'source': img.get('link', ''),
                        'query': query
                    })

            except Exception as e:
                print(f"  Image search error: {e}")
                continue

        return all_images if all_images else None

    def analyze_image_vlm(self, image_content: bytes, company_name: str, source: str = "image_search") -> Optional[Dict]:
        """Analyze validated image for TV evidence using VLM."""

        try:
            img_b64 = base64.b64encode(image_content).decode('utf-8')

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

            text_content = next(
                (block.text for block in response.content if hasattr(block, 'text')),
                None
            )

            if not text_content:
                return None

            json_start = text_content.find('{')
            json_end = text_content.rfind('}') + 1

            if json_start == -1 or json_end == 0:
                return None

            result = json.loads(text_content[json_start:json_end])

            # Calculate cost
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost = (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0)

            result['cost'] = cost
            return result

        except Exception as e:
            print(f"    VLM error: {str(e)[:100]}")
            return None

    def channel_image_search(self, company_name: str, operating_market: str, official_website: str) -> Optional[Dict]:
        """Channel 1: Image search with multi-layer validation."""

        print(f"📷 CHANNEL 1: Image Search")
        print(f"  Searching images for {company_name} ({operating_market})...")

        images = self.search_corporate_images(company_name, operating_market)

        if not images:
            print(f"  ❌ No images found")
            return None

        print(f"  ✓ Found {len(images)} images across all queries")

        total_cost = 0.001 * 4  # Serper API cost for 4 queries
        images_analyzed = 0
        images_failed = 0

        # Analyze up to 20 images (increased from 10)
        for i, img in enumerate(images[:20], 1):
            if not img.get('url'):
                continue

            print(f"  Analyzing image {i}/{min(len(images), 20)}...", end=" ")

            # Domain validation
            is_valid_domain, domain_reason, validation_cost = self.is_domain_valid(
                img['url'],
                company_name,
                official_website=official_website,
                image_title=img.get('title', ''),
                page_url=img.get('source', '')
            )

            total_cost += validation_cost

            if not is_valid_domain:
                print(f"rejected ({domain_reason})")
                images_failed += 1
                continue

            # Geographic check
            if not self.is_us_relevant(img['url'], img.get('title', ''), operating_market):
                print("international (skipped)")
                images_failed += 1
                continue

            # Image validation
            image_content = self.validate_image(img['url'])
            if not image_content:
                images_failed += 1
                continue

            print("valid,", end=" ")

            # VLM analysis
            analysis = self.analyze_image_vlm(image_content, company_name, "image_search")

            if not analysis:
                images_failed += 1
                print("analysis failed")
                continue

            images_analyzed += 1
            total_cost += analysis.get('cost', 0.0)

            # Check for valid TV evidence
            if (analysis['tv_detected'] and
                analysis['is_entertainment_tv'] and
                analysis['is_communal_space'] and
                analysis['confidence'] in ['high', 'medium'] and
                not analysis.get('is_menu_board', False) and
                not analysis.get('is_logo_display', False) and
                not analysis.get('is_black_screen', False)):

                print(f"✅ PROSPECT!")
                return {
                    'tier': 'PROSPECT',
                    'channel': 'image_search',
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

        print(f"  ❌ No TV evidence in {images_analyzed} images analyzed")
        return {'cost': total_cost, 'images_analyzed': images_analyzed, 'images_failed': images_failed}

    # ========== CHANNEL 2: YOUTUBE VIDEO ==========

    def search_youtube_videos(self, company_name: str) -> Optional[List[Dict]]:
        """Search YouTube for corporate office tour videos."""

        queries = [
            f"{company_name} office tour",
            f"{company_name} headquarters tour",
            f"{company_name} workplace tour",
            f"{company_name} office virtual tour",
        ]

        all_videos = []

        for query in queries:
            try:
                url = "https://youtube-v3-alternative.p.rapidapi.com/search"
                headers = {
                    "X-RapidAPI-Key": self.rapidapi_key,
                    "X-RapidAPI-Host": "youtube-v3-alternative.p.rapidapi.com"
                }
                params = {"query": query, "type": "video"}

                response = requests.get(url, headers=headers, params=params, timeout=30)

                if response.status_code != 200:
                    continue

                data = response.json()
                items = data.get("data", [])

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    video_id = item.get("videoId")
                    title = item.get("title", "")

                    if not video_id or not title:
                        continue

                    title_lower = title.lower()

                    if any(kw in title_lower for kw in ["tour", "office", "headquarters", "workplace", "campus", "facility"]):
                        all_videos.append({
                            "video_id": video_id,
                            "title": title,
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "channel_title": item.get("channelTitle", "")
                        })

                if all_videos:
                    break

            except Exception as e:
                print(f"  YouTube search error: {e}")
                continue

        return all_videos[:3] if all_videos else None

    def download_video(self, video_url: str, output_dir: Path) -> Optional[Path]:
        """Download YouTube video using pytubefix."""

        max_retries = 3
        for attempt in range(max_retries):
            try:
                from pytubefix import YouTube

                yt = YouTube(video_url)

                stream = yt.streams.filter(
                    file_extension='mp4',
                    only_video=True
                ).order_by('resolution').first()

                if not stream:
                    stream = yt.streams.filter(file_extension='mp4').first()

                if not stream:
                    return None

                output_file = stream.download(
                    output_path=str(output_dir),
                    filename=f"{yt.video_id}.mp4"
                )

                return Path(output_file)

            except Exception as e:
                if '503' in str(e) and attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5
                    print(f"    Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    return None

        return None

    def extract_frames(self, video_path: Path, interval_seconds: int = 2) -> List[Path]:
        """Extract frames from video at regular intervals."""

        frames = []
        video = cv2.VideoCapture(str(video_path))

        if not video.isOpened():
            return frames

        fps = video.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30

        frame_interval = int(fps * interval_seconds)
        frame_count = 0
        saved_count = 0

        output_dir = video_path.parent / "frames"
        output_dir.mkdir(exist_ok=True)

        while True:
            ret, frame = video.read()
            if not ret:
                break

            if frame_count % frame_interval == 0:
                frame_path = output_dir / f"frame_{saved_count:04d}.jpg"
                cv2.imwrite(str(frame_path), frame)
                frames.append(frame_path)
                saved_count += 1

                if saved_count >= 30:
                    break

            frame_count += 1

        video.release()
        return frames

    def yolo_detect_tv(self, frame_path: Path) -> Optional[Dict]:
        """Run YOLO detection on frame to find TVs/monitors."""
        from ultralytics import YOLO

        try:
            model = YOLO('yolo11n.pt')
            results = model(str(frame_path), conf=0.20, verbose=False)

            for result in results:
                boxes = result.boxes
                for box in boxes:
                    cls = int(box.cls[0])
                    conf = float(box.conf[0])

                    # Class 62 = TV, 63 = laptop, 67 = cell phone
                    if cls in [62, 63]:  # TV or laptop (monitors)
                        return {
                            'detected': True,
                            'class': cls,
                            'class_name': 'tv' if cls == 62 else 'monitor',
                            'confidence': conf,
                            'frame': str(frame_path)
                        }

            return None

        except Exception as e:
            print(f"    YOLO error: {e}")
            return None

    def channel_youtube_video(self, company_name: str) -> Optional[Dict]:
        """Channel 2: YouTube video + YOLO + VLM."""

        print(f"🎥 CHANNEL 2: YouTube Video")
        print(f"  Searching YouTube for {company_name}...")

        videos = self.search_youtube_videos(company_name)

        if not videos:
            print(f"  ❌ No videos found")
            return None

        print(f"  ✓ Found {len(videos)} videos")

        total_cost = 0.001  # YouTube search

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            for video in videos[:2]:  # Try top 2 videos
                video_title = video['title']
                video_url = video['url']

                print(f"  Processing: {video_title[:60]}...")

                # Download video
                video_path = self.download_video(video_url, tmpdir_path)
                if not video_path:
                    print(f"    ❌ Download failed")
                    continue

                print(f"    ✓ Downloaded video")

                # Extract frames
                frames = self.extract_frames(video_path, interval_seconds=2)
                if not frames:
                    print(f"    ❌ No frames extracted")
                    continue

                print(f"    ✓ Extracted {len(frames)} frames")

                # YOLO detection
                tv_frames = []
                for frame in frames:
                    detection = self.yolo_detect_tv(frame)
                    if detection:
                        tv_frames.append(frame)

                if not tv_frames:
                    print(f"    ❌ No TVs detected by YOLO")
                    continue

                print(f"    ✓ YOLO found TVs in {len(tv_frames)} frames")

                # VLM confirmation on frames with TVs
                for frame in tv_frames[:3]:  # Check up to 3 frames
                    with open(frame, 'rb') as f:
                        frame_content = f.read()

                    analysis = self.analyze_image_vlm(frame_content, company_name, "youtube_video")

                    if not analysis:
                        continue

                    total_cost += analysis.get('cost', 0.0)

                    if (analysis['tv_detected'] and
                        analysis['is_entertainment_tv'] and
                        analysis['is_communal_space'] and
                        analysis['confidence'] in ['high', 'medium']):

                        print(f"    ✅ PROSPECT!")
                        return {
                            'tier': 'PROSPECT',
                            'channel': 'youtube_video',
                            'evidence_url': video_url,
                            'video_title': video_title,
                            'tv_location': analysis.get('tv_location', ''),
                            'confidence': analysis.get('confidence', 'low'),
                            'tv_powered_on': analysis.get('tv_powered_on', False),
                            'reasoning': analysis.get('reasoning', ''),
                            'cost': total_cost,
                            'details': {
                                'video': video,
                                'frame': str(frame),
                                'vlm_analysis': analysis,
                                'tv_frames_found': len(tv_frames)
                            }
                        }

        print(f"  ❌ No TV evidence in videos")
        return {'cost': total_cost}

    # ========== MAIN ENRICHMENT ==========

    def enrich_account(self, company_name: str, operating_market: str = "United States",
                      official_website: str = "") -> Dict:
        """
        Multi-channel waterfall enrichment with early exit.

        Tries each channel in order until finding evidence.
        Returns after first PROSPECT found.
        """

        print(f"\n{'='*70}")
        print(f"CORPORATE ENRICHMENT: {company_name}")
        print(f"{'='*70}")

        total_cost = 0.0

        # CHANNEL 1: Image Search
        result = self.channel_image_search(company_name, operating_market, official_website)
        if result and result.get('tier') == 'PROSPECT':
            return result  # Early exit - found evidence!

        if result:
            total_cost += result.get('cost', 0.0)

        # CHANNEL 2: YouTube Video
        result = self.channel_youtube_video(company_name)
        if result and result.get('tier') == 'PROSPECT':
            result['cost'] = total_cost + result.get('cost', 0.0)
            return result  # Early exit - found evidence!

        if result:
            total_cost += result.get('cost', 0.0)

        # No evidence found in any channel
        print(f"\n❌ REJECTED: No TV evidence found across all channels")
        print(f"💰 Total cost: ${total_cost:.4f}")

        return {
            'tier': 'REJECTED',
            'channel': 'none',
            'evidence_url': '',
            'confidence': 'none',
            'cost': total_cost,
            'details': {'reason': 'No TV evidence found in image search or video channels'}
        }


def process_account(record: Dict) -> Dict:
    """Process corporate account with unified multi-channel enricher."""

    enricher = CorporateEnricherUnified()

    company_name = record.get('account_name', '')
    operating_market = record.get('operating_market', 'United States')
    official_website = record.get('website', '')

    if not company_name:
        return {
            **record,
            'tier': 'REJECTED',
            'channel': 'none',
            'error': 'Missing account_name'
        }

    result = enricher.enrich_account(company_name, operating_market, official_website)

    return {**record, **result}
