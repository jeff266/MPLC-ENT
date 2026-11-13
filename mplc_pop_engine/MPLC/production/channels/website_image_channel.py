#!/usr/bin/env python3
"""
Generic Website Image Evidence Channel

Parameterized for reuse across verticals (MDU, Healthcare, Corporate, etc.)
Extracts images from property websites, runs YOLO + VLM verification.

Four extraction methods:
1. <img src> tags
2. <img srcset> / <picture><source srcset> - parse largest resolution
3. Inline style="background-image: url(...)"
4. <a href> links to image files (lightbox galleries)

Includes:
- Deduplication (within-page and cross-property via image hashing)
- VLM gate (every YOLO-positive must pass vertical-specific prompt)
- Explicit rejection-reason taxonomy
- Scroll/load-more handling for JS-rendered galleries
"""

import os
import re
import sys
import time
import json
import hashlib
from pathlib import Path

try:
    import imghdr  # Python < 3.13
except ModuleNotFoundError:
    # Removed in Python 3.13 (PEP 594) -- see enrichers/image_sniff.py for why/what.
    # FIX (2026-11-13): this module previously had an unguarded `import imghdr`
    # with no fallback at all -- it would have crashed outright on Python 3.13+
    # (not even degraded gracefully like the enrichers did before their own fix).
    # Path-aware because locally this file lives in production/channels/ while
    # image_sniff.py lives in production/enrichers/ (two different directories);
    # on the droplets both are deployed flattened into the same directory
    # (see deploy_all.sh), where a plain `import image_sniff` would already work.
    for _path in (Path(__file__).parent, Path(__file__).parent.parent / 'enrichers'):
        sys.path.insert(0, str(_path))
        try:
            import image_sniff as imghdr
            break
        except ModuleNotFoundError:
            continue
    else:
        raise
from datetime import datetime
from typing import List, Dict, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass

import requests
from PIL import Image
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from ultralytics import YOLO


@dataclass
class ImageEvidence:
    """Container for image evidence with metadata."""
    url: str
    file_path: Path
    hash: str
    yolo_class: str
    yolo_confidence: float
    vlm_result: Dict
    source_method: str  # 'img_src', 'srcset', 'background_image', 'a_href'


