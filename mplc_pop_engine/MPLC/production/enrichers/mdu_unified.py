#!/usr/bin/env python3
"""
MDU PoP Detection Enricher - Unified with Video Processing

Waterfall (free → paid):
1. Website images (generic channel) → YOLO → VLM
2. Amenity text-mining (FREE fallback)
3. YouTube property tours → RapidAPI download → YOLO → VLM

Uses generic WebsiteImageEvidenceChannel (reusable across verticals).
"""

import os
import json
import requests
import base64
import imghdr
import sys
import time
import cv2
import shutil
from typing import Dict, Optional, List
from pathlib import Path
from anthropic import Anthropic
from ultralytics import YOLO

# Import generic website image channel
channels_path = Path(__file__).parent.parent / 'channels'
sys.path.insert(0, str(channels_path))
try:
    from website_image_channel import WebsiteImageEvidenceChannel
    GENERIC_IMAGE_CHANNEL_AVAILABLE = True
except ImportError as e:
    GENERIC_IMAGE_CHANNEL_AVAILABLE = False
    print(f"Warning: Generic image channel not available - {e}")

# Import text-mining channel
# Path: enrichers/mdu_unified.py -> production -> MPLC -> mplc_pop_engine -> verticals/mdu
text_channel_path = Path(__file__).parent.parent.parent.parent / 'verticals/mdu'
sys.path.insert(0, str(text_channel_path))
try:
    from amenity_text_channel import MDUAmenityTextChannel
    TEXT_CHANNEL_AVAILABLE = True
except ImportError as e:
    TEXT_CHANNEL_AVAILABLE = False
    print(f"Warning: Amenity text channel not available - {e}")

# Load environment variables from .env file (without python-dotenv dependency)
def load_env_file(env_path):
    """Load .env file and set environment variables."""
    if not env_path.exists():
        return
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

# Try loading from multiple locations
for env_path in [Path('/root/.env'), Path.home() / '.env']:
    load_env_file(env_path)

# Also try loading from production config (for local development)
config_env = Path(__file__).parent.parent / 'config' / '.env'
if config_env.exists():
    load_env_file(config_env)

# API Keys (with fallback defaults matching rest of pipeline)
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "REDACTED-ROTATED-SERPER-KEY")
# Get Anthropic key from environment (droplets have it set, local needs it)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    # Try common key names
    ANTHROPIC_API_KEY = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_KEY")


