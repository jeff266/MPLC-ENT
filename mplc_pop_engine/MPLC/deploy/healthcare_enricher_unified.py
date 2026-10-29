#!/usr/bin/env python3
"""
Healthcare PoP Detection - Unified 7-Channel Pipeline

Channels (in order):
1. Public/Private Detection (instant, FREE)
2A. State Procurement DB (public only, FREE)
2B. Federal Contracts API (all hospitals, $0.001)
3. YouTube Video + YOLO + VLM ($0.015-0.025)
4-7. Future channels (stubbed)

Early exit: Stop on first PROSPECT (cost optimization)
Cost tracking: Cumulative across all API calls
Evidence schema: Compliant with CLAUDE.md requirements
"""

import os
import json
import sqlite3
import requests
import base64
import tempfile
import imghdr
import time
import signal
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from contextlib import contextmanager

# Third-party dependencies
import cv2
from ultralytics import YOLO
from pytubefix import YouTube
from anthropic import Anthropic

# API Keys
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
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

    def __init__(self):
        self.rapidapi_key = RAPIDAPI_KEY
        self.anthropic_key = ANTHROPIC_API_KEY

        if not self.rapidapi_key:
            raise ValueError("RAPIDAPI_KEY not set")
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        # Find procurement DB (multiple possible locations)
        self.procurement_db_path = self._find_procurement_db()

        # Find YOLO model
        self.yolo_model_path = self._find_yolo_model()

    def _find_procurement_db(self) -> Optional[Path]:
        """Find state procurement database with fallback locations."""
        search_paths = [
            Path(__file__).parent / "verticals/healthcare/state_procurement_contracts.db",
            Path(__file__).parent.parent / "verticals/healthcare/state_procurement_contracts.db",
            Path("/root/enrichment/healthcare/state_procurement_contracts.db"),
            Path(__file__).parent / "state_procurement_contracts.db",
        ]
        for path in search_paths:
            if path.exists():
                return path
        return None  # Graceful degradation - skip this channel

    def _find_yolo_model(self) -> str:
        """Find YOLO model with fallback locations."""
        search_paths = [
            Path(__file__).parent / "yolo11n.pt",
            Path(__file__).parent.parent / "yolo11n.pt",
            Path("/root/enrichment/yolo11n.pt"),
        ]
        for path in search_paths:
            if path.exists():
                return str(path)
        return "yolo11n.pt"  # Ultralytics will auto-download if not found

    # ========== STAGE 1: PUBLIC/PRIVATE DETECTION ==========

    def is_public_hospital(self, name: str) -> bool:
        """
        Determine if hospital is public (can use procurement contracts).

        Source: run_healthcare_pipeline.py lines 54-88
        """
        name_lower = name.lower()

        # Public ownership indicators
        public_keywords = [
            'county', 'state', 'municipal', 'district', 'regional', 'public',
            'university', 'uc ', 'suny', 'ut ', 'cuny',
            'va ', 'veterans', 'military', 'naval',
            'nyc h+h', 'health and hospitals corporation',
            'city of', 'town of'
        ]

        # Private ownership indicators (override public)
        private_keywords = [
            'hca', 'tenet', 'kaiser', 'cedars-sinai', 'mayo clinic',
            'llc', ' inc', 'corporation', 'partners', 'adventist',
            'baptist health', 'catholic health', 'community health systems'
        ]

        # Check private first (more specific)
        for keyword in private_keywords:
            if keyword in name_lower:
                return False

        # Then check public
        for keyword in public_keywords:
            if keyword in name_lower:
                return True

        return False  # Default to private if unclear

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
                AND contract_description NOT LIKE '%surveillance%'
                AND contract_description NOT LIKE '%conferencing%'
                AND contract_description NOT LIKE '%microphone%'
                ORDER BY contract_value DESC
                LIMIT 5
            """

            cursor.execute(query, (state_abbrev,))
            rows = cursor.fetchall()

            if rows:
                contract = dict(rows[0])
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
        Search YouTube using RapidAPI.

        Source: healthcare_enricher_video_yolo.py lines 62-129
        """
        queries = [
            f"{facility_name} {city} {state} facility tour",
            f"{facility_name} {city} tour",
            f"{facility_name} virtual tour",
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
                    if any(kw in title_lower for kw in ["tour", "virtual", "facility", "hospital", "welcome", "inside"]):
                        all_videos.append({
                            "video_id": video_id,
                            "title": title,
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "channel_title": item.get("channelTitle", ""),
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
        Download YouTube video with timeout and pytube fallback.

        Source: healthcare_enricher_video_yolo.py lines 131-226
        """
        max_retries = 2
        for attempt in range(max_retries):
            try:
                with self._timeout(60):
                    yt = YouTube(video_url)
                    stream = yt.streams.filter(file_extension='mp4', only_video=True).order_by('resolution').first()

                    if not stream:
                        stream = yt.streams.filter(file_extension='mp4').first()

                    if not stream:
                        return None, "No suitable video stream found"

                    output_file = stream.download(output_path=str(output_dir), filename=f"{yt.video_id}.mp4")
                    return Path(output_file), None

            except TimeoutError:
                break
            except Exception as e:
                if '503' in str(e) and attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 5)
                    continue
                else:
                    break

        # Fallback to pytube (if installed)
        try:
            from pytube import YouTube as PyTubeYouTube

            with self._timeout(60):
                yt = PyTubeYouTube(video_url)
                stream = yt.streams.filter(file_extension='mp4', only_video=True).order_by('resolution').first()

                if not stream:
                    stream = yt.streams.filter(file_extension='mp4').first()

                if not stream:
                    return None, "pytube: No suitable stream"

                output_file = stream.download(output_path=str(output_dir), filename=f"{yt.video_id}.mp4")
                return Path(output_file), None

        except ImportError:
            return None, "pytube: Module not installed"
        except Exception as e:
            return None, f"pytube: {str(e)[:100]}"

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
                    'tier': 'REJECTED',
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

                        return {
                            'tier': 'PROSPECT',
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
                'tier': 'REJECTED',
                'channel': 'youtube_video_yolo',
                'cost': total_cost,
                'reason': f'No TV evidence in {len(videos)} videos'
            }

    # ========== WATERFALL ORCHESTRATOR ==========

    def enrich_facility(self, facility_name: str, city: str, state: str, segment: str = 'UNKNOWN') -> Dict:
        """
        7-stage waterfall with early exit on PROSPECT.

        Returns evidence-compliant dict with tier, channel, cost, etc.
        """
        total_cost = 0.0
        processing_log = []

        try:
            # Stage 1: Public/Private Detection (instant, FREE)
            is_public = self.is_public_hospital(facility_name)
            processing_log.append(f"Stage 1: Public={is_public}")

            # Stage 2A: State Procurement DB (public only, FREE)
            if is_public and self.procurement_db_path:
                try:
                    result = self.search_state_procurement(facility_name, state)
                    if result:
                        processing_log.append("Stage 2A: PROSPECT (state procurement)")
                        return {
                            'tier': 'PROSPECT',
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
                except Exception as e:
                    processing_log.append(f"Stage 2A: Error - {str(e)[:50]}")

            # Stage 2B: Federal Contracts API (all hospitals, $0.001)
            try:
                result = self.search_federal_contracts(facility_name, state)
                total_cost += 0.001

                if result:
                    processing_log.append("Stage 2B: PROSPECT (federal contracts)")
                    return {
                        'tier': 'PROSPECT',
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

            # Stage 3: YouTube Video + YOLO + VLM ($0.015-0.025)
            try:
                video_result = self.search_and_analyze_videos(facility_name, city, state)
                total_cost += video_result.get('cost', 0.0)

                if video_result['tier'] == 'PROSPECT':
                    processing_log.append("Stage 3: PROSPECT (video)")
                    return {**video_result, 'cost': total_cost, 'processing_log': processing_log, 'vertical': 'healthcare'}
                else:
                    processing_log.append(f"Stage 3: {video_result.get('reason', 'No evidence')}")

            except Exception as e:
                processing_log.append(f"Stage 3: Error - {str(e)[:50]}")

            # Stages 4-7: Future channels (STUB)
            processing_log.append("Stages 4-7: Not implemented")

            # No evidence found
            return {
                'tier': 'REJECTED',
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
                'tier': 'REJECTED',
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
    """
    enricher = HealthcareEnricherUnified()

    facility_name = record.get('clean_name') or record.get('account_name', '')
    city = record.get('account_state', '')  # Use full state name for broader search (matches old enricher)
    state = record.get('state_abbrev', '')
    segment = record.get('segment', 'UNKNOWN')

    if not facility_name:
        return {
            **record,
            'tier': 'REJECTED',
            'channel': 'none',
            'cost': 0.0,
            'error': 'Missing facility name'
        }

    result = enricher.enrich_facility(facility_name, city, state, segment)

    return {**record, **result}