class WebsiteImageEvidenceChannel:
    """
    Generic website image evidence detection channel.

    Parameterized for vertical-specific use cases.
    """

    def __init__(
        self,
        target_object_classes: List[str],
        gallery_page_keywords: List[str],
        vlm_classification_prompt,  # str or callable(property_name, yolo_confidence) -> str
        anthropic_api_key: Optional[str] = None,
        yolo_model_path: Optional[Path] = None,
        exclude_image_keywords: Optional[List[str]] = None,
        min_yolo_confidence: float = 0.2,
    ):
        """
        Initialize website image evidence channel.

        Args:
            target_object_classes: YOLO classes to detect (e.g. ['tv', 'monitor'])
            gallery_page_keywords: Keywords for finding gallery pages (e.g. ['gallery', 'amenities'])
            vlm_classification_prompt: Vertical-specific VLM prompt (str template or callable)
            anthropic_api_key: Anthropic API key for VLM
            yolo_model_path: Path to YOLO model weights
            exclude_image_keywords: Keywords to skip (default: logos, icons, etc.)
            min_yolo_confidence: Minimum YOLO confidence threshold
        """
        self.target_object_classes = target_object_classes
        self.gallery_page_keywords = gallery_page_keywords
        self.vlm_classification_prompt = vlm_classification_prompt
        self.min_yolo_confidence = min_yolo_confidence

        # API key
        self.anthropic_api_key = anthropic_api_key or os.getenv('ANTHROPIC_API_KEY')

        # YOLO model
        if yolo_model_path and yolo_model_path.exists():
            self.yolo_model_path = yolo_model_path
        else:
            # Default fallback locations
            candidates = [
                Path(__file__).parent.parent / "dependencies/models/yolo11n.pt",
                Path.home() / ".cache/yolo11n.pt",
                Path("yolo11n.pt"),
            ]
            for path in candidates:
                if path.exists():
                    self.yolo_model_path = path
                    break
            else:
                raise FileNotFoundError("YOLO model not found in any default location")

        # Exclude keywords
        self.exclude_image_keywords = exclude_image_keywords or [
            'logo', 'icon', 'avatar', 'banner', 'header', 'footer',
            'badge', 'button', 'nav', 'menu', '.svg'
        ]

        # Cross-property deduplication tracking
        self._global_image_hashes: Dict[str, str] = {}  # hash -> first_property_name

        # Diagnostics logging
        self.diagnostics_log_path = Path(__file__).parent / "website_image_extraction_diagnostics.jsonl"

    def search_evidence(
        self,
        property_name: str,
        website_url: str,
        temp_dir: Path,
    ) -> Dict:
        """
        Search for image evidence on property website.

        Returns dict with:
            - tier: 'PROSPECT' / 'REJECTED'
            - evidence: ImageEvidence object (if PROSPECT)
            - rejection_reason: str (if REJECTED)
            - cost: float
            - images_found: int
            - images_analyzed: int
        """
        result = {
            'tier': 'REJECTED',
            'evidence': None,
            'rejection_reason': '',
            'cost': 0.0,
            'images_found': 0,
            'images_analyzed': 0,
        }

        # Initialize extraction diagnostics (populated during extraction)
        extraction_diagnostics = {
            'url': website_url,
            'domain': urlparse(website_url).netloc,
            'platform_signature': 'unknown',
            'extraction_methods': {'img_src': 0, 'srcset': 0, 'background_image': 0, 'a_href': 0},
            'scroll_triggered': False,
            'scroll_additional_images': 0,
            'screenshot_fallback_triggered': False,
            'screenshot_count': 0,
            'screenshot_fallback_outcome': None,
            'exception': None,
            'timeout': False,
        }

        try:
            # Step 1: Find gallery/amenity subpages (if keywords provided)
            target_urls = [website_url]  # Always include main page
            if self.gallery_page_keywords:
                gallery_urls = self._find_gallery_pages(website_url)
                if gallery_urls:
                    target_urls.extend(gallery_urls)
                # If no gallery pages found or error, fall back to main page only

            # Step 2: Extract image URLs from all target pages
            all_image_urls = []
            combined_diagnostics = None

            for target_url in target_urls:
                image_urls, extraction_diagnostics = self._extract_image_urls(target_url)
                all_image_urls.extend(image_urls)

                # Keep diagnostics from first page (main page)
                if combined_diagnostics is None:
                    combined_diagnostics = extraction_diagnostics
                    combined_diagnostics['gallery_pages_scraped'] = len(target_urls)
                    combined_diagnostics['gallery_pages_found'] = len(target_urls) - 1

            # Deduplicate combined image URLs
            image_urls = list(dict.fromkeys(all_image_urls))
            extraction_diagnostics = combined_diagnostics or extraction_diagnostics
            result['images_found'] = len(image_urls)

            # Step 3: Download and deduplicate images
            images_dir = temp_dir / "images"
            images_dir.mkdir(exist_ok=True, parents=True)

            downloaded_images = []
            if image_urls:
                downloaded_images = self._download_and_dedupe_images(
                    image_urls, images_dir, property_name
                )

            # Step 3b: Screenshot fallback if no images found via extraction
            # Only triggers if page loaded successfully (not timeout) but extraction found nothing
            if not downloaded_images and not extraction_diagnostics.get('timeout'):
                # Trigger screenshot fallback
                # Need to re-open page since _extract_image_urls closed browser
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        page = browser.new_page()
                        page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                        time.sleep(1)

                        screenshots, screenshot_diag = self._screenshot_fallback(
                            page, images_dir, property_name, target_url
                        )

                        browser.close()

                        # Update diagnostics
                        extraction_diagnostics.update(screenshot_diag)

                        # Add screenshots to downloaded_images list
                        # Format: (path, hash, source_method, url)
                        downloaded_images.extend(screenshots)

                except Exception as e:
                    extraction_diagnostics['screenshot_fallback_outcome'] = f'error_{type(e).__name__}'

            if not downloaded_images:
                if extraction_diagnostics.get('screenshot_fallback_triggered'):
                    result['rejection_reason'] = 'screenshot_fallback_no_hits'
                elif target_url != website_url:
                    result['rejection_reason'] = 'gallery_found_no_images_extracted'
                else:
                    result['rejection_reason'] = 'no_images_found'

                # Log diagnostics before returning
                self._log_diagnostics(
                    property_name, extraction_diagnostics,
                    result['images_found'], result['images_analyzed'],
                    result['tier'], result['rejection_reason']
                )
                return result

            # Step 4: YOLO detection
            yolo_positives = []
            for img_path, img_hash, source_method, orig_url in downloaded_images:
                detection = self._yolo_detect(img_path)
                if detection:
                    yolo_positives.append((img_path, img_hash, source_method, orig_url, detection))

            if not yolo_positives:
                # Check if ALL images were from screenshot fallback
                # If so, use specific rejection reason to distinguish from DOM extraction failures
                all_from_screenshots = all(
                    source_method.startswith('screenshot_fallback')
                    for _, _, source_method, _ in downloaded_images
                )

                if all_from_screenshots and extraction_diagnostics.get('screenshot_fallback_triggered'):
                    result['rejection_reason'] = 'screenshot_fallback_no_hits'
                    extraction_diagnostics['screenshot_fallback_outcome'] = 'no_yolo_hits'
                else:
                    result['rejection_reason'] = 'no_yolo_hits'

                self._log_diagnostics(
                    property_name, extraction_diagnostics,
                    result['images_found'], result['images_analyzed'],
                    result['tier'], result['rejection_reason']
                )
                return result

            # Step 5: VLM verification (REQUIRED GATE)
            for img_path, img_hash, source_method, orig_url, detection in yolo_positives:
                result['images_analyzed'] += 1

                vlm_result = self._vlm_verify(img_path, property_name, detection['confidence'])

                if vlm_result is None:
                    # VLM call failed
                    continue

                # Check VLM rejection reasons
                if not vlm_result.get('is_common_area', False):
                    result['rejection_reason'] = 'vlm_rejected_private_area'
                    continue

                # Check for target object confirmation (flexible field names across verticals)
                # MDU uses 'is_entertainment_tv', others might use 'is_target_object'
                is_target = vlm_result.get('is_target_object')
                if is_target is None:
                    # Fallback to is_entertainment_tv for MDU
                    is_target = vlm_result.get('is_entertainment_tv', True)

                if not is_target:
                    result['rejection_reason'] = 'vlm_rejected_not_target_object'
                    continue

                # Additional check: exclude computer monitors
                device_type = vlm_result.get('device_type', '')
                if device_type == 'computer_monitor':
                    result['rejection_reason'] = 'vlm_rejected_computer_monitor'
                    continue

                # PROSPECT found!
                # Note: Both TV/monitor AND projector+screen count as PROSPECT
                # (MPLC licensing is about public audiovisual display, not equipment type)
                # device_type field preserved in evidence for future filtering if needed

                # Determine evidence URL
                if source_method.startswith('screenshot_fallback'):
                    # Screenshot evidence - use page URL + scroll position
                    evidence_url = f"{target_url}#{source_method}"
                else:
                    # Extracted image - use preserved original URL
                    evidence_url = orig_url

                result['tier'] = 'PROSPECT'
                result['evidence'] = ImageEvidence(
                    url=evidence_url,
                    file_path=img_path,
                    hash=img_hash,
                    yolo_class=detection['class'],
                    yolo_confidence=detection['confidence'],
                    vlm_result=vlm_result,
                    source_method=source_method,
                )
                result['cost'] = result['images_analyzed'] * 0.0045  # Approx VLM cost

                # Early exit on screenshot fallback hit
                if source_method.startswith('screenshot_fallback'):
                    extraction_diagnostics['screenshot_fallback_outcome'] = 'prospect_found'

                # Log diagnostics before returning
                self._log_diagnostics(
                    property_name, extraction_diagnostics,
                    result['images_found'], result['images_analyzed'],
                    result['tier'], result['rejection_reason']
                )
                return result

            # All YOLO-positives rejected by VLM
            if not result['rejection_reason']:
                result['rejection_reason'] = 'all_vlm_rejected'

            result['cost'] = result['images_analyzed'] * 0.0045

            # Set screenshot fallback outcome if triggered
            if extraction_diagnostics.get('screenshot_fallback_triggered') and not extraction_diagnostics.get('screenshot_fallback_outcome'):
                extraction_diagnostics['screenshot_fallback_outcome'] = result['rejection_reason']

            # Log diagnostics before returning
            self._log_diagnostics(
                property_name, extraction_diagnostics,
                result['images_found'], result['images_analyzed'],
                result['tier'], result['rejection_reason']
            )
            return result

        except PlaywrightTimeout:
            result['rejection_reason'] = 'website_timeout'
            extraction_diagnostics['timeout'] = True
            self._log_diagnostics(
                property_name, extraction_diagnostics,
                result['images_found'], result['images_analyzed'],
                result['tier'], result['rejection_reason']
            )
            return result
        except Exception as e:
            result['rejection_reason'] = f'error_{type(e).__name__}'
            extraction_diagnostics['exception'] = f"{type(e).__name__}: {str(e)}"
            self._log_diagnostics(
                property_name, extraction_diagnostics,
                result['images_found'], result['images_analyzed'],
                result['tier'], result['rejection_reason']
            )
            return result

    def _log_diagnostics(
        self,
        property_name: str,
        extraction_diagnostics: Dict,
        images_found: int,
        images_analyzed: int,
        final_tier: str,
        rejection_reason: str = '',
    ):
        """
        Write extraction diagnostics to JSONL file for pattern analysis.

        Separate from business outcomes - tracks engineering patterns.
        """
        # Classify extraction outcome
        if extraction_diagnostics.get('timeout'):
            outcome_category = 'timeout'
            outcome_reason = 'page_timeout'
        elif extraction_diagnostics.get('exception'):
            outcome_category = 'exception'
            outcome_reason = extraction_diagnostics['exception']
        elif images_found == 0:
            outcome_category = 'empty'
            # Determine specific reason
            if extraction_diagnostics['platform_signature'] == 'unknown':
                outcome_reason = 'unknown_platform_no_images'
            else:
                outcome_reason = 'no_images_extracted'
        elif images_found < 5:
            outcome_category = 'partial'
            outcome_reason = f'only_{images_found}_images_found'
        else:
            outcome_category = 'full_success'
            outcome_reason = f'{images_found}_images_extracted'

        # Build diagnostic record
        diagnostic_record = {
            'timestamp': datetime.now().isoformat(),
            'property_name': property_name,
            'url': extraction_diagnostics.get('url', ''),
            'domain': extraction_diagnostics.get('domain', ''),
            'platform_signature': extraction_diagnostics.get('platform_signature', 'unknown'),
            'extraction_methods': extraction_diagnostics.get('extraction_methods', {}),
            'scroll_triggered': extraction_diagnostics.get('scroll_triggered', False),
            'scroll_additional_images': extraction_diagnostics.get('scroll_additional_images', 0),
            'images_found': images_found,
            'images_analyzed': images_analyzed,
            'outcome_category': outcome_category,
            'outcome_reason': outcome_reason,
            'final_tier': final_tier,
            'rejection_reason': rejection_reason,
            'exception': extraction_diagnostics.get('exception'),
            'timeout': extraction_diagnostics.get('timeout', False),
            # Screenshot fallback diagnostics
            'screenshot_fallback_triggered': extraction_diagnostics.get('screenshot_fallback_triggered', False),
            'screenshot_count': extraction_diagnostics.get('screenshot_count', 0),
            'screenshot_fallback_outcome': extraction_diagnostics.get('screenshot_fallback_outcome'),
        }

        # Append to JSONL file
        try:
            with open(self.diagnostics_log_path, 'a') as f:
                f.write(json.dumps(diagnostic_record) + '\n')
        except Exception:
            # Don't fail enrichment if diagnostics logging fails
            pass

    def _detect_platform(self, page_content: str, page_url: str) -> str:
        """
        Detect website platform/CMS from page source.

        Returns: platform signature (wordpress, realpage, entrata, appfolio, yardi, custom, unknown)
        """
        content_lower = page_content.lower()
        url_lower = page_url.lower()

        # WordPress
        if 'wp-content' in content_lower or 'wp-includes' in content_lower:
            return 'wordpress'

        # Apartment industry platforms
        if 'realpage' in content_lower or 'realpage.com' in url_lower:
            return 'realpage'

        if 'entrata' in content_lower or 'entrata.com' in url_lower:
            return 'entrata'

        if 'appfolio' in content_lower or 'appfolio.com' in url_lower:
            return 'appfolio'

        if 'yardi' in content_lower or 'rentcafe' in content_lower:
            return 'yardi_rentcafe'

        # Other common apartment platforms
        if 'g5marketingcloud' in content_lower or 'g5-assets' in content_lower:
            return 'g5_marketingcloud'

        if 'respage' in content_lower:
            return 'respage'

        if 'knock' in content_lower and 'rentals' in content_lower:
            return 'knock'

        # Generic CMS
        if 'squarespace' in content_lower:
            return 'squarespace'

        if 'wix.com' in content_lower or 'wixstatic.com' in content_lower:
            return 'wix'

        if 'shopify' in content_lower:
            return 'shopify'

        # Custom site (has structured content but no known platform)
        # Look for common frameworks
        if any(fw in content_lower for fw in ['react', 'vue.js', 'angular', 'next.js']):
            return 'custom_framework'

        return 'unknown'

    def _find_gallery_pages(self, website_url: str) -> List[str]:
        """
        Find ALL gallery/amenity subpages using keywords.

        Returns:
            - List of gallery page URLs (may be empty if none found)
            - Empty list on error/timeout
        """
        gallery_pages = []
        seen_urls = set()

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(website_url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(1)

                # Look for ALL links matching gallery keywords
                links = page.locator('a').all()
                for link in links:
                    try:
                        href = link.get_attribute('href')
                        text = link.inner_text().strip().lower()

                        if not href:
                            continue

                        combined = f"{text} {href}".lower()
                        if any(kw in combined for kw in self.gallery_page_keywords):
                            # Found gallery link
                            gallery_url = urljoin(website_url, href)

                            # Deduplicate (same page might be linked multiple times)
                            if gallery_url not in seen_urls and gallery_url != website_url:
                                gallery_pages.append(gallery_url)
                                seen_urls.add(gallery_url)
                    except:
                        continue

                browser.close()
                return gallery_pages

        except PlaywrightTimeout:
            return []
        except Exception:
            return []

    def find_embedded_videos(self, website_url: str) -> List[Dict]:
        """
        Find candidate TV-evidence videos embedded on the account's own
        website (2026-11-13, Jeff: "Perhaps videos and images from the
        websites themselves" + "add video-embed detection to the shared
        module while I'm in there").

        Checks the main page AND any gallery/amenity subpages (reusing
        _find_gallery_pages(), same as search_evidence()'s own image crawl)
        for two kinds of embed:
        1. Direct <video> files: <video><source src="...mp4/.webm"></video>
           (and a bare <video src="...">)
        2. Third-party iframe embeds: youtube.com / youtu.be / vimeo.com

        This method does NOT download, decode, or analyze the videos --
        it only finds candidate URLs. Each vertical enricher already has
        its own working download/frame-extraction/YOLO/VLM pipeline
        (download_video, extract_frames, yolo_detect_tv, analyze_frame_vlm
        in mdu_unified.py and healthcare_unified.py); the intent is for
        those to consume this method's output rather than duplicating
        video-processing logic inside this generic, vertical-agnostic
        channel. Entity-certain by construction, same as the image channel:
        since this crawls the account's OWN site, there's no search-based
        wrong-entity ambiguity (unlike a YouTube/Serper video search).

        Returns a list of dicts: {'url', 'type' ('direct'|'youtube'|'vimeo'),
        'source_page'}. Empty list on error/timeout or if nothing found.
        """
        target_urls = [website_url]
        if self.gallery_page_keywords:
            target_urls.extend(self._find_gallery_pages(website_url))

        videos: List[Dict] = []
        seen_urls: Set[str] = set()

        iframe_host_types = {
            'youtube.com': 'youtube',
            'youtu.be': 'youtube',
            'youtube-nocookie.com': 'youtube',
            'player.vimeo.com': 'vimeo',
            'vimeo.com': 'vimeo',
        }

        for target_url in target_urls:
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                    time.sleep(1)

                    # Direct <video> elements: bare src=, or nested <source src=>
                    for video_el in page.locator('video').all():
                        try:
                            direct_src = video_el.get_attribute('src')
                            if direct_src:
                                abs_url = urljoin(target_url, direct_src)
                                if abs_url not in seen_urls:
                                    videos.append({'url': abs_url, 'type': 'direct', 'source_page': target_url})
                                    seen_urls.add(abs_url)
                        except Exception:
                            pass

                    for source_el in page.locator('video source').all():
                        try:
                            src = source_el.get_attribute('src')
                            if src:
                                abs_url = urljoin(target_url, src)
                                if abs_url not in seen_urls:
                                    videos.append({'url': abs_url, 'type': 'direct', 'source_page': target_url})
                                    seen_urls.add(abs_url)
                        except Exception:
                            pass

                    # Third-party embeds: <iframe src="...youtube.com/..."> etc.
                    for iframe_el in page.locator('iframe').all():
                        try:
                            src = iframe_el.get_attribute('src')
                            if not src:
                                continue
                            abs_url = urljoin(target_url, src)
                            host = urlparse(abs_url).netloc.lower()
                            for known_host, embed_type in iframe_host_types.items():
                                if known_host in host:
                                    if abs_url not in seen_urls:
                                        videos.append({'url': abs_url, 'type': embed_type, 'source_page': target_url})
                                        seen_urls.add(abs_url)
                                    break
                        except Exception:
                            pass

                    browser.close()

            except PlaywrightTimeout:
                continue
            except Exception:
                continue

        return videos

    def _screenshot_fallback(
        self,
        page,
        output_dir: Path,
        property_name: str,
        page_url: str,
    ) -> Tuple[List[Tuple[Path, str, str, str]], Dict]:
        """
        Screenshot fallback when DOM extraction finds no images.

        Takes scroll-and-capture screenshots, returns list of (path, hash, source_method, url) tuples.
        """
        screenshots = []
        screenshot_hashes = set()
        screenshot_diagnostics = {
            'screenshot_fallback_triggered': True,
            'screenshot_count': 0,
            'screenshot_fallback_outcome': None,
        }

        try:
            # Force desktop viewport for screenshots
            page.set_viewport_size({"width": 1920, "height": 1080})

            max_screenshots = 8
            scroll_position = 0
            last_scroll_height = 0

            for i in range(max_screenshots):
                # Take screenshot
                screenshot_path = output_dir / f"screenshot_{i}.png"
                page.screenshot(path=str(screenshot_path), full_page=False)

                # Hash screenshot to detect duplicates
                with open(screenshot_path, 'rb') as f:
                    screenshot_hash = hashlib.md5(f.read()).hexdigest()[:16]

                # Skip if duplicate of previous screenshot
                if screenshot_hash in screenshot_hashes:
                    screenshot_path.unlink()
                    break

                screenshot_hashes.add(screenshot_hash)
                screenshots.append((
                    screenshot_path,
                    screenshot_hash,
                    f"screenshot_fallback_scroll_{i}",
                    page_url
                ))
                screenshot_diagnostics['screenshot_count'] += 1

                # Scroll down one viewport height
                current_scroll_height = page.evaluate("document.documentElement.scrollHeight")
                if current_scroll_height == last_scroll_height:
                    # Page height unchanged - reached bottom
                    break

                last_scroll_height = current_scroll_height
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(0.5)

        except Exception as e:
            screenshot_diagnostics['screenshot_fallback_outcome'] = f'error_{type(e).__name__}'

        return screenshots, screenshot_diagnostics

    def _extract_image_urls(self, url: str) -> Tuple[List[str], Dict]:
        """
        Extract all image URLs from page using five methods.

        Methods:
        1. <img src> - Standard image tags
        2. <img srcset> - Responsive images
        3. background-image - CSS backgrounds
        4. <a href> - Lightbox gallery links
        5. <img data-src> - Lazy-loaded images

        Returns: (deduplicated image URLs, diagnostics dict)
        """
        image_urls = []
        diagnostics = {
            'url': url,
            'domain': urlparse(url).netloc,
            'platform_signature': 'unknown',
            'extraction_methods': {
                'img_src': 0,
                'srcset': 0,
                'background_image': 0,
                'a_href': 0,
                'data_src': 0,
            },
            'scroll_triggered': False,
            'scroll_additional_images': 0,
            'exception': None,
            'timeout': False,
        }

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=15000)

                # Detect platform from page source
                page_content = page.content()
                diagnostics['platform_signature'] = self._detect_platform(page_content, url)

                # Count images before scroll
                images_before_scroll = len(image_urls)

                # Scroll to trigger lazy loading (reuse from scrape_track_a_b_v4_final.py)
                diagnostics['scroll_triggered'] = True
                for _ in range(3):
                    page.evaluate('window.scrollBy(0, 1000)')
                    time.sleep(0.5)

                # Method 1: <img src> tags
                img_elements = page.locator('img').all()
                for img in img_elements:
                    try:
                        src = img.get_attribute('src')
                        if src and not self._should_exclude(src):
                            absolute_url = urljoin(url, src)
                            if self._is_image_url(absolute_url):
                                if absolute_url not in image_urls:
                                    image_urls.append(absolute_url)
                                    diagnostics['extraction_methods']['img_src'] += 1
                    except:
                        continue

                # Method 2: <img srcset> and <picture><source srcset>
                srcset_elements = page.locator('img[srcset], source[srcset]').all()
                for elem in srcset_elements:
                    try:
                        srcset = elem.get_attribute('srcset')
                        if srcset:
                            largest = self._parse_srcset_largest(srcset, url)
                            if largest and not self._should_exclude(largest):
                                if self._is_image_url(largest):
                                    if largest not in image_urls:
                                        image_urls.append(largest)
                                        diagnostics['extraction_methods']['srcset'] += 1
                    except:
                        continue

                # Method 3: Inline style="background-image: url(...)"
                bg_elements = page.locator('[style*="background-image"]').all()
                for elem in bg_elements:
                    try:
                        style = elem.get_attribute('style')
                        if style and 'url(' in style:
                            match = re.search(r'url\(["\']?([^"\')\s]+)["\']?\)', style)
                            if match:
                                bg_url = match.group(1)
                                if not self._should_exclude(bg_url):
                                    absolute_url = urljoin(url, bg_url)
                                    if self._is_image_url(absolute_url):
                                        if absolute_url not in image_urls:
                                            image_urls.append(absolute_url)
                                            diagnostics['extraction_methods']['background_image'] += 1
                    except:
                        continue

                # Method 4: <a href> links to image files (lightbox galleries)
                link_elements = page.locator('a').all()
                for link in link_elements:
                    try:
                        href = link.get_attribute('href')
                        if href and not self._should_exclude(href):
                            absolute_url = urljoin(url, href)
                            if self._is_image_url(absolute_url):
                                if absolute_url not in image_urls:
                                    image_urls.append(absolute_url)
                                    diagnostics['extraction_methods']['a_href'] += 1
                    except:
                        continue

                # Method 5: <img data-src> lazy-loaded images
                # Captures images with real URLs in data-src and placeholders in src
                # Common pattern: <img src="data:image/gif;base64,..." data-src="real-url.jpg">
                data_src_elements = page.locator('img[data-src]').all()
                for img in data_src_elements:
                    try:
                        data_src = img.get_attribute('data-src')
                        if data_src and not self._should_exclude(data_src):
                            absolute_url = urljoin(url, data_src)
                            if self._is_image_url(absolute_url):
                                if absolute_url not in image_urls:
                                    image_urls.append(absolute_url)
                                    diagnostics['extraction_methods']['data_src'] += 1
                    except:
                        continue

                # Calculate scroll effectiveness
                images_after_scroll = len(image_urls)
                diagnostics['scroll_additional_images'] = images_after_scroll - images_before_scroll

                browser.close()

        except PlaywrightTimeout:
            diagnostics['timeout'] = True
        except Exception as e:
            diagnostics['exception'] = f"{type(e).__name__}: {str(e)}"

        # Deduplicate (preserving order)
        unique_urls = list(dict.fromkeys(image_urls))
        return unique_urls, diagnostics

    def _parse_srcset_largest(self, srcset: str, base_url: str) -> Optional[str]:
        """
        Parse srcset attribute and return the largest resolution candidate.

        srcset format: "url1 1x, url2 2x" or "url1 100w, url2 200w"
        """
        candidates = []

        # Split by comma
        parts = srcset.split(',')
        for part in parts:
            part = part.strip()
            # Format: "url descriptor" where descriptor is "1x", "2x", "100w", etc.
            tokens = part.split()
            if len(tokens) >= 1:
                url = tokens[0]
                # Extract numeric descriptor if present
                descriptor = 1.0
                if len(tokens) >= 2:
                    desc_str = tokens[1]
                    # Extract number (handles "2x", "100w", etc.)
                    match = re.match(r'(\d+\.?\d*)', desc_str)
                    if match:
                        descriptor = float(match.group(1))

                candidates.append((descriptor, url))

        if not candidates:
            return None

        # Sort by descriptor (largest first)
        candidates.sort(reverse=True)
        largest_url = candidates[0][1]

        # Convert to absolute URL
        return urljoin(base_url, largest_url)

    def _should_exclude(self, url_or_text: str) -> bool:
        """Check if URL/text matches exclusion keywords."""
        text_lower = url_or_text.lower()
        return any(kw in text_lower for kw in self.exclude_image_keywords)

    def _is_image_url(self, url: str) -> bool:
        """Check if URL is likely an image file."""
        url_lower = url.lower()
        return any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif'])

    def _hash_url(self, url: str) -> str:
        """Generate hash for URL (used for tracking before download)."""
        return hashlib.md5(url.encode()).hexdigest()[:16]

    def _download_and_dedupe_images(
        self,
        image_urls: List[str],
        output_dir: Path,
        property_name: str,
    ) -> List[Tuple[Path, str, str, str]]:
        """
        Download images with deduplication.

        Returns: List of (file_path, image_hash, source_method, original_url) tuples

        Deduplication:
        - Within-page: If same hash appears multiple times (e.g. thumbnail + full-res),
          prefer the larger file size
        - Cross-property: If same hash seen on different property, flag as stock content
        """
        downloaded = {}  # hash -> (path, size, source_method, original_url)

        for url in image_urls:
            try:
                # Download
                response = requests.get(url, timeout=10, stream=True)
                if response.status_code != 200:
                    continue

                # Validate size
                content_length = response.headers.get('Content-Length')
                if content_length and int(content_length) < 5000:
                    continue  # Too small (< 5KB)

                # Save to temp file
                filename = f"{self._hash_url(url)}.jpg"
                file_path = output_dir / filename

                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                # Validate is actual image
                if not imghdr.what(file_path):
                    file_path.unlink()
                    continue

                # Get file size
                file_size = file_path.stat().st_size
                if file_size < 5000:
                    file_path.unlink()
                    continue

                # Hash the actual image content
                with open(file_path, 'rb') as f:
                    img_hash = hashlib.md5(f.read()).hexdigest()[:16]

                # Determine source method (heuristic based on URL pattern)
                source_method = self._infer_source_method(url)

                # Within-page deduplication: prefer larger file
                if img_hash in downloaded:
                    existing_path, existing_size, existing_method, existing_url = downloaded[img_hash]
                    if file_size > existing_size:
                        # New image is larger, replace
                        existing_path.unlink()
                        downloaded[img_hash] = (file_path, file_size, source_method, url)
                    else:
                        # Keep existing, delete new
                        file_path.unlink()
                else:
                    downloaded[img_hash] = (file_path, file_size, source_method, url)

                # Cross-property deduplication check
                if img_hash in self._global_image_hashes:
                    first_property = self._global_image_hashes[img_hash]
                    if first_property != property_name:
                        # This image appeared on a different property
                        # Flag as likely stock content (don't count as unique evidence)
                        # For now, still include but mark it
                        # TODO: Could add a flag to evidence result
                        pass
                else:
                    self._global_image_hashes[img_hash] = property_name

            except Exception:
                continue

        # Return list of (path, hash, source_method, original_url)
        return [(path, hash, method, orig_url) for hash, (path, size, method, orig_url) in downloaded.items()]

    def _infer_source_method(self, url: str) -> str:
        """Infer which extraction method likely found this URL."""
        # This is a heuristic - in practice all methods might find the same URL
        # Could be enhanced by tracking source in extract phase
        if 'background' in url.lower():
            return 'background_image'
        elif any(size in url for size in ['@2x', '@3x', '-large', '-full']):
            return 'srcset'
        elif url.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            # Might be <a href> or <img src>
            return 'a_href'  # Assume lightbox link
        else:
            return 'img_src'

    def _yolo_detect(self, image_path: Path) -> Optional[Dict]:
        """
        Run YOLO detection on image.

        Returns dict with:
            - class: str (e.g. 'tv', 'monitor')
            - confidence: float
        """
        try:
            model = YOLO(self.yolo_model_path)
            results = model(str(image_path), conf=self.min_yolo_confidence, verbose=False)

            for result in results:
                if result.boxes:
                    for box in result.boxes:
                        class_id = int(box.cls[0])
                        class_name = model.names[class_id]

                        if class_name in self.target_object_classes:
                            return {
                                'class': class_name,
                                'confidence': float(box.conf[0]),
                            }

            return None

        except Exception:
            return None

    def _vlm_verify(
        self,
        image_path: Path,
        property_name: str,
        yolo_confidence: float,
    ) -> Optional[Dict]:
        """
        Verify YOLO-positive image with VLM using vertical-specific prompt.

        Returns dict with:
            - is_common_area: bool
            - is_target_object: bool
            - device_type: str (optional, vertical-specific)
            - space_type: str (optional, vertical-specific)
            - tv_powered_on: bool (optional)
            - reasoning: str
            - confidence: str (high/medium/low)
        """
        try:
            import base64
            from anthropic import Anthropic

            if not self.anthropic_api_key:
                return None

            client = Anthropic(api_key=self.anthropic_api_key)

            # Read image
            with open(image_path, 'rb') as f:
                img_content = f.read()

            img_b64 = base64.b64encode(img_content).decode('utf-8')

            # Determine media type
            img_format = imghdr.what(None, h=img_content)
            media_type_map = {
                'jpeg': 'image/jpeg',
                'png': 'image/png',
                'gif': 'image/gif',
                'webp': 'image/webp',
            }
            media_type = media_type_map.get(img_format, 'image/jpeg')

            # Format prompt (support both callable and string template)
            if callable(self.vlm_classification_prompt):
                prompt = self.vlm_classification_prompt(property_name, yolo_confidence)
            else:
                prompt = self.vlm_classification_prompt.format(
                    property_name=property_name,
                    yolo_confidence=yolo_confidence,
                )

            # Call VLM
            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=500,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": img_b64,
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        }
                    ]
                }]
            )

            response_text = response.content[0].text.strip()

            # Parse JSON response
            import json

            # Extract JSON (handle markdown code blocks)
            if '```json' in response_text:
                json_start = response_text.find('```json') + 7
                json_end = response_text.find('```', json_start)
                json_text = response_text[json_start:json_end].strip()
            elif '```' in response_text:
                json_start = response_text.find('```') + 3
                json_end = response_text.find('```', json_start)
                json_text = response_text[json_start:json_end].strip()
            else:
                json_text = response_text

            vlm_result = json.loads(json_text)
            return vlm_result

        except Exception:
            return None
