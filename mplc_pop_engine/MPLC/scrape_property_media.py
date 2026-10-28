#!/usr/bin/env python3
"""
Property Website Media Scraper for MDU PoP Detection

Scrapes property websites for:
- Embedded videos (virtual tours, community videos)
- Photo galleries (common areas, amenities)
- Runs YOLO+VLM analysis for TV detection

Much cheaper than YouTube API approach.
"""

import re
import csv
import json
import time
import logging
import os
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import requests

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


class PropertyMediaScraper:
    """Scrape media from property websites."""

    def __init__(self, output_dir: str = 'property_media'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Create subdirectories
        (self.output_dir / 'videos').mkdir(exist_ok=True)
        (self.output_dir / 'images').mkdir(exist_ok=True)

    def scrape_property_page(self, property_url: str, property_name: str) -> Dict:
        """
        Scrape a property page for media.

        Returns:
            {
                'property_url': str,
                'videos': [{'url': str, 'type': str}],
                'images': [{'url': str, 'type': str}],
                'media_found': bool,
            }
        """
        log.info(f"Scraping: {property_name}")

        try:
            html = self._fetch_page(property_url)

            if not html:
                return {
                    'property_url': property_url,
                    'videos': [],
                    'images': [],
                    'media_found': False,
                }

            soup = BeautifulSoup(html, 'html.parser')

            # Extract videos
            videos = self._extract_videos(soup, property_url)

            # Extract images (focus on common areas)
            images = self._extract_images(soup, property_url)

            # Log details about images found
            if images:
                common_area_count = sum(1 for img in images if img['type'] == 'common_area')
                high_priority_count = sum(1 for img in images if img.get('priority') == 'high')
                log.info(f"  Found: {len(videos)} videos, {len(images)} images")
                log.info(f"    - {common_area_count} common area images")
                log.info(f"    - {high_priority_count} high-priority images")
                # Log sample URLs for verification
                for img in images[:3]:
                    log.info(f"    - Sample: {img['url'][:100]}...")
            else:
                log.info(f"  Found: {len(videos)} videos, 0 images (all filtered out)")

            return {
                'property_url': property_url,
                'videos': videos,
                'images': images,
                'media_found': len(videos) + len(images) > 0,
            }

        except Exception as e:
            log.error(f"  Error scraping {property_url}: {e}")
            return {
                'property_url': property_url,
                'videos': [],
                'images': [],
                'media_found': False,
            }

    def _fetch_page(self, url: str) -> Optional[str]:
        """Fetch property page with Playwright."""
        if not PLAYWRIGHT_AVAILABLE:
            log.error("Playwright not available")
            return None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                )
                page = context.new_page()

                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                time.sleep(3)  # Let JS load

                html = page.content()
                browser.close()

                return html

        except Exception as e:
            log.error(f"  Fetch error: {e}")
            return None

    def _extract_videos(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """Extract video URLs from property page."""
        videos = []

        # Pattern 1: YouTube embeds
        youtube_iframes = soup.find_all('iframe', src=re.compile(r'youtube\.com/embed'))
        for iframe in youtube_iframes:
            src = iframe.get('src')
            if src:
                video_id = self._extract_youtube_id(src)
                if video_id:
                    videos.append({
                        'url': f"https://www.youtube.com/watch?v={video_id}",
                        'type': 'youtube',
                        'embed_src': src,
                    })

        # Pattern 2: Video tags
        video_tags = soup.find_all('video')
        for video in video_tags:
            src = video.get('src')
            if not src:
                # Check for source children
                source = video.find('source')
                if source:
                    src = source.get('src')

            if src:
                full_url = urljoin(base_url, src)
                videos.append({
                    'url': full_url,
                    'type': 'html5_video',
                })

        # Pattern 3: Vimeo embeds
        vimeo_iframes = soup.find_all('iframe', src=re.compile(r'player\.vimeo\.com'))
        for iframe in vimeo_iframes:
            src = iframe.get('src')
            if src:
                videos.append({
                    'url': src,
                    'type': 'vimeo',
                })

        # Pattern 4: Links to video files
        video_links = soup.find_all('a', href=re.compile(r'\.(mp4|webm|mov)$', re.I))
        for link in video_links:
            href = link.get('href')
            if href:
                full_url = urljoin(base_url, href)
                videos.append({
                    'url': full_url,
                    'type': 'video_file',
                })

        return videos

    def _extract_images(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """Extract images from property page, focusing on common areas."""
        images = []

        # Look for images in galleries/sliders
        gallery_containers = soup.find_all(
            ['div', 'section'],
            class_=re.compile(r'gallery|slider|carousel|photos|amenities', re.I)
        )

        for container in gallery_containers:
            # Get all images in this container
            imgs = container.find_all('img')

            for img in imgs[:50]:  # Check up to 50 images per property (but filter heavily)
                src = img.get('src') or img.get('data-src') or img.get('data-lazy') or img.get('data-original')

                if not src:
                    continue

                src_lower = src.lower()

                # FILTER 1: Skip SVG files completely (these are icons, not photos)
                if '.svg' in src_lower or src_lower.endswith('.svg'):
                    continue

                # FILTER 2: Check if it's a photo format
                # Accept explicit extensions OR image resizer/CDN URLs (which are likely photos)
                is_photo_ext = any(ext in src_lower for ext in ['.jpg', '.jpeg', '.png', '.webp'])
                is_cdn_image = any(cdn in src_lower for cdn in ['cdn', 'cloudfront', 'imgix', 'cloudinary', 'arcpublishing', 'resizer'])

                # Skip if it's not a photo format and not from an image CDN
                if not is_photo_ext and not is_cdn_image:
                    continue

                # FILTER 3: Skip tiny images (icons, logos, thumbnails)
                if any(skip in src.lower() for skip in [
                    'logo', 'icon', 'avatar', 'thumb', 'badge', 'button',
                    'sprite', 'placeholder', 'emoji', 'arrow'
                ]):
                    continue

                # FILTER 4: Look for high-resolution indicators in URL
                has_hires_indicator = any(indicator in src.lower() for indicator in [
                    'large', 'full', 'original', '1920', '1280', '1024', '800',
                    'hero', 'gallery', 'photo', 'image'
                ])

                # FILTER 5: Check image dimensions if available
                width = img.get('width')
                height = img.get('height')

                # If dimensions are specified, require minimum size
                if width and height:
                    try:
                        w = int(width)
                        h = int(height)
                        # Skip images smaller than 300x300 (likely icons/logos)
                        if w < 300 or h < 300:
                            continue
                    except (ValueError, TypeError):
                        pass  # Dimensions not numeric, can't filter on this

                full_url = urljoin(base_url, src)

                # Categorize image type based on context
                alt_text = (img.get('alt') or '').lower()
                img_class = ' '.join(img.get('class', [])).lower()

                image_type = self._categorize_image(alt_text, img_class)

                # Prioritize images from amenity/gallery sections
                priority = 'high' if has_hires_indicator or image_type == 'common_area' else 'medium'

                images.append({
                    'url': full_url,
                    'type': image_type,
                    'alt_text': img.get('alt'),
                    'priority': priority,
                })

        # Also check for background images in CSS
        # (common for hero sections)
        style_divs = soup.find_all(['div', 'section'], style=re.compile(r'background-image'))
        for div in style_divs[:10]:
            style = div.get('style', '')
            url_match = re.search(r'url\([\'"]?([^\'"]+)[\'"]?\)', style)
            if url_match:
                url = url_match.group(1)
                url_lower = url.lower()

                # Apply same filters to background images
                if '.svg' in url_lower or url_lower.endswith('.svg'):
                    continue

                # Check if it's a photo format or CDN URL
                is_photo_ext = any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp'])
                is_cdn_image = any(cdn in url_lower for cdn in ['cdn', 'cloudfront', 'imgix', 'cloudinary', 'arcpublishing', 'resizer'])

                if not is_photo_ext and not is_cdn_image:
                    continue

                full_url = urljoin(base_url, url)
                images.append({
                    'url': full_url,
                    'type': 'background',
                    'priority': 'high',  # Background images are usually hero/feature images
                })

        # Sort by priority (high resolution / common area images first)
        images.sort(key=lambda x: 0 if x.get('priority') == 'high' else 1)

        # Limit to top 20 images after filtering and sorting
        return images[:20]

    def _categorize_image(self, alt_text: str, img_class: str) -> str:
        """Categorize image based on context."""
        combined = f"{alt_text} {img_class}"

        # Common area keywords
        if any(kw in combined for kw in ['lobby', 'lounge', 'clubhouse', 'amenity', 'fitness', 'gym']):
            return 'common_area'
        elif any(kw in combined for kw in ['pool', 'patio', 'outdoor', 'courtyard']):
            return 'outdoor'
        elif any(kw in combined for kw in ['unit', 'apartment', 'bedroom', 'kitchen', 'interior']):
            return 'unit_interior'
        else:
            return 'unknown'

    def _extract_youtube_id(self, url: str) -> Optional[str]:
        """Extract YouTube video ID from URL."""
        patterns = [
            r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
            r'youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
            r'youtu\.be/([a-zA-Z0-9_-]{11})',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return None


def process_properties(input_csv: str, output_csv: str, limit: int = None):
    """Process properties and extract media."""

    # Read properties
    with open(input_csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        properties = list(reader)

    if limit:
        properties = properties[:limit]

    log.info(f"Processing {len(properties)} properties from {input_csv}")

    scraper = PropertyMediaScraper()

    results = []
    media_found_count = 0

    for i, prop in enumerate(properties, 1):
        property_url = prop.get('property_url')
        property_name = prop.get('community_name', 'Unknown')

        if not property_url:
            log.warning(f"[{i}/{len(properties)}] No URL for {property_name}, skipping")
            continue

        log.info(f"[{i}/{len(properties)}] {property_name}")

        # Scrape media
        media = scraper.scrape_property_page(property_url, property_name)

        if media['media_found']:
            media_found_count += 1

        # Combine property info with media
        result = {
            'reit': prop.get('reit'),
            'community_name': property_name,
            'city': prop.get('city'),
            'state': prop.get('state'),
            'property_url': property_url,
            'videos_found': len(media['videos']),
            'images_found': len(media['images']),
            'video_urls': json.dumps([v['url'] for v in media['videos']]),
            'image_urls': json.dumps([img['url'] for img in media['images']]),
        }

        results.append(result)

        # Progress
        if i % 10 == 0:
            log.info(f"  Progress: {i}/{len(properties)} ({i/len(properties)*100:.1f}%)")
            log.info(f"  Properties with media: {media_found_count}")

        # Rate limiting
        time.sleep(2)

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Properties processed: {len(results)}")
    print(f"Properties with media: {media_found_count} ({media_found_count/len(results)*100:.1f}%)")

    total_videos = sum(r['videos_found'] for r in results)
    total_images = sum(r['images_found'] for r in results)
    print(f"Total videos found: {total_videos}")
    print(f"Total images found: {total_images}")
    print(f"\nCost: $0 (no API calls needed!)")

    # Write CSV
    fieldnames = [
        'reit', 'community_name', 'city', 'state', 'property_url',
        'videos_found', 'images_found', 'video_urls', 'image_urls'
    ]

    with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nWrote to: {output_csv}")
    print("Ready for YOLO+VLM analysis!")

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Scrape property website media')
    parser.add_argument('--input', default='all_reit_properties.csv', help='Input CSV')
    parser.add_argument('--output', default='properties_with_media.csv', help='Output CSV')
    parser.add_argument('--limit', type=int, help='Limit number of properties')

    args = parser.parse_args()

    process_properties(args.input, args.output, args.limit)


if __name__ == '__main__':
    main()
