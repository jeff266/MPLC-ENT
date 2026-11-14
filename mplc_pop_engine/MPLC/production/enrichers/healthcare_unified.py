#!/usr/bin/env python3
"""
Healthcare PoP Detection - Unified 7-Channel Pipeline

Channels (in order):
1. Public/Private Detection (instant, FREE)
2A. State Procurement DB (public only, FREE)
2B. Federal Contracts API (all hospitals, $0.001)
3. YouTube Video + YOLO + VLM ($0.015-0.025, assisted living only)
4. Hospital Image Search + VLM ($0.02-0.03, 75% hit rate on private hospitals)
5-7. Future channels (stubbed)

Early exit: Stop on first PROSPECT (cost optimization)
Cost tracking: Cumulative across all API calls
Evidence schema: Compliant with CLAUDE.md requirements
"""

import os
import sys
import json
import sqlite3
import requests
import base64
import tempfile
try:
    import imghdr  # Python < 3.13
except ModuleNotFoundError:
    # Removed in Python 3.13 (PEP 594) -- see image_sniff.py for why/what
    import image_sniff as imghdr
import time
import signal
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from contextlib import contextmanager

# Third-party dependencies
import cv2
from ultralytics import YOLO
from anthropic import Anthropic

# Import generic website image channel (2026-11-13, Jeff: "wire
# WebsiteImageEvidenceChannel into Healthcare and Corporate the same way MDU
# uses it"). Same guarded-import pattern as mdu_unified.py: try same directory
# first (droplet deployment, flattened), then nested repo structure (local dev).
GENERIC_IMAGE_CHANNEL_AVAILABLE = False
for _path in (Path(__file__).parent, Path(__file__).parent.parent / 'channels'):
    sys.path.insert(0, str(_path))
    try:
        from website_image_channel import WebsiteImageEvidenceChannel
        GENERIC_IMAGE_CHANNEL_AVAILABLE = True
        break
    except ImportError:
        continue
if not GENERIC_IMAGE_CHANNEL_AVAILABLE:
    print(f"Warning: Generic image channel not available (tried: {Path(__file__).parent}, {Path(__file__).parent.parent / 'channels'})")

# Import normalization layer
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core"))
try:
    from data_normalization import create_normalizer
    NORMALIZATION_AVAILABLE = True
except ImportError:
    NORMALIZATION_AVAILABLE = False
    print("⚠️  WARNING: Normalization layer not available - using raw account names")

# Import shared entity verification module
sys.path.insert(0, str(Path(__file__).parent.parent / "workers"))
try:
    from entity_verification import verify_entity_match as shared_verify_entity_match
    ENTITY_VERIFICATION_AVAILABLE = True
except ImportError:
    ENTITY_VERIFICATION_AVAILABLE = False
    print("⚠️  WARNING: Shared entity verification not available - using fallback")

# API Keys
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
try:
    import config
    SERPER_API_KEY = config.SERPER_API_KEY
    ANTHROPIC_API_KEY = config.ANTHROPIC_API_KEY
except ImportError:
    SERPER_API_KEY = os.getenv("SERPER_API_KEY")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# USASpending.gov API
USASPENDING_API = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# AV keywords for contract filtering
AV_KEYWORDS = [
    "television", "tv", "iptv", "cable tv", "satellite tv",
    "patient entertainment", "bedside entertainment",
    "lobby tv", "waiting room tv", "cafeteria tv",
    "display", "monitor", "screen",
    "cable service", "satellite service"
]