class MDUEnricherUnified:
    """MDU PoP detection with video processing via RapidAPI."""

    def __init__(self):
        self.serper_key = SERPER_API_KEY
        self.anthropic_key = ANTHROPIC_API_KEY
        self.yolo_model_path = self._find_yolo_model()

        # Initialize generic website image channel
        if GENERIC_IMAGE_CHANNEL_AVAILABLE:
            self.image_channel = WebsiteImageEvidenceChannel(
                target_object_classes=['tv', 'monitor'],
                gallery_page_keywords=['gallery', 'amenities', 'photos'],
                vlm_classification_prompt=self._mdu_vlm_prompt,
                anthropic_api_key=self.anthropic_key,
                yolo_model_path=self.yolo_model_path,
                min_yolo_confidence=0.2,
            )
        else:
            self.image_channel = None

        # Initialize text-mining channel
        if TEXT_CHANNEL_AVAILABLE:
            self.text_channel = MDUAmenityTextChannel(anthropic_api_key=self.anthropic_key)
        else:
            self.text_channel = None

    def _mdu_vlm_prompt(self, property_name: str, yolo_confidence: float) -> str:
        """
        MDU-specific VLM prompt for apartment property common areas.
        Used by generic WebsiteImageEvidenceChannel.
        """
        return f"""Analyze this apartment property website image for TV/display evidence.

Property: {property_name}

Look for TVs/displays in COMMON AMENITY AREAS:
- Clubhouse/community room
- Fitness center/gym
- Pool area/lounge
- Lobby/leasing office public areas
- Business center
- Theater room (may have projector+screen instead of TV)

CRITICAL - EXCLUDE:
- Individual apartment units (living rooms, bedrooms, kitchens)
- Model unit tours showing private spaces
- Leasing office staff desks/computers (work monitors)
- Hallways/corridors
- Storage areas

DEVICE TYPES:
- TV/Monitor: Flat-screen display (wall-mounted or on stand)
- Projector+Screen: Theater room setup with projector and projection screen
- Computer Monitor: Desktop workstation screen (leasing office, business center)

Answer ONLY with valid JSON:
{{
  "tv_detected": true|false,
  "device_type": "tv|monitor|projector_screen|computer_monitor|none",
  "tv_location": "clubhouse|fitness_center|pool_area|lobby|theater_room|business_center|none",
  "confidence": "high|medium|low",
  "is_entertainment_tv": true|false,
  "is_common_area": true|false,
  "is_target_object": true|false,
  "tv_powered_on": true|false,
  "reasoning": "Brief explanation"
}}"""

    def _find_yolo_model(self) -> Path:
        """Find YOLO model in standard locations."""
        search_paths = [
            Path(__file__).parent.parent / "dependencies/models/yolo11n.pt",
            Path("/root/enrichment/dependencies/models/yolo11n.pt"),
            Path.cwd() / "yolo11n.pt",
        ]

        for path in search_paths:
            if path.exists():
                return path

        raise FileNotFoundError("YOLO model yolo11n.pt not found")

    def cleanup_temp_files(self, temp_dir: Path):
        """
        Delete temporary video files and frames after analysis.
        Called in finally block to ensure cleanup even on errors.
        """
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                print(f"  Cleaned up temp files: {temp_dir}")
        except Exception as e:
            # Log but don't fail enrichment if cleanup fails
            print(f"  WARNING: Failed to cleanup {temp_dir}: {e}")

    def search_youtube_videos(
        self,
        property_name: str,
        city: str,
        state: str
    ) -> Optional[List[Dict]]:
        """Search YouTube for property tour videos using Serper API."""

        queries = [
            f"{property_name} {city} {state} apartment tour",
            f"{property_name} {city} virtual tour amenities",
            f"{property_name} apartment amenities"
        ]

        for query in queries:
            try:
                url = "https://google.serper.dev/videos"
                headers = {
                    "X-API-KEY": self.serper_key,
                    "Content-Type": "application/json"
                }
                payload = {"q": query}

                response = requests.post(url, headers=headers, json=payload, timeout=30)

                if response.status_code != 200:
                    continue

                data = response.json()
                videos = data.get("videos", [])

                results = []
                for video in videos[:5]:  # Top 5 results
                    link = video.get("link", "")

                    # Filter for YouTube only
                    if "youtube.com/watch" not in link and "youtu.be/" not in link:
                        continue

                    title = video.get("title", "").lower()

                    # Filter for property tour keywords
                    if any(kw in title for kw in ["tour", "virtual", "amenities", "apartment", "clubhouse"]):
                        results.append({
                            "url": link,
                            "title": video.get("title", ""),
                            "channel_title": video.get("channel", "")
                        })

                if results:
                    return results

            except Exception as e:
                print(f"Serper search error: {e}")
                continue

        return None

    def download_video(self, video_url: str, output_dir: Path) -> tuple[Optional[Path], Optional[str]]:
        """
        Download YouTube video using RapidAPI YouTube Download service.
        Includes retry logic with exponential backoff for transient failures.
        Cost: ~$0.0003 per video.
        """
        # Extract video ID once (not repeated in retries)
        video_id = None
        if "youtube.com/watch?v=" in video_url:
            video_id = video_url.split("watch?v=")[1].split("&")[0]
        elif "youtu.be/" in video_url:
            video_id = video_url.split("youtu.be/")[1].split("?")[0]

        if not video_id:
            return None, "Could not extract video ID"

        output_file = output_dir / f"{video_id}.mp4"

        # Retry configuration
        max_retries = 3
        base_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                # Log retry attempts
                if attempt > 0:
                    delay = base_delay * (2 ** (attempt - 1))  # 2s, 4s, 8s
                    print(f"        🔄 Retry {attempt}/{max_retries-1} after {delay}s delay...")
                    time.sleep(delay)

                # Step 1: Initiate download
                api_url = "https://youtube-info-download-api.p.rapidapi.com/ajax/download.php"
                headers = {
                    "X-RapidAPI-Key": "REDACTED-ROTATED-RAPIDAPI-KEY",
                    "X-RapidAPI-Host": "youtube-info-download-api.p.rapidapi.com",
                    "accept": "application/json"
                }
                params = {
                    "url": video_url,
                    "format": "480",  # Lower quality for faster download
                    "max_duration": 30,
                    "add_info": "1"
                }

                response = requests.get(api_url, headers=headers, params=params, timeout=60)

                if response.status_code != 200:
                    # Non-transient error, don't retry
                    if response.status_code in [400, 403, 404]:
                        return None, f"RapidAPI: {response.status_code}"
                    # Transient error, retry
                    if attempt < max_retries - 1:
                        continue
                    return None, f"RapidAPI: {response.status_code}"

                result = response.json()

                # Step 2: Poll progress until download URL is ready
                progress_url = result.get('progress_url')

                if not progress_url:
                    return None, "RapidAPI: No progress URL"

                # Poll for up to 60 seconds
                download_url = None
                max_poll_attempts = 30
                for poll_attempt in range(max_poll_attempts):
                    time.sleep(2)
                    progress_response = requests.get(progress_url, timeout=30)
                    progress_data = progress_response.json()

                    download_url = progress_data.get('download_url') or progress_data.get('url')
                    if download_url:
                        break

                    if progress_data.get('error'):
                        error_msg = progress_data['error'][:100]
                        # Some errors are transient, retry
                        if 'timeout' in error_msg.lower() or 'temporary' in error_msg.lower():
                            if attempt < max_retries - 1:
                                break  # Break poll loop, retry entire download
                        return None, f"RapidAPI: {error_msg}"

                if not download_url:
                    # Timeout waiting for download URL - retry
                    if attempt < max_retries - 1:
                        continue
                    return None, "RapidAPI: Timeout waiting for download URL"

                # Download the video file with hard timeout
                video_response = requests.get(download_url, timeout=90, stream=True)

                if video_response.status_code != 200:
                    # Non-transient error
                    if video_response.status_code in [403, 404, 410]:
                        return None, f"RapidAPI: Download failed {video_response.status_code}"
                    # Transient error, retry
                    if attempt < max_retries - 1:
                        continue
                    return None, f"RapidAPI: Download failed {video_response.status_code}"

                # Save video file with hard timeout on total download time
                download_start = time.time()
                max_download_time = 90  # 90 second hard limit
                download_timed_out = False

                with open(output_file, 'wb') as f:
                    for chunk in video_response.iter_content(chunk_size=8192):
                        if time.time() - download_start > max_download_time:
                            download_timed_out = True
                            break  # Break chunk loop, will retry below
                        f.write(chunk)

                # If download timed out, retry
                if download_timed_out:
                    if attempt < max_retries - 1:
                        print(f"        ⏱️  Download timeout after {max_download_time}s")
                        if output_file.exists():
                            output_file.unlink()  # Delete partial file
                        continue  # Will retry with backoff delay
                    return None, f"Download timeout after {max_download_time}s"

                # Check if download completed successfully
                if output_file.exists() and output_file.stat().st_size > 0:
                    return output_file, None
                else:
                    # Empty file - retry
                    if attempt < max_retries - 1:
                        if output_file.exists():
                            output_file.unlink()  # Delete partial file
                        continue
                    return None, "Downloaded file is empty"

            except requests.exceptions.Timeout:
                # Timeout is transient, retry
                if attempt < max_retries - 1:
                    print(f"        ⏱️  Request timeout")
                    continue
                return None, "RapidAPI: Request timeout"

            except requests.exceptions.ConnectionError:
                # Connection error is transient, retry
                if attempt < max_retries - 1:
                    print(f"        🔌 Connection error")
                    continue
                return None, "RapidAPI: Connection error"

            except Exception as e:
                # Unknown error - don't retry
                return None, f"RapidAPI: {str(e)[:150]}"

        # Should never reach here, but just in case
        return None, "RapidAPI: Max retries exceeded"

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

                if saved_count >= 30:  # Limit to 30 frames
                    break

            frame_count += 1

        video.release()
        return frames

    def yolo_detect_tv(self, frame_path: Path) -> Optional[Dict]:
        """Run YOLO detection on frame to find TVs/monitors."""
        try:
            model = YOLO(self.yolo_model_path)
            results = model(str(frame_path), conf=0.20, verbose=False)

            for result in results:
                if result.boxes:
                    for box in result.boxes:
                        class_id = int(box.cls[0])
                        class_name = model.names[class_id]

                        if class_name in ['tv', 'monitor']:
                            return {
                                'class': class_name,
                                'confidence': float(box.conf[0]),
                                'frame_path': frame_path
                            }

            return None

        except Exception as e:
            print(f"  YOLO error: {e}")
            return None

    def analyze_frame_vlm(
        self,
        frame_path: Path,
        property_name: str,
        video_title: str
    ) -> Optional[Dict]:
        """Analyze YOLO-positive frame with VLM for TV evidence."""
        try:
            with open(frame_path, 'rb') as f:
                img_content = f.read()

            img_b64 = base64.b64encode(img_content).decode('utf-8')

            img_format = imghdr.what(None, h=img_content)
            if img_format == 'png':
                media_type = "image/png"
            elif img_format in ['jpeg', 'jpg']:
                media_type = "image/jpeg"
            else:
                media_type = "image/jpeg"

            client = Anthropic(api_key=self.anthropic_key)

            prompt = f"""Analyze this apartment property video frame for TV evidence.

Property: {property_name}
Video: {video_title}

Look for TVs in COMMON AMENITY AREAS:
- Clubhouse/community room
- Fitness center/gym
- Pool area/lounge
- Lobby/leasing office public areas
- Business center
- Theater room

CRITICAL - EXCLUDE:
- Individual apartment units (living rooms, bedrooms)
- Model unit tours
- Leasing office staff desks/computers
- Hallways/corridors
- Storage areas

Answer ONLY with valid JSON:
{{
  "tv_detected": true|false,
  "tv_location": "clubhouse|fitness_center|pool_area|lobby|theater_room|business_center|none",
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
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )

            # Parse VLM response
            text_content = next(
                (block.text for block in response.content if hasattr(block, 'text')),
                None
            )

            if not text_content:
                return None

            # Extract JSON from response
            json_start = text_content.find('{')
            json_end = text_content.rfind('}') + 1

            if json_start == -1 or json_end == 0:
                return None

            result = json.loads(text_content[json_start:json_end])

            # Calculate cost (Sonnet 4.5: $3/MTok input, $15/MTok output)
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost = (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0)

            result['cost'] = cost
            return result

        except Exception as e:
            # Print FULL exception details to expose auth failures
            print(f"  ❌ VLM EXCEPTION: {type(e).__name__}: {str(e)}")
            # Return error dict instead of None to distinguish from genuine rejection
            return {'error': str(e), 'error_type': type(e).__name__}

    def verify_video_entity(
        self,
        video_title: str,
        property_name: str,
        city: str,
        state: str
    ) -> tuple[bool, str]:
        """
        Verify video is for THIS property, not a different property with similar name.

        Returns: (is_valid, rejection_reason)

        Entity verification checks (ALL must pass):
        1. Property name match: video title contains property name (fuzzy/substring)
        2. Location match: video title contains city OR state

        CRITICAL: Both property name AND location are required. City/state alone has
        zero discriminating power for single-market operators (e.g., 34 Rainier properties
        in Austin would all accept any "Austin" video).

        Examples:
        - "Trailhead Apartments in Austin" for "Prospect Point" → REJECT (wrong property)
        - "Heritage Crossing at Reunion Resort" (Florida) for "Heritage Crossing" (Austin) → REJECT (wrong state)
        """
        video_title_lower = video_title.lower()
        property_name_lower = property_name.lower()

        # Check 1: Property name match (required)
        # Extract meaningful words from property name (ignore common words)
        stop_words = {'the', 'at', 'on', 'apartments', 'apartment', 'condos', 'condo', 'villas', 'villa'}
        property_words = [w for w in property_name_lower.split() if w not in stop_words]

        # Require at least one significant word from property name to appear in video title
        # (handles "The Trails" vs "Trails", "Prospect Point Apartments" vs "Prospect Point")
        property_name_match = False
        matched_word = None
        for word in property_words:
            if len(word) >= 4 and word in video_title_lower:  # Min 4 chars to avoid false matches
                property_name_match = True
                matched_word = word
                break

        if not property_name_match:
            return False, f"entity_mismatch_property (property '{property_name}' not found in video title)"

        # Check 2: Location match (city OR state - required)
        location_match = False
        matched_location = None

        if city:
            city_lower = city.lower()
            if city_lower in video_title_lower:
                location_match = True
                matched_location = city

        if not location_match and state:
            state_lower = state.lower()
            # Check for full state name or abbreviation
            if state_lower in video_title_lower or state.upper() in video_title:
                location_match = True
                matched_location = state

        if not location_match:
            return False, f"entity_mismatch_location (expected '{city or state}', not found in video title)"

        # Both checks passed
        return True, ""

    def process_videos(
        self,
        videos: List[Dict],
        property_name: str,
        city: str,
        state: str,
        temp_dir: Path
    ) -> Optional[Dict]:
        """Process YouTube videos to find TV evidence with entity verification."""

        rejection_reasons = []  # Track why videos were rejected

        for i, video in enumerate(videos[:3], 1):  # Process up to 3 videos
            video_url = video['url']
            video_title = video['title']

            print(f"    Processing video: {video_title[:60]}...")

            # Entity verification BEFORE downloading
            is_valid, rejection_reason = self.verify_video_entity(
                video_title,
                property_name,
                city,
                state
            )

            if not is_valid:
                print(f"      Rejected: {rejection_reason}")
                rejection_reasons.append(rejection_reason)
                continue

            # Download video
            video_path, error = self.download_video(video_url, temp_dir)
            if error:
                print(f"      Failed: {error}")
                continue

            # Extract frames
            frames = self.extract_frames(video_path)
            if not frames:
                print(f"      Failed: No frames extracted")
                continue

            print(f"      Extracted {len(frames)} frames")

            # YOLO detection on frames
            tv_frames = []
            for frame in frames:
                detection = self.yolo_detect_tv(frame)
                if detection:
                    tv_frames.append(detection)

            print(f"      YOLO detected TV in {len(tv_frames)} frames")

            if not tv_frames:
                print(f"      ⏭️  No YOLO-positive frames to analyze")
                continue

            # VLM analysis on best frame (highest YOLO confidence)
            best_frame = max(tv_frames, key=lambda x: x['confidence'])

            vlm_result = self.analyze_frame_vlm(
                best_frame['frame_path'],
                property_name,
                video_title
            )

            # Distinguish: VLM failed vs VLM ran but said no
            if vlm_result and 'error' in vlm_result:
                # VLM call failed (auth error, connection error, etc.)
                print(f"      ❌ VLM call FAILED: {vlm_result.get('error_type', 'Unknown')} - {vlm_result.get('error', '')[:100]}")
                continue

            if not vlm_result:
                # VLM returned None (should not happen after error handling change, but defensive)
                print(f"      ⚠️  VLM returned None (unexpected - check logs)")
                continue

            # VLM ran successfully, check results
            if not vlm_result.get('tv_detected'):
                print(f"      ⏭️  VLM ran: No TV detected")
                continue

            if not vlm_result.get('is_common_area'):
                print(f"      ⏭️  VLM ran: Not common area (location: {vlm_result.get('tv_location', 'unknown')})")
                continue

            if not vlm_result.get('is_entertainment_tv'):
                print(f"      ⏭️  VLM ran: Not entertainment TV")
                continue

            # Check if it's a valid PROSPECT
            if (vlm_result.get('tv_detected') and
                vlm_result.get('is_entertainment_tv') and
                vlm_result.get('is_common_area') and
                vlm_result.get('confidence') in ['high', 'medium']):

                print(f"      ✅ VLM confirmed PROSPECT: {vlm_result.get('tv_location', '')} - {vlm_result.get('confidence', '')} confidence")

                return {
                    'lead_status': 'qualified',
                    'channel': 'youtube_video_yolo',
                    'evidence_url': video_url,
                    'video_title': video_title,
                    'tv_location': vlm_result.get('tv_location', ''),
                    'confidence': vlm_result.get('confidence', 'low'),
                    'tv_powered_on': vlm_result.get('tv_powered_on', False),
                    'yolo_confidence': best_frame['confidence'],
                    'reasoning': vlm_result.get('reasoning', ''),
                    'cost': vlm_result.get('cost', 0.0)
                }

        # If we got here, all videos failed
        if rejection_reasons:
            # Return rejection reasons for explicit tracking
            return {
                'lead_status': 'no_evidence',
                'channel': 'youtube_video_yolo',
                'rejection_reasons': rejection_reasons,
                'reason': f"All videos rejected: {', '.join(rejection_reasons[:2])}"  # First 2 reasons
            }

        return None

    def scrape_website_images(self, website_url: str) -> List[str]:
        """
        Scrape property website for amenity/gallery image URLs.

        Returns: List of image URLs
        """
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

        image_urls = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                # Load main property page
                page.goto(website_url, wait_until="networkidle", timeout=30000)
                time.sleep(2)  # Let images load

                # Extract all image URLs from the page
                from urllib.parse import urlparse

                # 1. Check <img> tags
                images = page.locator('img').all()
                for img in images:
                    try:
                        src = img.get_attribute('src')
                        if not src:
                            continue

                        # Skip logos, icons, SVGs
                        if any(skip in src.lower() for skip in ['logo', 'icon', '.svg']):
                            continue

                        # Convert relative URLs to absolute
                        if src.startswith('//'):
                            src = 'https:' + src
                        elif src.startswith('/'):
                            parsed = urlparse(website_url)
                            src = f"{parsed.scheme}://{parsed.netloc}{src}"
                        elif not src.startswith('http'):
                            continue

                        # Only accept image formats
                        if any(ext in src.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                            if src not in image_urls:
                                image_urls.append(src)

                    except Exception as e:
                        continue

                # 2. Check background-image CSS styles
                bg_elements = page.locator('[style*="background-image"]').all()
                for elem in bg_elements:
                    try:
                        style = elem.get_attribute('style')
                        if not style or 'url(' not in style:
                            continue

                        # Extract URL from background-image: url(...)
                        start = style.find('url(') + 4
                        end = style.find(')', start)
                        if end == -1:
                            continue

                        src = style[start:end].strip('\'"')
                        if not src:
                            continue

                        # Skip logos, icons
                        if any(skip in src.lower() for skip in ['logo', 'icon', '.svg']):
                            continue

                        # Convert relative URLs to absolute
                        if src.startswith('//'):
                            src = 'https:' + src
                        elif src.startswith('/'):
                            parsed = urlparse(website_url)
                            src = f"{parsed.scheme}://{parsed.netloc}{src}"
                        elif not src.startswith('http'):
                            continue

                        # Only accept image formats
                        if any(ext in src.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                            if src not in image_urls:
                                image_urls.append(src)

                    except Exception as e:
                        continue

                # 3. Check <a> tags pointing directly to image files
                link_elements = page.locator('a').all()
                for link in link_elements:
                    try:
                        href = link.get_attribute('href')
                        if not href:
                            continue

                        # Skip logos, icons
                        if any(skip in href.lower() for skip in ['logo', 'icon', '.svg']):
                            continue

                        # Convert relative URLs to absolute
                        if href.startswith('//'):
                            href = 'https:' + href
                        elif href.startswith('/'):
                            parsed = urlparse(website_url)
                            href = f"{parsed.scheme}://{parsed.netloc}{href}"
                        elif not href.startswith('http'):
                            continue

                        # Only accept image formats
                        if any(ext in href.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                            if href not in image_urls:
                                image_urls.append(href)

                    except Exception as e:
                        continue

                browser.close()

        except PlaywrightTimeout:
            print(f"    Timeout loading website")
        except Exception as e:
            print(f"    Website scrape error: {type(e).__name__}")

        # Deduplicate and limit
        image_urls = list(dict.fromkeys(image_urls))  # Preserve order, remove dupes
        return image_urls[:20]  # Max 20 images to avoid excessive processing

    def download_image(self, image_url: str, output_dir: Path) -> Optional[Path]:
        """
        Download image from URL.

        Returns: Path to downloaded image, or None if failed
        """
        try:
            # Create filename from URL
            from urllib.parse import urlparse
            parsed = urlparse(image_url)
            filename = Path(parsed.path).name
            if not filename or '.' not in filename:
                filename = f"image_{hash(image_url) % 10000}.jpg"

            output_path = output_dir / filename

            # Download with timeout
            response = requests.get(image_url, timeout=10, stream=True)
            if response.status_code != 200:
                return None

            # Save image
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Verify it's a valid image
            if output_path.stat().st_size == 0:
                output_path.unlink()
                return None

            # Check if it's too small (likely icon/thumbnail)
            if output_path.stat().st_size < 5000:  # 5KB minimum
                output_path.unlink()
                return None

            return output_path

        except Exception as e:
            return None

    def analyze_image_vlm(
        self,
        image_path: Path,
        property_name: str,
        yolo_confidence: float
    ) -> Optional[Dict]:
        """
        Analyze image with VLM for TV evidence in common areas.

        Special handling for projector+screen (theater room) vs TV/monitor.
        """
        try:
            with open(image_path, 'rb') as f:
                img_content = f.read()

            img_b64 = base64.b64encode(img_content).decode('utf-8')

            img_format = imghdr.what(None, h=img_content)
            if img_format == 'png':
                media_type = "image/png"
            elif img_format in ['jpeg', 'jpg']:
                media_type = "image/jpeg"
            else:
                media_type = "image/jpeg"

            client = Anthropic(api_key=self.anthropic_key)

            prompt = f"""Analyze this apartment property website image for TV/display evidence.