class HealthcareEnricherUnified:
    """Unified healthcare PoP detection across 7 channels."""

    def __init__(self, enable_youtube: bool = True, enable_image_search: bool = True):
        """
        Initialize Healthcare enricher.

        Args:
            enable_youtube: Enable YouTube video channel (default: True)
                          Set to False to skip expensive video processing
            enable_image_search: Enable generic image search channel (default: True)
        """
        self.rapidapi_key = RAPIDAPI_KEY
        self.serper_key = SERPER_API_KEY
        self.anthropic_key = ANTHROPIC_API_KEY

        # Channel configuration (for fast runs, disable expensive channels)
        self.enable_youtube = enable_youtube
        self.enable_image_search = enable_image_search

        if not self.serper_key:
            raise ValueError("SERPER_API_KEY not set")
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        # Find procurement DB (multiple possible locations)
        self.procurement_db_path = self._find_procurement_db()

        # Find YOLO model
        self.yolo_model_path = self._find_yolo_model()

        # Initialize normalizer for clean account names
        if NORMALIZATION_AVAILABLE:
            self.normalizer = create_normalizer("healthcare")
            print("✅ Normalization layer enabled")
        else:
            self.normalizer = None
            print("⚠️  Normalization layer disabled - searches will use raw account names")

        # Generic website-image channel (free, entity-certain by construction
        # since it crawls the account's own website rather than searching the
        # open web) -- same pattern as mdu_unified.py's self.image_channel.
        self.image_channel = None
        if GENERIC_IMAGE_CHANNEL_AVAILABLE:
            try:
                self.image_channel = WebsiteImageEvidenceChannel(
                    target_object_classes=['tv', 'monitor'],
                    gallery_page_keywords=[
                        'waiting room', 'waiting area', 'lobby', 'patient',
                        'gallery', 'amenities', 'facility tour', 'about us',
                    ],
                    vlm_classification_prompt=self._healthcare_vlm_prompt,
                    anthropic_api_key=self.anthropic_key,
                    yolo_model_path=self.yolo_model_path,
                    min_yolo_confidence=0.2,
                )
            except Exception as e:
                print(f"Warning: Could not initialize generic image channel: {e}")

        # Log channel configuration
        print(f"📺 YouTube channel: {'ENABLED' if self.enable_youtube else 'DISABLED'}")
        print(f"🖼️  Image search channel: {'ENABLED' if self.enable_image_search else 'DISABLED'}")
        print(f"🌐 Website-image channel: {'ENABLED' if self.image_channel else 'DISABLED'}")

    def _healthcare_vlm_prompt(self, property_name: str, yolo_confidence: float) -> str:
        """VLM prompt for the generic website-image channel, adapted from this
        file's own analyze_image_vlm() prompt (used by Stage 4 / hospital image
        search) but reshaped to the generic channel's field names (is_common_area
        / is_target_object / device_type) so _vlm_verify() can parse it the same
        way it parses MDU's and Corporate's prompts."""
        return f"""Analyze this image for TV/entertainment-screen evidence at a healthcare facility.

Facility: {property_name}
YOLO pre-filter confidence this image contains a TV/monitor-like object: {yolo_confidence:.2f}

Look for TVs in PUBLIC, patient/visitor-accessible communal spaces:
- Waiting room / waiting area
- Public lobby
- Common patient lounge

CRITICAL EXCLUSIONS (must be ruled out):
- Nurses' station or staff-only monitors
- Medical/diagnostic equipment displays (EKG, vitals monitors, imaging screens)
- Patient room TVs (private rooms, not public-facing)
- Digital wayfinding / directory screens
- Black screens (powered off)
- Computer monitors at reception desks

Answer ONLY with valid JSON in exactly this shape:
{{
  "tv_detected": true|false,
  "device_type": "tv"|"monitor"|"projector_screen"|"computer_monitor",
  "tv_location": "waiting_room|lobby|patient_lounge|none",
  "confidence": "high"|"medium"|"low",
  "is_entertainment_tv": true|false,
  "is_common_area": true|false,
  "is_target_object": true|false,
  "tv_powered_on": true|false,
  "reasoning": "Brief explanation"
}}"""

    def _find_procurement_db(self) -> Optional[Path]:
        """Find state procurement database with fallback locations."""
        search_paths = [
            Path(__file__).parent.parent / "dependencies/databases/state_procurement_contracts.db",  # Production structure
            Path("/root/enrichment/dependencies/databases/state_procurement_contracts.db"),  # Droplet production
            Path("/root/enrichment/healthcare/state_procurement_contracts.db"),  # Droplet legacy
            Path(__file__).parent / "verticals/healthcare/state_procurement_contracts.db",
            Path(__file__).parent.parent / "verticals/healthcare/state_procurement_contracts.db",
            Path(__file__).parent / "state_procurement_contracts.db",
        ]
        for path in search_paths:
            if path.exists():
                return path
        return None  # Graceful degradation - skip this channel

    def _find_yolo_model(self) -> str:
        """Find YOLO model with fallback locations."""
        search_paths = [
            Path(__file__).parent.parent / "dependencies/models/yolo11n.pt",  # Production structure
            Path("/root/enrichment/dependencies/models/yolo11n.pt"),  # Droplet production
            Path("/root/enrichment/yolo11n.pt"),  # Droplet legacy
            Path(__file__).parent / "yolo11n.pt",
            Path(__file__).parent.parent / "yolo11n.pt",
        ]
        for path in search_paths:
            if path.exists():
                return str(path)
        return "yolo11n.pt"  # Ultralytics will auto-download if not found

    # ========== STAGE 1: PUBLIC/PRIVATE DETECTION ==========

    def is_confidently_private(self, name: str) -> bool:
        """
        Determine if hospital is CONFIDENTLY private (skip procurement lookup).

        Since procurement lookup is free/local, we run it for everyone except
        facilities that are clearly private chains/corporations. This is a hint,
        not a gate - strict name matching in procurement results prevents false positives.

        Returns True only if confident the facility is private (major chain, LLC, Inc, etc.)
        Returns False for unclear cases (let procurement lookup try and fail gracefully)
        """
        name_lower = name.lower()

        # CONFIDENTLY PRIVATE: Major private chains and corporate markers
        # These are the only facilities we skip procurement for
        private_keywords = [
            'hca healthcare', 'hca ', 'tenet health', 'tenet ',
            'kaiser permanente', 'kaiser ',
            'cedars-sinai', 'mayo clinic',
            'adventist health',
            'catholic health initiatives', 'dignity health',
            'community health systems', 'chs ',
            'lifepoint health', 'universal health services',
            'ascension health', 'trinity health',
            ' llc', ' inc.', ' inc ', ' incorporated',
            ' corporation', ' corp.', ' corp ',
            ' partners healthcare', ' partners health'
        ]

        # Check if name contains any confidently-private markers
        for keyword in private_keywords:
            if keyword in name_lower:
                return True

        return False  # Unknown = try procurement (it's free)

    # ========== STAGE 2A: STATE PROCUREMENT DB ==========

    def search_state_procurement(self, account_name: str, state: str) -> Optional[Dict]:
        """
        Search state procurement database for MPLC-relevant contracts.

        Source: run_healthcare_pipeline.py lines 122-180
        """
        if not self.procurement_db_path or not self.procurement_db_path.exists():
            return None

        # Normalize state name (convert "California" -> "CA")
        state_abbrev = self._normalize_state_name(state)

        try:
            conn = sqlite3.connect(self.procurement_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Extract key terms from account name for fuzzy matching
            # E.g., "UCLA Health" -> match "UCLA", "University of California"
            # "Mayo Clinic" -> match "Mayo"
            name_terms = []
            account_lower = account_name.lower()

            # Extract meaningful terms (skip common words)
            skip_words = {'health', 'hospital', 'medical', 'center', 'system', 'healthcare', 'clinic', 'care'}
            for word in account_name.split():
                if len(word) >= 4 and word.lower() not in skip_words:
                    name_terms.append(word)

            if not name_terms:
                # Fallback to full name if no meaningful terms
                name_terms = [account_name]

            # Build dynamic query with name matching
            query = """
                SELECT * FROM contracts
                WHERE state = ?
                AND (
                    LOWER(contract_description) LIKE '%television%' OR
                    LOWER(contract_description) LIKE '%tv%' OR
                    LOWER(contract_description) LIKE '%iptv%' OR
                    LOWER(contract_description) LIKE '%patient entertainment%' OR
                    LOWER(contract_description) LIKE '%waiting room%' OR
                    LOWER(contract_description) LIKE '%lobby%'
                )
                AND (
                    {}
                )
                AND contract_description NOT LIKE '%surveillance%'
                AND contract_description NOT LIKE '%conferencing%'
                AND contract_description NOT LIKE '%microphone%'
                ORDER BY contract_value DESC
                LIMIT 5
            """

            # Add name matching conditions
            name_conditions = []
            query_params = [state_abbrev]

            for term in name_terms[:3]:  # Limit to 3 terms to avoid too complex query
                name_conditions.append("LOWER(facility_name) LIKE ?")
                name_conditions.append("LOWER(facility_system) LIKE ?")
                query_params.extend([f'%{term.lower()}%', f'%{term.lower()}%'])

            query = query.format(' OR '.join(name_conditions))

            cursor.execute(query, tuple(query_params))
            rows = cursor.fetchall()

            if rows:
                # STRICT NAME MATCHING: Validate that contract facility name actually matches account
                # Since we now run procurement for everyone (not just confidently public),
                # we need strict matching to prevent false positives
                contract = dict(rows[0])
                contract_facility = contract.get('facility_name', '').lower()
                contract_system = contract.get('facility_system', '').lower()

                # Check if at least 60% of account name words appear in contract facility/system
                account_words = set(w.lower() for w in account_name.split() if len(w) >= 3)
                contract_words = set(contract_facility.split()) | set(contract_system.split())

                if account_words and contract_words:
                    match_score = len(account_words & contract_words) / len(account_words)
                    if match_score < 0.6:
                        # Not enough overlap - likely wrong facility
                        conn.close()
                        return None

                conn.close()
                return contract

            conn.close()
            return None

        except Exception as e:
            print(f"  Error searching procurement DB: {e}")
            return None

    # ========== STAGE 2B: FEDERAL CONTRACTS API ==========

    def search_federal_contracts(self, hospital_name: str, state: str = None) -> Optional[Dict]:
        """
        Search USASpending.gov for hospital AV contracts.

        Source: run_healthcare_pipeline.py lines 183-247
        """
        today = datetime.now()
        three_years_ago = today - timedelta(days=1095)

        payload = {
            "filters": {
                "time_period": [{
                    "start_date": three_years_ago.strftime("%Y-%m-%d"),
                    "end_date": today.strftime("%Y-%m-%d")
                }],
                "recipient_search_text": [hospital_name],
            },
            "fields": [
                "Award ID", "Recipient Name", "Award Amount",
                "Description", "Award Type", "Awarding Agency",
                "Start Date", "End Date",
            ],
            "page": 1,
            "limit": 100,
            "sort": "Award Amount",
            "order": "desc"
        }

        try:
            response = requests.post(USASPENDING_API, json=payload, timeout=30)

            if response.status_code != 200:
                return None

            data = response.json()
            results = data.get("results", [])

            # Filter for AV-related contracts
            for contract in results:
                description = contract.get("Description", "").lower()
                if any(keyword in description for keyword in AV_KEYWORDS):
                    return contract

            return None

        except Exception:
            return None

    # ========== STAGE 3: YOUTUBE VIDEO + YOLO + VLM ==========

    def search_youtube_videos(self, facility_name: str, city: str, state: str) -> Optional[List[Dict]]:
        """
        Search YouTube using Serper API (Google Videos).

        Switched from RapidAPI (403 errors) to Serper on 2024-10-28.
        """
        queries = [
            f"{facility_name} {city} {state} facility tour",
            f"{facility_name} {city} tour",
            f"{facility_name} virtual tour",
        ]

        all_videos = []

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
                    print(f"  Serper error {response.status_code}: {response.text[:100]}")
                    continue

                data = response.json()
                videos = data.get("videos", [])

                for video in videos:
                    if not isinstance(video, dict):
                        continue

                    link = video.get("link", "")
                    title = video.get("title", "")

                    if not link or not title:
                        continue

                    # Filter for YouTube videos only
                    if "youtube.com/watch" not in link and "youtu.be/" not in link:
                        continue

                    # Extract video ID from YouTube URL
                    video_id = None
                    if "youtube.com/watch?v=" in link:
                        video_id = link.split("watch?v=")[1].split("&")[0]
                    elif "youtu.be/" in link:
                        video_id = link.split("youtu.be/")[1].split("?")[0]

                    if not video_id:
                        continue

                    title_lower = title.lower()
                    if any(kw in title_lower for kw in ["tour", "virtual", "facility", "hospital", "welcome", "inside"]):
                        all_videos.append({
                            "video_id": video_id,
                            "title": title,
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "channel_title": video.get("channel", ""),
                        })

                if all_videos:
                    break

            except Exception as e:
                print(f"  YouTube search error: {e}")
                continue

        return all_videos[:3] if all_videos else None

    @contextmanager
    def _timeout(self, seconds):
        """Context manager for timeout using signal.alarm (Unix-only)."""
        def timeout_handler(signum, frame):
            raise TimeoutError(f"Exceeded {seconds}s timeout")

        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    def download_video(self, video_url: str, output_dir: Path) -> tuple[Optional[Path], Optional[str]]:
        """
        Download YouTube video using RapidAPI YouTube Download service.

        Uses paid API to bypass all bot detection. Cost: ~$0.0003 per video.
        Switched from Playwright (DASH fragments) to RapidAPI on 2024-10-28.
        """
        try:
            # Extract video ID from URL
            video_id = None
            if "youtube.com/watch?v=" in video_url:
                video_id = video_url.split("watch?v=")[1].split("&")[0]
            elif "youtu.be/" in video_url:
                video_id = video_url.split("youtu.be/")[1].split("?")[0]

            if not video_id:
                return None, "Could not extract video ID"

            output_file = output_dir / f"{video_id}.mp4"

            # Call RapidAPI YouTube Download API
            api_url = "https://youtube-info-download-api.p.rapidapi.com/ajax/download.php"
            headers = {
                "X-RapidAPI-Key": self.rapidapi_key,
                "X-RapidAPI-Host": "youtube-info-download-api.p.rapidapi.com",
                "accept": "application/json"
            }
            params = {
                "url": video_url,
                "format": "720",  # 720p MP4
                "max_duration": 30,  # Reject videos >30 minutes
                "add_info": "1"  # Get video metadata
            }

            # Step 1: Initiate download
            response = requests.get(api_url, headers=headers, params=params, timeout=60)

            if response.status_code != 200:
                error_msg = response.text[:100] if response.text else f"API error {response.status_code}"
                return None, f"RapidAPI: {error_msg}"

            result = response.json()

            if not result.get('success'):
                error = result.get('error') or result.get('text') or 'Unknown error'
                return None, f"RapidAPI: {error[:100]}"

            # Step 2: Poll progress until download URL is ready
            task_id = result.get('id')
            progress_url = result.get('progress_url')

            if not task_id or not progress_url:
                return None, f"RapidAPI: No task ID in response: {str(result)[:100]}"

            # Poll for up to 60 seconds
            download_url = None
            max_attempts = 30
            for attempt in range(max_attempts):
                time.sleep(2)  # Wait 2 seconds between polls

                progress_response = requests.get(progress_url, timeout=30)
                if progress_response.status_code != 200:
                    continue

                progress_data = progress_response.json()

                # Check if download URL is ready
                download_url = progress_data.get('download_url') or progress_data.get('url')
                if download_url:
                    break

                # Check for errors
                if progress_data.get('error'):
                    return None, f"RapidAPI: {progress_data['error'][:100]}"

            if not download_url:
                return None, "RapidAPI: Timeout waiting for download URL"

            # Download the video file
            video_response = requests.get(download_url, timeout=90, stream=True)

            if video_response.status_code != 200:
                return None, f"RapidAPI: Download failed {video_response.status_code}"

            # Save video file
            with open(output_file, 'wb') as f:
                for chunk in video_response.iter_content(chunk_size=8192):
                    f.write(chunk)

            if output_file.exists() and output_file.stat().st_size > 0:
                return output_file, None
            else:
                return None, "Downloaded file is empty"

        except Exception as e:
            return None, f"RapidAPI: {str(e)[:150]}"

    def extract_frames(self, video_path: Path, interval_seconds: int = 2) -> List[Path]:
        """
        Extract frames from video at regular intervals.

        Source: healthcare_enricher_video_yolo.py lines 227-266
        """
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
        """
        Run YOLO detection on frame to find TVs/monitors.

        Source: healthcare_enricher_video_yolo.py lines 268-293
        """
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

    def analyze_frame_vlm(self, frame_path: Path, facility_name: str, video_title: str) -> Optional[Dict]:
        """
        Analyze YOLO-positive frame with VLM for TV evidence.

        Source: healthcare_enricher_video_yolo.py lines 295-370
        """
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

            prompt = f"""Analyze this healthcare facility video frame for TV evidence.

Facility: {facility_name}
Video: {video_title}

Look for TVs in common areas (lobby, waiting room, cafeteria).
Exclude: Patient rooms, nurse stations, medical equipment displays.

Answer ONLY with valid JSON:
{{
  "tv_detected": true|false,
  "tv_location": "lobby|waiting_room|cafeteria|none",
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
            print(f"  VLM analysis error: {e}")
            return None

    def search_and_analyze_videos(self, facility_name: str, city: str, state: str) -> Dict:
        """Process video channel: search + download + YOLO + VLM."""
        total_cost = 0.003  # RapidAPI search cost

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Search YouTube
            videos = self.search_youtube_videos(facility_name, city, state)

            if not videos:
                return {
                    'lead_status': 'no_evidence',
                    'channel': 'none',
                    'cost': total_cost,
                    'reason': 'No facility tour videos found'
                }

            # Process videos
            for video in videos:
                print(f"    Processing video: {video['title'][:50]}...")

                # Download video
                video_path, error = self.download_video(video['url'], tmpdir_path)
                if not video_path:
                    print(f"      Failed: {error}")
                    continue

                # Extract frames
                frames = self.extract_frames(video_path)
                if not frames:
                    continue

                print(f"      Extracted {len(frames)} frames")

                # YOLO scan
                yolo_positive_frames = []
                for frame in frames:
                    detection = self.yolo_detect_tv(frame)
                    if detection:
                        yolo_positive_frames.append(detection)

                print(f"      YOLO detected TV in {len(yolo_positive_frames)} frames")

                # VLM analyze YOLO-positive frames
                for detection in yolo_positive_frames[:3]:
                    analysis = self.analyze_frame_vlm(detection['frame_path'], facility_name, video['title'])

                    if not analysis:
                        continue

                    total_cost += analysis.get('cost', 0.0)

                    # Check for valid TV evidence
                    if analysis['tv_detected'] and \
                       analysis['is_entertainment_tv'] and \
                       analysis['is_common_area'] and \
                       analysis['confidence'] in ['high', 'medium']:

                        # ENTITY VERIFICATION (CRITICAL): Verify this video is actually about this facility
                        # This channel previously had NO entity verification - major source of false positives
                        if not self.verify_entity_match(
                            source_text=f"{video['url']} {video['title']}",
                            facility_name=facility_name,
                            account_website=None  # Not available in this context
                        ):
                            print(f"      Entity mismatch: video '{video['title'][:50]}' does not match '{facility_name}'")
                            continue  # Try next frame/video

                        return {
                            'lead_status': 'qualified',
                            'channel': 'youtube_video_yolo',
                            'evidence_url': video['url'],
                            'video_title': video['title'],
                            'tv_location': analysis.get('tv_location', ''),
                            'confidence': analysis.get('confidence', 'low'),
                            'tv_powered_on': analysis.get('tv_powered_on', False),
                            'reasoning': analysis.get('reasoning', ''),
                            'yolo_confidence': detection['confidence'],
                            'cost': total_cost
                        }

            return {
                'lead_status': 'no_evidence',
                'channel': 'youtube_video_yolo',
                'cost': total_cost,
                'reason': f'No TV evidence in {len(videos)} videos'
            }

    # ========== STAGE 4: HOSPITAL IMAGE SEARCH + VLM ==========
    def is_domain_valid(self, image_url: str, facility_name: str, image_title: str = "", state: str = "") -> tuple[bool, str]:
        """
        Validate that image source is trustworthy and attributable to facility.

        Returns (is_valid, reason)

        REJECTS:
        - Stock photos (Getty Images, Shutterstock)
        - Generic CDNs (Squarespace, Cloudinary, AWS S3)
        - Unverified third-party sites (architecture firms without attribution)
        - Wrong state/location indicators

        ACCEPTS:
        - Facility's own domain
        - Hospital/healthcare system domains
        - Medical architecture firms WITH facility name in title
        - Reputable news sources explicitly naming the facility
        """
        from urllib.parse import urlparse
        import re

        domain = urlparse(image_url).netloc.lower()

        # Remove common subdomains for matching
        domain_base = re.sub(r'^(www\d?\.|media\.|newsroom\.|about\.|blog\.|images\.|static\.)', '', domain)

        # Extract facility name for matching
        facility_clean = facility_name.lower().replace(',', '').replace('.', '').replace('inc', '').replace('llc', '').replace('hospital', '').replace('medical center', '').replace('health system', '').strip()
        facility_words = set(facility_clean.split())

        # 1. REJECT: Stock photo sites
        stock_photo_domains = [
            'gettyimages.com', 'shutterstock.com', 'istockphoto.com',
            'adobestock.com', 'dreamstime.com', 'depositphotos.com'
        ]
        for stock_domain in stock_photo_domains:
            if stock_domain in domain:
                return False, f"Stock photo site ({stock_domain})"

        # 2. REJECT: Generic CDNs (can't verify attribution)
        generic_cdn_domains = [
            'squarespace-cdn.com', 'squarespace.com', 'cloudinary.com',
            'amazonaws.com', 's3.amazonaws.com', 'wixstatic.com',
            'contentstack.io', 'imgix.net', 'cloudfront.net',
            'creativecirclecdn.com', 'files.edl.io'
        ]
        for cdn_domain in generic_cdn_domains:
            if cdn_domain in domain:
                return False, f"Generic CDN ({cdn_domain}) - can't verify attribution"

        # 3. REJECT: Social media CDNs
        social_cdn_domains = ['lookaside.instagram.com', 'lookaside.fbsbx.com', 'scontent.']
        for social_cdn in social_cdn_domains:
            if social_cdn in domain:
                return False, f"Social media CDN"

        # 4. REJECT: CDN platforms without confirmation
        cdn_platforms = ['yelpcdn.com', 'yimg.com']
        for cdn in cdn_platforms:
            if cdn in domain:
                # OK only if facility name is in title
                if image_title and any(word in image_title.lower() for word in facility_words if len(word) > 3):
                    return True, "Third-party CDN with facility name in title"
                return False, f"Third-party CDN ({cdn}) without facility confirmation"

        # 5. ACCEPT: Facility's own domain
        # Check if facility name appears in domain
        for word in facility_words:
            if len(word) > 3 and word in domain_base:
                return True, f"Facility's own domain (matched: {word})"

        # 6. ACCEPT: Healthcare-specific domains
        healthcare_domains = [
            '.health', 'hospital.', 'medical', 'healthcare',
            'surgery', 'clinic', 'wellness', 'rehab'
        ]
        for hc_domain in healthcare_domains:
            if hc_domain in domain:
                # Must also have facility name in domain or title
                for word in facility_words:
                    if len(word) > 3 and (word in domain_base or word in image_title.lower()):
                        return True, f"Healthcare domain with facility match"

        # 7. ACCEPT: Medical architecture firms WITH facility name in title
        medical_architecture_domains = [
            'hksinc.com', 'cannondesign.com', 'perkinswill.com',
            'hdr.com', 'stantec.com', 'aecom.com', 'gensler.com'
        ]
        for arch_domain in medical_architecture_domains:
            if arch_domain in domain:
                # Must have facility name in title to verify it's about this facility
                if image_title and any(word in image_title.lower() for word in facility_words if len(word) > 3):
                    return True, f"Medical architecture firm with facility in title"
                return False, f"Architecture firm without facility confirmation"

        # 8. ACCEPT: Trusted news/business sources
        trusted_news_domains = {
            'bizj.us': 'Business Journals',
            'bizjournals.com': 'Business Journals',
            'healthcaredive.com': 'Healthcare Dive',
            'modernhealthcare.com': 'Modern Healthcare',
            'fiercehealthcare.com': 'Fierce Healthcare',
            'beckershospitalreview.com': 'Beckers Hospital Review',
            'aha.org': 'American Hospital Association',
        }
        for news_domain, news_name in trusted_news_domains.items():
            if news_domain in domain:
                # Must have facility name in title or URL path
                url_lower = image_url.lower()
                title_lower = (image_title or "").lower()
                if any(word in url_lower or word in title_lower for word in facility_words if len(word) > 3):
                    return True, f"Trusted healthcare news source ({news_name})"

        # 9. REJECT: Everything else (can't verify)
        return False, "Unverified third-party domain"

    def is_us_relevant(self, image_url: str, image_title: str, state: str = "", operating_market: str = "United States") -> bool:
        """
        Quick geographic relevance check before calling VLM.

        Returns False if evidence clearly from wrong state/country.
        Prevents "Memorial Hospital - Texas" from matching "Memorial Hospital - Florida"
        """
        if operating_market != "United States":
            return True  # Don't filter non-US accounts

        # International indicators (clearly not US)
        international_indicators = [
            'uk', 'canada', 'australia', 'india', 'china', 'mexico',
            'london', 'toronto', 'sydney', 'mumbai', 'beijing',
            'united kingdom', 'ontario', 'queensland', 'maharashtra'
        ]

        url_lower = image_url.lower()
        title_lower = image_title.lower()

        for indicator in international_indicators:
            if indicator in url_lower or indicator in title_lower:
                return False

        # State mismatch check (if state provided)
        if state:
            # Common state indicators that would show wrong state
            # e.g., if account is in CA, reject images with "texas", "florida", etc.
            us_states = {
                'AL': 'alabama', 'AK': 'alaska', 'AZ': 'arizona', 'AR': 'arkansas',
                'CA': 'california', 'CO': 'colorado', 'CT': 'connecticut', 'DE': 'delaware',
                'FL': 'florida', 'GA': 'georgia', 'HI': 'hawaii', 'ID': 'idaho',
                'IL': 'illinois', 'IN': 'indiana', 'IA': 'iowa', 'KS': 'kansas',
                'KY': 'kentucky', 'LA': 'louisiana', 'ME': 'maine', 'MD': 'maryland',
                'MA': 'massachusetts', 'MI': 'michigan', 'MN': 'minnesota', 'MS': 'mississippi',
                'MO': 'missouri', 'MT': 'montana', 'NE': 'nebraska', 'NV': 'nevada',
                'NH': 'new hampshire', 'NJ': 'new jersey', 'NM': 'new mexico', 'NY': 'new york',
                'NC': 'north carolina', 'ND': 'north dakota', 'OH': 'ohio', 'OK': 'oklahoma',
                'OR': 'oregon', 'PA': 'pennsylvania', 'RI': 'rhode island', 'SC': 'south carolina',
                'SD': 'south dakota', 'TN': 'tennessee', 'TX': 'texas', 'UT': 'utah',
                'VT': 'vermont', 'VA': 'virginia', 'WA': 'washington', 'WV': 'west virginia',
                'WI': 'wisconsin', 'WY': 'wyoming'
            }

            # Get current state name
            current_state_name = us_states.get(state.upper(), state.lower())

            # Check if URL/title explicitly mentions a DIFFERENT state
            for abbrev, state_name in us_states.items():
                if abbrev != state.upper() and state_name != current_state_name:
                    # Look for clear state indicators
                    if f" {state_name} " in title_lower or f"{state_name}." in title_lower:
                        return False
                    if f"/{state_name}/" in url_lower or f"-{state_name}-" in url_lower:
                        return False

        return True

    def search_hospital_images(self, hospital_name: str, state: str = "") -> Optional[List[Dict]]:
        """
        Search for hospital waiting area/lobby images via Serper API.

        Proven in exploration: 75% PROSPECT hit rate on private hospitals.
        Sources: Hospital domains, medical architecture firms, healthcare news.
        """
        # Include state in queries for better geographic targeting
        if state:
            queries = [
                f"{hospital_name} {state} waiting area",
                f"{hospital_name} {state} lobby",
                f"{hospital_name} {state} patient lounge",
            ]
        else:
            queries = [
                f"{hospital_name} waiting area",
                f"{hospital_name} lobby",
                f"{hospital_name} patient lounge",
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
                    print(f"    Serper image API error: {response.status_code}")
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

                # Only try first query that returns results (optimization)
                if images:
                    break

                time.sleep(0.5)  # Rate limiting

            except Exception as e:
                print(f"    Image search error: {e}")
                continue

        return all_images if all_images else None

    def validate_image(self, image_url: str, timeout: int = 10) -> Optional[bytes]:
        """
        Download and validate image before sending to VLM.
        Returns image bytes if valid, None if invalid.

        Validation: size (5KB-5MB), format (jpeg/png/webp), not corrupted.
        """
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(image_url, headers=headers, timeout=timeout, stream=True)

            if response.status_code != 200:
                return None

            content = response.content

            # Check size (skip if too small or too large)
            size_kb = len(content) / 1024
            if size_kb < 5 or size_kb > 5000:
                return None

            # Validate it's actually an image
            img_format = imghdr.what(None, h=content)
            if not img_format or img_format not in ['jpeg', 'jpg', 'png', 'gif', 'webp']:
                return None

            # Try to open with PIL to verify it's not corrupted
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(content))
                img.verify()
            except:
                return None

            return content

        except:
            return None

    def analyze_image_vlm(self, image_content: bytes, hospital_name: str, source: str = "") -> Optional[Dict]:
        """
        Analyze validated image for TV evidence in hospital waiting areas using VLM.

        Returns: {tv_detected, tv_location, confidence, tv_powered_on, reasoning, cost}
        """
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
            client = Anthropic(api_key=self.anthropic_key)

            prompt = f"""Analyze this hospital/healthcare facility image for TV evidence.

Hospital: {hospital_name}
Source: {source}

Look for TVs in PUBLIC PATIENT/VISITOR WAITING AREAS:
- Main lobby waiting area
- Emergency department waiting room
- Outpatient waiting area
- Registration/check-in waiting area
- Family lounge / visitor lounge
- Cafeteria

EXCLUDE (not valid evidence):
- Patient rooms or exam rooms
- Nurse stations or staff areas
- Medical equipment displays
- Conference rooms or administrative offices
- Outdoor/parking areas

Answer ONLY with valid JSON:
{{
  "tv_detected": true|false,
  "tv_location": "lobby|waiting_room|cafeteria|registration|family_lounge|none",
  "confidence": "high|medium|low",
  "is_entertainment_tv": true|false,
  "is_public_waiting_area": true|false,
  "tv_powered_on": true|false,
  "reasoning": "Brief explanation of what you see"
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

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1].replace("json", "").strip()

            result = json.loads(text)

            # Calculate cost
            cost = (response.usage.input_tokens / 1_000_000 * 3.00) + \
                   (response.usage.output_tokens / 1_000_000 * 15.00)

            result['cost'] = cost
            return result

        except Exception as e:
            print(f"  VLM image analysis error: {e}")
            return None

    def search_and_analyze_images(self, hospital_name: str, state: str = "", operating_market: str = "United States") -> Dict:
        """Process image channel: search + domain validation + VLM."""
        total_cost = 0.001  # Serper search cost

        # Search for hospital images
        images = self.search_hospital_images(hospital_name, state)

        if not images:
            return {
                'lead_status': 'no_evidence',
                'channel': 'none',
                'cost': total_cost,
                'reason': 'No hospital images found'
            }

        # Process images (cap at 10 to control costs)
        images_analyzed = 0
        images_failed = 0

        for img in images[:10]:
            if not img.get('url'):
                continue

            # Step 1: Domain validation (attribution check)
            is_valid_domain, domain_reason = self.is_domain_valid(
                img['url'],
                hospital_name,
                img.get('title', ''),
                state
            )
            if not is_valid_domain:
                images_failed += 1
                continue

            # Step 2: Geographic relevance check
            if not self.is_us_relevant(img['url'], img.get('title', ''), state, operating_market):
                images_failed += 1
                continue

            # Step 3: Validate image (size, format, not corrupted)
            image_content = self.validate_image(img['url'])
            if not image_content:
                images_failed += 1
                continue

            images_analyzed += 1

            # VLM analysis
            analysis = self.analyze_image_vlm(image_content, hospital_name, img.get('source', ''))

            if not analysis:
                continue

            total_cost += analysis.get('cost', 0.0)

            # Check for valid TV evidence
            if analysis.get('tv_detected') and \
               analysis.get('is_entertainment_tv') and \
               analysis.get('is_public_waiting_area') and \
               analysis.get('confidence') in ['high', 'medium']:

                return {
                    'lead_status': 'qualified',
                    'channel': 'hospital_image_search',
                    'evidence_url': img.get('source', img.get('url')),
                    'source_url': img.get('source', img.get('url')),
                    'tv_location': analysis.get('tv_location', ''),
                    'confidence': analysis.get('confidence', 'low'),
                    'tv_powered_on': analysis.get('tv_powered_on', False),
                    'reasoning': analysis.get('reasoning', ''),
                    'cost': total_cost
                }

        return {
            'lead_status': 'no_evidence',
            'channel': 'hospital_image_search',
            'cost': total_cost,
            'reason': f'No TV evidence in {images_analyzed} images analyzed ({images_failed} filtered)'
        }

    # ========== STAGE 5: PEDIATRIC WAITING AREA DETECTION (PATH B) ==========

    def extract_domain(self, url: str) -> Optional[str]:
        """
        Extract base domain from URL.

        Examples:
            'https://www.example.com/page' -> 'example.com'
            'https://subdomain.example.org' -> 'example.org'
            'www.example.com' -> 'example.com'
        """
        if not url:
            return None

        # Remove protocol
        url = url.lower().strip()
        url = url.replace('https://', '').replace('http://', '').replace('www.', '')

        # Get domain part (before first /)
        domain = url.split('/')[0].split('?')[0]

        # Get base domain (last two parts: example.com)
        parts = domain.split('.')
        if len(parts) >= 2:
            return '.'.join(parts[-2:])

        return domain

    def verify_entity_match(self, source_text: str, facility_name: str,
                          account_website: str = None, threshold: float = 0.85) -> bool:
        """
        Verify that source matches the target facility using shared entity verification module.

        UPDATED: Now uses shared entity_verification.py module instead of ad hoc implementation.

        This prevents false positives like:
        - "Capital Senior Living" matching "Capital Health" (different orgs)
        - "Meridian Senior Living" matching "Meridian Pediatrics" (incompatible types)
        - "LMH Health" (Kansas) matching "Lehigh Valley Health Network" (Pennsylvania)

        Args:
            source_text: Evidence URL, title, or description (combined string for compatibility)
            facility_name: Target facility name
            account_website: Account's own website URL (for domain verification)
            threshold: Name similarity threshold (default 0.85 = 85%, but module uses 0.75)

        Returns:
            True only if strong evidence this is the SAME entity
        """
        if not ENTITY_VERIFICATION_AVAILABLE:
            # Fallback: basic substring check (not recommended for production)
            print("⚠️  WARNING: Using fallback entity verification (shared module not available)")
            if not source_text or not facility_name:
                return False
            facility_clean = facility_name.lower().replace(', inc', '').replace(', llc', '').strip()
            return facility_clean in source_text.lower()

        # Parse source_text to extract URL and title (source_text is often "URL title" combined)
        parts = source_text.split()
        evidence_url = None
        evidence_title = None

        # First part is usually the URL
        if parts:
            potential_url = parts[0]
            if potential_url.startswith('http') or '.' in potential_url:
                evidence_url = potential_url
                # Rest is title
                evidence_title = ' '.join(parts[1:]) if len(parts) > 1 else None
            else:
                # No URL, entire text is title
                evidence_title = source_text

        # Call shared entity verification module
        result = shared_verify_entity_match(
            account_name=facility_name,
            account_website=account_website,
            evidence_url=evidence_url,
            evidence_title=evidence_title,
            evidence_snippet=source_text,  # Pass full text as snippet too
            min_name_match_threshold=threshold if threshold < 0.85 else 0.75,  # Module default is 0.75
            verbose=False
        )

        return result['match']

    def detect_facility_type(self, facility_name: str) -> str:
        """
        Detect if this is a senior living facility vs. other healthcare.

        Returns:
            'senior_living' | 'pediatric' | 'general_healthcare'
        """
        name_lower = facility_name.lower()

        # Senior living indicators
        senior_keywords = [
            'senior living', 'senior care', 'assisted living', 'retirement',
            'memory care', 'nursing home', 'elder care', 'senior housing',
            'independent living', 'continuing care', 'life care',
            'alzheimer', 'dementia care', 'senior community'
        ]

        # Pediatric indicators
        pediatric_keywords = [
            'pediatric', 'pediatrics', 'children', 'kids', 'child',
            'youth', 'adolescent', 'nicu', 'picu'
        ]

        if any(kw in name_lower for kw in senior_keywords):
            return 'senior_living'
        elif any(kw in name_lower for kw in pediatric_keywords):
            return 'pediatric'
        else:
            return 'general_healthcare'

    def search_senior_activity_reviews(self, facility_name: str, state: str) -> Dict:
        """
        Search Google/Yelp reviews for mentions of TV entertainment in common areas.

        Looks for review mentions of:
        - Movie nights, sports viewing events
        - TV in lounge, common area, activity room
        - Entertainment activities with residents
        """
        if not self.serper_key:
            return {
                'lead_status': 'no_evidence',
                'channel': 'senior_activity_reviews',
                'cost': 0.003,
                'reason': 'Serper API key not available',
                'qualifying_path': 'senior_activity'
            }

        # Search for reviews mentioning activities/amenities
        # Don't use quotes - just facility name and location
        query = f'{facility_name} {state} reviews amenities activities'

        try:
            response = requests.post(  # Serper uses POST, not GET
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": self.serper_key,
                    "Content-Type": "application/json"
                },
                json={"q": query, "num": 10},
                timeout=10
            )

            cost = 0.003  # Serper search cost

            if response.status_code != 200:
                print(f"      Serper API error {response.status_code}: {response.text[:100]}")
                return {
                    'lead_status': 'no_evidence',
                    'channel': 'senior_activity_reviews',
                    'cost': cost,
                    'reason': f'Serper API error: {response.status_code}',
                    'qualifying_path': 'senior_activity'
                }

            data = response.json()

            # Check organic results and reviews
            all_text = []

            # Get snippets from search results
            for result in data.get('organic', [])[:10]:
                snippet = result.get('snippet', '')
                all_text.append(snippet)

            # Combine all text
            combined_text = ' '.join(all_text).lower()

            # Keywords indicating TV entertainment in common areas
            tv_keywords = [
                'movie night', 'movies night', 'movie theater', 'theater room',
                'watch movies', 'watching movies', 'watch sports', 'watching sports',
                'tv lounge', 'television lounge', 'tv room', 'television room',
                'tv in the lounge', 'tv in lounge', 'television in the lounge',
                'big screen tv', 'large screen tv', 'big tv',
                'activity room with tv', 'activity room tv',
                'community room tv', 'community room with tv',
                'game room tv', 'game room with tv',
                'super bowl', 'football games', 'sports games',
                'movie viewing', 'film viewing'
            ]

            # Look for matches
            matches = []
            for keyword in tv_keywords:
                if keyword in combined_text:
                    matches.append(keyword)

            if matches:
                # Extract snippet containing the match for evidence
                evidence_snippet = ''
                for text in all_text:
                    text_lower = text.lower()
                    for match in matches:
                        if match in text_lower:
                            evidence_snippet = text
                            break
                    if evidence_snippet:
                        break

                return {
                    'lead_status': 'qualified',
                    'channel': 'senior_activity_reviews',
                    'evidence_url': f'Google search: {query}',
                    'evidence_type': 'review_text_mention',
                    'matched_keywords': ', '.join(matches[:3]),  # First 3 matches
                    'evidence_snippet': evidence_snippet[:200],
                    'confidence': 'high' if len(matches) >= 2 else 'medium',
                    'reasoning': f'Reviews mention TV entertainment activities: {", ".join(matches[:3])}',
                    'cost': cost,
                    'qualifying_path': 'senior_activity'
                }
            else:
                return {
                    'lead_status': 'no_evidence',
                    'channel': 'senior_activity_reviews',
                    'cost': cost,
                    'reason': 'No TV entertainment mentions found in reviews',
                    'qualifying_path': 'senior_activity'
                }

        except Exception as e:
            print(f"      Review search error: {e}")
            return {
                'lead_status': 'no_evidence',
                'channel': 'senior_activity_reviews',
                'cost': 0.003,
                'reason': f'Search error: {str(e)[:100]}',
                'qualifying_path': 'senior_activity'
            }

    def search_senior_activity_images(self, facility_name: str, state: str) -> Optional[List[Dict]]:
        """
        Search for senior living activity/entertainment evidence.

        Looks for:
        - Community rooms, lounges, common areas
        - Activity rooms, recreation areas
        - Amenities, facilities photos
        """
        if not self.serper_key:
            return None

        # Search for facility photos that might show common areas with TVs
        # Use broader queries that are more likely to find facility photos
        queries = [
            f'"{facility_name}" {state} community room lounge',
            f'"{facility_name}" {state} amenities common area',
            f'"{facility_name}" {state} activity room recreation',
            f'"{facility_name}" photos facility tour',
            f'"{facility_name}" {state} resident lounge dining'
        ]

        all_images = []
        for query in queries:
            try:
                response = requests.get(
                    "https://google.serper.dev/images",
                    headers={"X-API-KEY": self.serper_key},
                    json={"q": query, "num": 3},  # Get 3 from each query
                    timeout=10
                )

                if response.status_code == 200:
                    data = response.json()
                    images = data.get('images', [])

                    for img in images:
                        # Avoid duplicates
                        img_url = img.get('imageUrl', '')
                        if not any(existing['url'] == img_url for existing in all_images):
                            all_images.append({
                                'url': img_url,
                                'source': img.get('link', ''),
                                'title': img.get('title', ''),
                                'query': query
                            })

                    # Try first 2 queries, then return what we have
                    if len(all_images) >= 5:
                        break

            except Exception as e:
                print(f"      Serper error: {e}")
                continue

        return all_images[:10] if all_images else None  # Return up to 10 images

    def analyze_senior_activity_vlm(self, image_content: bytes, facility_name: str, source_url: str) -> Optional[Dict]:
        """
        Analyze image for senior living activity/entertainment evidence.

        Looks for:
        - TVs in common areas, lounges, activity rooms
        - Movie night events
        - Residents watching TV together
        - Entertainment areas
        """
        client = Anthropic(api_key=self.anthropic_key)

        # Encode image
        img_b64 = base64.b64encode(image_content).decode('utf-8')
        media_type = f"image/{imghdr.what(None, h=image_content)}"

        prompt = f"""Analyze this image to determine if it shows a senior living facility's common area with a television.

Facility: {facility_name}
Source: {source_url}

REQUIRED CRITERIA:
1. Television must be clearly visible and identifiable
2. TV must be in a COMMUNAL SPACE for residents (not private room):
   - Activity room, game room, recreation room
   - Common lounge, sitting area
   - Community room, gathering space
   - Dining area, great room
3. Environment should indicate SENIOR LIVING/CARE facility:
   - Age-appropriate furniture (comfortable seating, accessible design)
   - Professional/commercial quality space (not residential home)
   - Senior-friendly features (if visible: handrails, accessible layout)

ACCEPT IF:
- TV visible in any communal area where residents gather
- Room appears to be for resident use (entertainment, dining, activities)
- Space is part of senior living/care facility

REJECT IF:
- Private resident room or apartment unit
- Staff-only area (office, nurse station, break room)
- Hospital/medical patient room
- Clearly a hotel, restaurant, or non-healthcare facility
- TV is just a small informational screen or menu board
- No TV visible in the image

Return JSON:
{{
    "is_senior_activity_area": true/false,
    "confidence": "high/medium/low",
    "tv_visible": true/false,
    "space_type": "activity_room/lounge/dining_area/community_room/other",
    "senior_living_indicators": ["list", "of", "observed", "indicators"],
    "reasoning": "brief explanation of why this qualifies or doesn't"
}}"""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=400,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1].replace("json", "").strip()

            result = json.loads(text)

            # Calculate cost
            cost = (response.usage.input_tokens / 1_000_000 * 3.00) + \
                   (response.usage.output_tokens / 1_000_000 * 15.00)

            result['cost'] = cost
            return result

        except Exception as e:
            print(f"  Senior activity VLM analysis error: {e}")
            return None

    def search_and_analyze_senior_activities(self, facility_name: str, state: str, account_website: str = None) -> Dict:
        """
        PATH B (Senior Living): Search for activity/entertainment evidence.

        Looks for movie nights, activity rooms, common areas with TVs.

        Returns:
        - tier: PROSPECT | REJECTED
        - channel: senior_activity_area
        - evidence_url: source URL of confirming image
        - reasoning: VLM explanation
        - cost: total detection cost
        - qualifying_path: 'senior_activity' (for reporting)
        """
        total_cost = 0.003  # Serper image search cost

        # Search for senior activity images
        images = self.search_senior_activity_images(facility_name, state)

        if not images:
            return {
                'lead_status': 'no_evidence',
                'channel': 'senior_activity_area',
                'cost': total_cost,
                'reason': 'No senior activity images found',
                'qualifying_path': 'senior_activity'
            }

        print(f"      Found {len(images)} senior activity candidate images")

        # Analyze images with VLM
        images_analyzed = 0
        images_entity_rejected = 0
        for img in images:
            # ENTITY VERIFICATION
            source_url = img.get('source', '')
            title = img.get('title', '')
            source_text = f"{source_url} {title}"

            if not self.verify_entity_match(source_text, facility_name, account_website=account_website):
                images_entity_rejected += 1
                print(f"      Entity mismatch: '{title}' does not match '{facility_name}'")
                continue

            # Validate image
            image_content = self.validate_image(img['url'])
            if not image_content:
                continue

            images_analyzed += 1

            # VLM analysis
            analysis = self.analyze_senior_activity_vlm(
                image_content,
                facility_name,
                img.get('source', img['url'])
            )

            if not analysis:
                continue

            total_cost += analysis.get('cost', 0.0)

            # Check if senior activity area confirmed
            if analysis.get('is_senior_activity_area') and \
               analysis.get('tv_visible') and \
               analysis.get('confidence') in ['high', 'medium']:

                return {
                    'lead_status': 'qualified',
                    'channel': 'senior_activity_area',
                    'evidence_url': img.get('source', img['url']),
                    'evidence_type': 'senior_activity_area_image',
                    'space_type': analysis.get('space_type', 'activity_room'),
                    'senior_living_indicators': ','.join(analysis.get('senior_living_indicators', [])),
                    'confidence': analysis.get('confidence', 'low'),
                    'reasoning': analysis.get('reasoning', ''),
                    'cost': total_cost,
                    'qualifying_path': 'senior_activity'
                }

        return {
            'lead_status': 'no_evidence',
            'channel': 'senior_activity_area',
            'cost': total_cost,
            'reason': f'No qualifying senior activity areas in {images_analyzed} images analyzed ({images_entity_rejected} entity mismatches filtered)',
            'qualifying_path': 'senior_activity'
        }

    def search_pediatric_images(self, facility_name: str, state: str) -> Optional[List[Dict]]:
        """
        Search for images of pediatric waiting areas using Serper Image Search.

        Returns list of image dicts with 'url', 'source', 'title' fields.
        """
        queries = [
            f"{facility_name} {state} pediatric waiting room",
            f"{facility_name} {state} children waiting area",
            f"{facility_name} pediatric department",
        ]

        all_images = []

        for query in queries:
            try:
                url = "https://google.serper.dev/images"
                headers = {
                    "X-API-KEY": self.serper_key,
                    "Content-Type": "application/json"
                }
                payload = {"q": query, "num": 10}

                response = requests.post(url, headers=headers, json=payload, timeout=30)

                if response.status_code != 200:
                    print(f"  Serper pediatric image search error {response.status_code}")
                    continue

                data = response.json()
                images = data.get("images", [])

                for img in images:
                    if not isinstance(img, dict):
                        continue

                    image_url = img.get("imageUrl", "")
                    source_url = img.get("link", "")
                    title = img.get("title", "")

                    if not image_url:
                        continue

                    all_images.append({
                        "url": image_url,
                        "source": source_url,
                        "title": title
                    })

                if all_images:
                    break  # Stop after first successful query

            except Exception as e:
                print(f"  Pediatric image search error: {e}")
                continue

        return all_images[:5] if all_images else None

    def analyze_pediatric_waiting_area_vlm(self, image_content: bytes, facility_name: str, image_source: str) -> Optional[Dict]:
        """
        Analyze image for pediatric waiting area indicators using VLM.

        Looks for:
        - Pediatric-specific decor (toys, colorful furniture, children's art)
        - Age-appropriate seating (small chairs, play areas)
        - Medical context (healthcare facility, not daycare/school)

        Returns dict with:
        - is_pediatric_waiting_area: bool
        - confidence: high|medium|low
        - pediatric_indicators: list of features seen
        - reasoning: str (what was seen)
        - cost: float (VLM API cost)
        """
        try:
            img_b64 = base64.b64encode(image_content).decode('utf-8')

            img_format = imghdr.what(None, h=image_content)
            if img_format == 'png':
                media_type = "image/png"
            elif img_format in ['jpeg', 'jpg']:
                media_type = "image/jpeg"
            else:
                media_type = "image/jpeg"

            client = Anthropic(api_key=self.anthropic_key)

            prompt = f"""Analyze this image for evidence of a PEDIATRIC WAITING AREA in a healthcare facility.

Facility: {facility_name}
Source: {image_source}

QUALIFYING CRITERIA:
✅ Must be a HEALTHCARE FACILITY waiting area (not daycare, school, or home)
✅ Must have PEDIATRIC-specific indicators:
   - Toys, play areas, children's books
   - Small chairs, child-sized furniture
   - Colorful decor, cartoon characters, children's artwork
   - Age-appropriate entertainment (kids' TV shows, games)

❌ EXCLUDE:
- General hospital lobbies without pediatric features
- Medical exam rooms (not waiting areas)
- Staff areas or administrative spaces
- Schools, daycares, or non-medical facilities
- Adult waiting rooms (even with TV)

Answer ONLY with valid JSON:
{{
  "is_pediatric_waiting_area": true|false,
  "confidence": "high|medium|low",
  "pediatric_indicators": ["list specific features seen"],
  "space_type": "pediatric_waiting_room|general_lobby|exam_room|non_medical|unclear",
  "reasoning": "Detailed explanation of what you see and why it qualifies/disqualifies"
}}"""

            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=400,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1].replace("json", "").strip()

            result = json.loads(text)

            # Calculate cost
            cost = (response.usage.input_tokens / 1_000_000 * 3.00) + \
                   (response.usage.output_tokens / 1_000_000 * 15.00)

            result['cost'] = cost
            return result

        except Exception as e:
            print(f"  Pediatric VLM analysis error: {e}")
            return None

    def search_and_analyze_pediatric(self, facility_name: str, state: str, account_website: str = None) -> Dict:
        """
        PATH B: Search for and verify pediatric waiting area with STRICT entity verification.

        Args:
            facility_name: Target facility name
            state: State abbreviation
            account_website: Account's own website URL (for domain verification)

        Returns:
        - tier: PROSPECT | REJECTED
        - channel: pediatric_waiting_area
        - evidence_url: source URL of confirming image
        - reasoning: VLM explanation
        - cost: total detection cost
        - qualifying_path: 'pediatric_area' (for reporting)
        """
        total_cost = 0.003  # Serper image search cost

        # Search for pediatric images
        images = self.search_pediatric_images(facility_name, state)

        if not images:
            return {
                'lead_status': 'no_evidence',
                'channel': 'pediatric_waiting_area',
                'cost': total_cost,
                'reason': 'No pediatric images found',
                'qualifying_path': 'pediatric_area'
            }

        print(f"      Found {len(images)} pediatric candidate images")

        # Analyze images with VLM
        images_analyzed = 0
        images_entity_rejected = 0
        for img in images:
            # ENTITY VERIFICATION (STRICT): Use domain matching + business type check
            # This prevents false positives like:
            # - "Capital Senior Living" matching "Capital Health" (different orgs)
            # - "Meridian Senior Living" matching "Meridian Pediatrics" (incompatible types)
            source_url = img.get('source', '')
            title = img.get('title', '')
            source_text = f"{source_url} {title}"

            if not self.verify_entity_match(source_text, facility_name, account_website=account_website):
                images_entity_rejected += 1
                print(f"      Entity mismatch: '{title}' does not match '{facility_name}'")
                continue

            # Validate image
            image_content = self.validate_image(img['url'])
            if not image_content:
                continue

            images_analyzed += 1

            # VLM analysis
            analysis = self.analyze_pediatric_waiting_area_vlm(
                image_content,
                facility_name,
                img.get('source', img['url'])
            )

            if not analysis:
                continue

            total_cost += analysis.get('cost', 0.0)

            # Check if pediatric waiting area confirmed
            if analysis.get('is_pediatric_waiting_area') and \
               analysis.get('confidence') in ['high', 'medium']:

                return {
                    'lead_status': 'qualified',
                    'channel': 'pediatric_waiting_area',
                    'evidence_url': img.get('source', img['url']),
                    'evidence_type': 'pediatric_waiting_area_image',
                    'space_type': analysis.get('space_type', 'pediatric_waiting_room'),
                    'pediatric_indicators': ','.join(analysis.get('pediatric_indicators', [])),
                    'confidence': analysis.get('confidence', 'low'),
                    'reasoning': analysis.get('reasoning', ''),
                    'cost': total_cost,
                    'qualifying_path': 'pediatric_area'  # For reporting
                }

        return {
            'lead_status': 'no_evidence',
            'channel': 'pediatric_waiting_area',
            'cost': total_cost,
            'reason': f'No qualifying pediatric waiting areas in {images_analyzed} images analyzed ({images_entity_rejected} entity mismatches filtered)',
            'qualifying_path': 'pediatric_area'
        }

    # ========== DUAL-PATH ORCHESTRATOR ==========

    def enrich_facility_dual_path(self, facility_name: str, city: str, state: str, segment: str = 'UNKNOWN', search_name: str = None, account_website: str = None) -> Dict:
        """
        DUAL-PATH qualification system with facility-type-specific routing.

        Path A (TV Detection): 7-stage waterfall with early exit
        Path B (Facility-specific):
          - Senior Living: Activity/entertainment area detection (movie nights, lounges)
          - Pediatric/Other Healthcare: Pediatric waiting area detection

        Both paths run independently. Results merged with qualifying_path field.

        Args:
            facility_name: Target facility name
            city: City name
            state: State abbreviation
            segment: SB/MM/ENT
            search_name: Simplified name for searches (optional)
            account_website: Account's own website URL for entity verification (optional)

        Returns single dict with:
        - qualifying_path: 'tv_detection' | 'pediatric_area' | 'senior_activity' | 'both'
        - All evidence fields from qualifying path(s)
        """
        # Run Path A (TV Detection waterfall)
        tv_result = self.enrich_facility(facility_name, city, state, segment, search_name, account_website=account_website)

        # Detect facility type to route Path B appropriately
        facility_type = self.detect_facility_type(facility_name)
        print(f"      Facility type detected: {facility_type}")

        # Run Path B (facility-type specific)
        if facility_type == 'senior_living':
            # Senior living: Text mining from reviews for activity mentions
            # (Image search doesn't work - no public facility photos)
            path_b_result = self.search_senior_activity_reviews(facility_name, state)
        else:
            # Pediatric or general healthcare: Look for pediatric waiting areas
            path_b_result = self.search_and_analyze_pediatric(facility_name, state, account_website=account_website)

        # Merge results based on what qualified
        tv_qualified = tv_result.get('lead_status') == 'qualified'
        path_b_qualified = path_b_result.get('lead_status') == 'qualified'

        if tv_qualified and path_b_qualified:
            # Both paths qualify - merge evidence, prioritize TV detection for primary channel
            return {
                **tv_result,
                'qualifying_path': 'both',
                'secondary_evidence_url': path_b_result.get('evidence_url', ''),
                'secondary_reasoning': path_b_result.get('reasoning', ''),
                'secondary_channel': path_b_result.get('channel', ''),
                'secondary_confidence': path_b_result.get('confidence', ''),
                'cost': tv_result.get('cost', 0) + path_b_result.get('cost', 0)
            }
        elif tv_qualified:
            # TV detection only
            return {**tv_result, 'qualifying_path': 'tv_detection'}
        elif path_b_qualified:
            # Path B only (senior activity or pediatric)
            return {**path_b_result, 'vertical': 'healthcare'}
        else:
            # Neither qualified - return combined rejection
            path_b_name = 'Senior Activity' if facility_type == 'senior_living' else 'Pediatric'
            return {
                'lead_status': 'no_evidence',
                'channel': 'none',
                'cost': tv_result.get('cost', 0) + path_b_result.get('cost', 0),
                'vertical': 'healthcare',
                'reason': f"TV detection: {tv_result.get('reason', 'No evidence')}; {path_b_name}: {path_b_result.get('reason', 'No evidence')}"
            }

    def enrich_facility(self, facility_name: str, city: str, state: str, segment: str = 'UNKNOWN', search_name: str = None, account_website: str = None) -> Dict:
        """
        PATH A (TV Detection): 7-stage waterfall with early exit on PROSPECT.

        Args:
            facility_name: Clean name for procurement matching
            city: City name
            state: State code
            segment: SB/MM/ENT
            search_name: Simplified name for YouTube searches (optional, defaults to facility_name)
            account_website: Account's own website URL, used by the generic
                website-image channel (optional; added 2026-11-13)

        Returns evidence-compliant dict with tier, channel, cost, etc.
        """
        total_cost = 0.0
        processing_log = []

        # Use search_name for YouTube if provided, otherwise use facility_name
        if not search_name:
            search_name = facility_name

        try:
            # Stage 1: Public/Private Hint (instant, FREE)
            # This is a hint, not a gate - we query procurement for everyone except confidently private
            is_confidently_private = self.is_confidently_private(facility_name)
            processing_log.append(f"Stage 1: Confidently Private={is_confidently_private}")

            # Stage 2A: State Procurement DB (FREE, run for all non-confidently-private)
            # Strict name matching in results prevents false positives
            if not is_confidently_private and self.procurement_db_path:
                try:
                    result = self.search_state_procurement(facility_name, state)
                    if result:
                        processing_log.append("Stage 2A: PROSPECT (state procurement)")
                        return {
                            'lead_status': 'qualified',
                            'channel': 'state_procurement',
                            'evidence_url': result.get('source_url', ''),
                            'source_url': result.get('source_url', ''),
                            'evidence_description': result.get('contract_description', '')[:200],
                            'contract_value': result.get('contract_value', 0),
                            'confidence': 'high',
                            'vlm_confidence': 'high',
                            'cost': total_cost,
                            'vertical': 'healthcare',
                            'processing_log': processing_log
                        }
                    else:
                        processing_log.append("Stage 2A: No procurement match")
                except Exception as e:
                    processing_log.append(f"Stage 2A: Error - {str(e)[:50]}")

            # Stage 2B: Federal Contracts API (all hospitals, $0.001)
            try:
                result = self.search_federal_contracts(facility_name, state)
                total_cost += 0.001

                if result:
                    processing_log.append("Stage 2B: PROSPECT (federal contracts)")
                    return {
                        'lead_status': 'qualified',
                        'channel': 'federal_contracts',
                        'evidence_url': result.get('Award ID', ''),
                        'source_url': f"https://www.usaspending.gov/award/{result.get('Award ID', '')}",
                        'evidence_description': result.get('Description', '')[:200],
                        'contract_value': result.get('Award Amount', 0),
                        'confidence': 'high',
                        'vlm_confidence': 'high',
                        'cost': total_cost,
                        'vertical': 'healthcare',
                        'processing_log': processing_log
                    }
                else:
                    processing_log.append("Stage 2B: No federal contracts found")

            except Exception as e:
                processing_log.append(f"Stage 2B: Error - {str(e)[:50]}")
                total_cost += 0.001  # Still count API call

            # Stage 2C: Website images (generic, free, entity-certain) -- 2026-11-13.
            # Placed before the paid YouTube/image-search stages per the
            # free-before-paid waterfall principle: crawling the account's OWN
            # site means there's no entity-attribution ambiguity to begin with,
            # unlike a YouTube/Serper search that can surface an unrelated
            # same-named facility's videos or images.
            if self.image_channel and account_website:
                try:
                    temp_dir = Path("/tmp/healthcare_enrichment") / facility_name.replace(" ", "_").replace("/", "_")
                    temp_dir.mkdir(parents=True, exist_ok=True)

                    image_result = self.image_channel.search_evidence(
                        property_name=facility_name,
                        website_url=account_website,
                        temp_dir=temp_dir,
                    )
                    total_cost += image_result.get('cost', 0.0)

                    # NOTE: search_evidence() returns 'tier': 'PROSPECT' on success,
                    # never a 'lead_status' key -- confirmed 2026-11-13 after finding
                    # mdu_unified.py had checked the wrong key and so had silently
                    # never fired this channel in production. Correct key from the start.
                    if image_result.get('tier') == 'PROSPECT':
                        evidence = image_result['evidence']
                        processing_log.append("Stage 2C: PROSPECT (website images)")
                        return {
                            'lead_status': 'qualified',
                            'channel': 'website_images',
                            'evidence_url': evidence.url,
                            'source_url': evidence.url,
                            'tv_location': evidence.vlm_result.get('tv_location', 'unknown'),
                            'confidence': evidence.vlm_result.get('confidence', 'medium'),
                            'vlm_confidence': evidence.vlm_result.get('confidence', 'medium'),
                            'tv_powered_on': evidence.vlm_result.get('tv_powered_on', False),
                            'reasoning': evidence.vlm_result.get('reasoning', ''),
                            'cost': total_cost,
                            'vertical': 'healthcare',
                            'processing_log': processing_log,
                        }
                    else:
                        processing_log.append(
                            f"Stage 2C: {image_result.get('rejection_reason', 'No images found')} "
                            f"({image_result.get('images_found', 0)} images, {image_result.get('images_analyzed', 0)} analyzed)"
                        )
                except Exception as e:
                    processing_log.append(f"Stage 2C: Error - {str(e)[:50]}")
            else:
                processing_log.append("Stage 2C: SKIPPED (no image channel or no account_website)")

            # Stage 3: YouTube Video + YOLO + VLM ($0.015-0.025, assisted living only)
            if self.enable_youtube:
                try:
                    # Use search_name for YouTube queries (cleaner, better matches)
                    video_result = self.search_and_analyze_videos(search_name, city, state)
                    total_cost += video_result.get('cost', 0.0)

                    # FIX (2026-11-13): search_and_analyze_videos() only ever sets
                    # 'lead_status' (never 'tier') -- the old `video_result['tier']`
                    # check KeyError'd on every call since this file's first commit
                    # (91f4863), silently swallowed by this stage's own except block.
                    # Stage 3 could never return a PROSPECT in production until now.
                    if video_result.get('lead_status') == 'qualified':
                        processing_log.append("Stage 3: PROSPECT (video)")
                        return {**video_result, 'cost': total_cost, 'processing_log': processing_log, 'vertical': 'healthcare'}
                    else:
                        processing_log.append(f"Stage 3: {video_result.get('reason', 'No evidence')}")

                except Exception as e:
                    processing_log.append(f"Stage 3: Error - {str(e)[:50]}")
            else:
                processing_log.append("Stage 3: SKIPPED (YouTube disabled for this run)")

            # Stage 4: Hospital Image Search + VLM ($0.02-0.03, 75% hit rate on private hospitals)
            if self.enable_image_search:
                try:
                    image_result = self.search_and_analyze_images(facility_name, state=state, operating_market="United States")
                    total_cost += image_result.get('cost', 0.0)

                    # FIX (2026-11-13): same bug as Stage 3 above -- search_and_
                    # analyze_images() only ever sets 'lead_status', never 'tier'.
                    if image_result.get('lead_status') == 'qualified':
                        processing_log.append("Stage 4: PROSPECT (hospital images)")
                        return {**image_result, 'cost': total_cost, 'processing_log': processing_log, 'vertical': 'healthcare'}
                    else:
                        processing_log.append(f"Stage 4: {image_result.get('reason', 'No evidence')}")

                except Exception as e:
                    processing_log.append(f"Stage 4: Error - {str(e)[:50]}")
            else:
                processing_log.append("Stage 4: SKIPPED (Image search disabled for this run)")

            # Stages 5-7: Future channels (STUB)
            processing_log.append("Stages 5-7: Not implemented")

            # No evidence found
            return {
                'lead_status': 'no_evidence',
                'channel': 'none',
                'evidence_url': '',
                'confidence': 'none',
                'cost': total_cost,
                'vertical': 'healthcare',
                'processing_log': processing_log,
                'reason': 'No evidence found across all channels'
            }

        except Exception as e:
            # Catch-all: never let exceptions propagate to unified_worker
            return {
                'lead_status': 'no_evidence',
                'channel': 'error',
                'cost': total_cost,
                'vertical': 'healthcare',
                'error': str(e)[:200],
                'processing_log': processing_log
            }

    # ========== HELPER METHODS ==========

    def _normalize_state_name(self, state: str) -> str:
        """Convert full state name to abbreviation (California -> CA)."""
        STATE_MAPPING = {
            'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR',
            'California': 'CA', 'Colorado': 'CO', 'Connecticut': 'CT',
            'Delaware': 'DE', 'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI',
            'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA',
            'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME',
            'Maryland': 'MD', 'Massachusetts': 'MA', 'Michigan': 'MI',
            'Minnesota': 'MN', 'Mississippi': 'MS', 'Missouri': 'MO',
            'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV',
            'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM',
            'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND',
            'Ohio': 'OH', 'Oklahoma': 'OK', 'Oregon': 'OR',
            'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
            'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT',
            'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA',
            'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY',
            'District of Columbia': 'DC'
        }

        # If already an abbreviation, return as-is
        if len(state) == 2 and state.upper() == state:
            return state.upper()

        # Otherwise, look up in mapping
        return STATE_MAPPING.get(state, state)