Property: {property_name}

Look for TVs/displays in COMMON AMENITY AREAS:
- Clubhouse/community room
- Fitness center/gym
- Pool area/lounge
- Lobby/leasing office public areas
- Business center
- Theater room (may have projector+screen instead of TV)

CRITICAL - EXCLUDE:
- Individual apartment units (living rooms, bedrooms, kitchens)
- Model unit tours showing private spaces
- Leasing office staff desks/computers (work monitors)
- Hallways/corridors
- Storage areas

DEVICE TYPES:
- TV/Monitor: Flat-screen display (wall-mounted or on stand)
- Projector+Screen: Theater room setup with projector and projection screen
- Computer Monitor: Desktop workstation screen (leasing office, business center)

Answer ONLY with valid JSON:
{{
  "tv_detected": true|false,
  "device_type": "tv|monitor|projector_screen|computer_monitor|none",
  "tv_location": "clubhouse|fitness_center|pool_area|lobby|theater_room|business_center|none",
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
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )

            # Parse VLM response
            text_content = next(
                (block.text for block in response.content if hasattr(block, 'text')),
                None
            )

            if not text_content:
                return None

            # Extract JSON from response
            json_start = text_content.find('{')
            json_end = text_content.rfind('}') + 1

            if json_start == -1 or json_end == 0:
                return None

            result = json.loads(text_content[json_start:json_end])

            # Calculate cost (Sonnet 4.5: $3/MTok input, $15/MTok output)
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost = (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0)

            result['cost'] = cost
            result['yolo_confidence'] = yolo_confidence
            return result

        except Exception as e:
            # Print FULL exception details to expose auth failures
            print(f"  ❌ VLM EXCEPTION: {type(e).__name__}: {str(e)}")
            # Return error dict instead of None to distinguish from genuine rejection
            return {'error': str(e), 'error_type': type(e).__name__}

    def process_website_images(
        self,
        image_urls: List[str],
        property_name: str,
        temp_dir: Path
    ) -> Optional[Dict]:
        """
        Process website images to find TV evidence.

        Returns PROSPECT if TV found in common area, None otherwise.
        """
        images_dir = temp_dir / "website_images"
        images_dir.mkdir(exist_ok=True)

        images_analyzed = 0
        images_failed = 0

        for i, image_url in enumerate(image_urls[:20], 1):  # Max 20 images
            # Download image
            image_path = self.download_image(image_url, images_dir)
            if not image_path:
                images_failed += 1
                continue

            # YOLO detection
            detection = self.yolo_detect_tv(image_path)
            if not detection:
                continue  # No TV detected

            images_analyzed += 1
            print(f"      Image {i}: YOLO detected {detection['class']} (conf: {detection['confidence']:.2f})")

            # VLM analysis
            vlm_result = self.analyze_image_vlm(
                image_path,
                property_name,
                detection['confidence']
            )

            # Check for VLM errors
            if vlm_result and 'error' in vlm_result:
                print(f"      ❌ VLM call FAILED: {vlm_result.get('error_type')} - {vlm_result.get('error', '')[:100]}")
                continue

            if not vlm_result:
                print(f"      ⚠️  VLM returned None")
                continue

            # Check device type (tv, monitor, or projector_screen all count as PROSPECT)
            device_type = vlm_result.get('device_type', 'none')

            # Check if it's a valid PROSPECT (TV/monitor/projector in common area)
            if (vlm_result.get('tv_detected') and
                vlm_result.get('is_common_area') and
                vlm_result.get('is_entertainment_tv') and
                device_type in ['tv', 'monitor', 'projector_screen'] and
                vlm_result.get('confidence') in ['high', 'medium']):

                print(f"      ✅ VLM confirmed PROSPECT: {vlm_result.get('tv_location', '')} - {device_type} - {vlm_result.get('confidence', '')} confidence")

                return {
                    'lead_status': 'qualified',
                    'channel': 'website_images',
                    'evidence_url': image_url,
                    'image_path': str(image_path),
                    'tv_location': vlm_result.get('tv_location', ''),
                    'confidence': vlm_result.get('confidence', 'low'),
                    'device_type': device_type,
                    'tv_powered_on': vlm_result.get('tv_powered_on', False),
                    'yolo_confidence': detection['confidence'],
                    'reasoning': vlm_result.get('reasoning', ''),
                    'cost': vlm_result.get('cost', 0.0)
                }

            # VLM rejected
            reason = "No TV detected"
            if not vlm_result.get('tv_detected'):
                reason = "No TV detected"
            elif not vlm_result.get('is_common_area'):
                reason = f"Not common area ({vlm_result.get('tv_location', 'unknown')})"
            elif not vlm_result.get('is_entertainment_tv'):
                reason = "Not entertainment TV (likely computer monitor)"
            elif device_type == 'computer_monitor':
                reason = "Computer monitor (not entertainment TV)"

            print(f"      ⏭️  VLM ran: {reason}")

        # No PROSPECT found
        return None

    def enrich_property(
        self,
        property_name: str,
        city: str,
        state: str,
        website_url: str = ""
    ) -> Dict:
        """
        Enrich MDU property with PoP detection.

        Waterfall (cheapest → most expensive, early exit on first PROSPECT):
        1. Website images (generic channel) → YOLO → VLM (FREE scraping, cheap VLM)
        2. Amenity text-mining (FREE fallback)
        3. YouTube property tours → RapidAPI download → YOLO → VLM (paid downloads)
        """

        # Confirm API key is loaded (print presence, not value)
        if self.anthropic_key:
            print(f"  ✓ ANTHROPIC_API_KEY loaded (length: {len(self.anthropic_key)} chars)")
        else:
            print(f"  ❌ WARNING: ANTHROPIC_API_KEY is empty or not loaded!")

        total_cost = 0.0
        temp_dir = Path("/tmp/mdu_enrichment") / property_name.replace(" ", "_").replace("/", "_")
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Channel 1: Website images (generic channel - cheapest, most reliable)
            if self.image_channel and website_url:
                print(f"  Channel 1: Website images (generic)...")
                image_result = self.image_channel.search_evidence(
                    property_name=property_name,
                    website_url=website_url,
                    temp_dir=temp_dir,
                )

                total_cost += image_result.get('cost', 0.0)

                if image_result.get('lead_status') == 'qualified':
                    evidence = image_result['evidence']
                    return {
                        'lead_status': 'qualified',
                        'channel': 'website_images',
                        'evidence_url': evidence.url,
                        'tv_location': evidence.vlm_result.get('tv_location', 'unknown'),
                        'device_type': evidence.vlm_result.get('device_type', 'unknown'),
                        'confidence': evidence.vlm_result.get('confidence', 'medium'),
                        'yolo_confidence': evidence.yolo_confidence,
                        'reasoning': evidence.vlm_result.get('reasoning', ''),
                        'tv_powered_on': evidence.vlm_result.get('tv_powered_on', False),
                        'cost': total_cost,
                        'source_method': evidence.source_method,
                    }
                else:
                    print(f"    Image channel: {image_result.get('rejection_reason', 'No images found')} ({image_result.get('images_found', 0)} images, {image_result.get('images_analyzed', 0)} analyzed)")

            # Channel 2: Amenity text-mining (FREE fallback)
            if self.text_channel and website_url:
                print(f"  Channel 2: Text-mining amenity descriptions...")
                text_result = self.text_channel.search_amenities(property_name, website_url)

                total_cost += text_result.get('cost', 0.0)

                if text_result.get('found'):
                    evidence = text_result['evidence']
                    return {
                        'lead_status': 'qualified',
                        'channel': 'amenity_text_mining',
                        'evidence_url': evidence.get('SourceURL', website_url),
                        'video_title': '',
                        'tv_location': evidence.get('EvidenceLocation', 'Communal Area'),
                        'confidence': evidence.get('Confidence', 'medium'),
                        'tv_powered_on': True,  # Assume true from text evidence
                        'yolo_confidence': 0.0,  # N/A for text
                        'reasoning': evidence.get('EvidenceQuote', ''),
                        'cost': total_cost
                    }

            # Channel 3: YouTube property tours (paid downloads - last resort)
            print(f"  Channel 3: Searching YouTube for property tours...")
            videos = self.search_youtube_videos(property_name, city, state)

            if videos:
                print(f"    Found {len(videos)} videos")
                result = self.process_videos(videos, property_name, city, state, temp_dir)

                if result and result.get('lead_status') == 'qualified':
                    result['cost'] += total_cost
                    return result
                elif result and result.get('lead_status') == 'no_evidence':
                    # Video channel found videos but all rejected (entity mismatch)
                    total_cost += result.get('cost', 0.0)
                    print(f"    Video channel: {result.get('reason', 'All videos rejected')}")

            # No TV evidence found in any channel
            return {
                'lead_status': 'no_evidence',
                'channel': 'none',
                'evidence_url': '',
                'confidence': 'none',
                'cost': total_cost,
                'reason': 'No TV evidence found in available channels'
            }

        finally:
            # Always clean up temporary files, even if errors occur
            self.cleanup_temp_files(temp_dir)


def process_property(record: dict) -> dict:
    """Process a single MDU property record."""
    try:
        enricher = MDUEnricherUnified()

        property_name = record.get('account_name', record.get('property_name', ''))
        city = record.get('city', '')
        state = record.get('state', '')
        website = record.get('website', '')

        result = enricher.enrich_property(property_name, city, state, website)

        return {**record, **result, 'property_name': property_name}

    except Exception as e:
        property_name = record.get('account_name', record.get('property_name', ''))
        return {
            **record,
            'property_name': property_name,
            'lead_status': 'no_evidence',
            'channel': 'none',
            'evidence_url': '',
            'confidence': 'none',
            'cost': 0.0,
            'error': str(e)
        }