# ========== UNIFIED_WORKER INTEGRATION ==========

def process_account(record: Dict) -> Dict:
    """
    Process healthcare account (unified_worker compatible).

    Input record fields (from Salesforce CSV):
    - account_name / clean_name
    - account_city / city
    - account_state / state_abbrev
    - segment (SB/MM/ENT from ROE segmentation)

    Output: {**record, **enrichment_result}

    Channel Configuration (set via environment variables):
    - ENABLE_YOUTUBE=true|false (default: true)
    - ENABLE_IMAGE_SEARCH=true|false (default: true)

    Example usage:
        # Fast ROE run (free channels only)
        export ENABLE_YOUTUBE=false
        export ENABLE_IMAGE_SEARCH=false
        python3 unified_worker.py healthcare batch.csv

        # Full pipeline (all channels)
        export ENABLE_YOUTUBE=true
        export ENABLE_IMAGE_SEARCH=true
        python3 unified_worker.py healthcare batch.csv
    """
    # Read channel configuration from environment (defaults to all enabled)
    enable_youtube = os.getenv('ENABLE_YOUTUBE', 'true').lower() == 'true'
    enable_image_search = os.getenv('ENABLE_IMAGE_SEARCH', 'true').lower() == 'true'

    enricher = HealthcareEnricherUnified(
        enable_youtube=enable_youtube,
        enable_image_search=enable_image_search
    )

    # PRE-FLIGHT SAFETY CHECKS - Filter accounts that should not be enriched
    # These should have been filtered in Salesforce processing, but check again as safety net

    # Check 1: Industry filter (MDU, Hospitality, Retail, Real Estate)
    EXCLUDED_INDUSTRIES = ['Communal Living Facilities', 'Hospitality', 'Retail', 'Real Estate']
    industry = record.get('industry', '').strip()
    if industry in EXCLUDED_INDUSTRIES:
        return {
            **record,
            'lead_status': 'no_evidence',
            'channel': 'none',
            'cost': 0.0,
            'reason': f'Pre-flight filter: Non-healthcare industry ({industry})'
        }

    # Check 2: Account Status filter (Licensed accounts)
    # Note: This requires account_status field to be passed through from Salesforce
    EXCLUDED_STATUSES = ['Licensed', 'Inactive', 'Expired', 'Do Not Market', 'Delete / Duplicate']
    account_status = record.get('account_status', '').strip()
    if account_status in EXCLUDED_STATUSES:
        return {
            **record,
            'lead_status': 'no_evidence',
            'channel': 'none',
            'cost': 0.0,
            'reason': f'Pre-flight filter: Account Status = {account_status}'
        }

    # Normalize account name if normalizer available
    if enricher.normalizer and not record.get('clean_name'):
        try:
            normalized = enricher.normalizer.normalize_batch([record])
            if normalized and len(normalized) > 0:
                norm_data = normalized[0]
                # Use search_name for YouTube searches, clean_name for procurement matching
                record['clean_name'] = norm_data.get('clean_name', record.get('account_name', ''))
                record['search_name'] = norm_data.get('search_name', record.get('account_name', ''))
                record['state_abbrev'] = norm_data.get('state_abbrev', record.get('account_state', ''))
                record['is_public'] = norm_data.get('is_public', False)
                record['normalization_cost'] = norm_data.get('normalization_cost', 0.0)
        except Exception as e:
            print(f"  ⚠️  Normalization failed: {e} - using raw name")
            record['clean_name'] = record.get('account_name', '')
            record['search_name'] = record.get('account_name', '')

    # Extract facility name - handle both 'account_name' and 'Account Name' casing
    facility_name = record.get('clean_name') or record.get('account_name') or record.get('Account Name', '')
    search_name = record.get('search_name') or facility_name  # Use search_name for YouTube
    city = record.get('account_state', '')  # Use full state name for broader search (matches old enricher)
    state = record.get('state_abbrev', record.get('account_state', ''))
    segment = record.get('segment', 'UNKNOWN')
    # Handle both 'website' and 'Website' casing
    website = record.get('website') or record.get('Website', '')  # For entity verification via domain matching

    if not facility_name:
        return {
            **record,
            'lead_status': 'no_evidence',
            'channel': 'none',
            'cost': 0.0,
            'error': 'Missing facility name'
        }

    # Pass both clean_name (for procurement) and search_name (for YouTube)
    # Use DUAL-PATH enrichment (TV detection + Pediatric waiting area)
    # Pass website for STRICT entity verification via domain matching
    result = enricher.enrich_facility_dual_path(
        facility_name, city, state, segment,
        search_name=search_name,
        account_website=website
    )

    # Add normalization cost if present
    if 'normalization_cost' in record:
        result['cost'] = result.get('cost', 0.0) + record['normalization_cost']

    return {**record, **result}
