#!/usr/bin/env python3
"""
MDU PoP Detection Enricher - Unified with Video Processing

Waterfall (free → paid):
1. Website images (Playwright scraper) → YOLO → VLM
2. YouTube property tours → RapidAPI download → YOLO → VLM (NEW!)

Uses same battle-tested video pipeline as healthcare.
"""

import os
import json
import requests
import base64
import imghdr
import sys
import time
import cv2
from typing import Dict, Optional, List
from pathlib import Path
from anthropic import Anthropic
from ultralytics import YOLO

# API Keys
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


class MDUEnricherUnified:
    """MDU PoP detection with video processing via RapidAPI."""

    def __init__(self):
        self.serper_key = SERPER_API_KEY
        self.anthropic_key = ANTHROPIC_API_KEY
        self.yolo_model_path = self._find_yolo_model()

        if not self.serper_key:
            raise ValueError("SERPER_API_KEY not set")
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

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
        Same method as healthcare enricher - bypasses bot detection.
        Cost: ~$0.0003 per video.
        """
        try:
            # Extract video ID
            video_id = None
            if "youtube.com/watch?v=" in video_url:
                video_id = video_url.split("watch?v=")[1].split("&")[0]
            elif "youtu.be/" in video_url:
                video_id = video_url.split("youtu.be/")[1].split("?")[0]

            if not video_id:
                return None, "Could not extract video ID"

            output_file = output_dir / f"{video_id}.mp4"

            # Step 1: Initiate download
            api_url = "https://youtube-info-download-api.p.rapidapi.com/ajax/download.php"
            headers = {
                "X-RapidAPI-Key": "7df8cded7emsh4ad2e7a1007cd4dp1027adjsn5b025c1c3acc",
                "X-RapidAPI-Host": "youtube-info-download-api.p.rapidapi.com",
                "accept": "application/json"
            }
            params = {
                "url": video_url,
                "format": "720",
                "max_duration": 30,
                "add_info": "1"
            }

            response = requests.get(api_url, headers=headers, params=params, timeout=60)

            if response.status_code != 200:
                return None, f"RapidAPI: {response.status_code}"

            result = response.json()

            # Step 2: Poll progress until download URL is ready
            progress_url = result.get('progress_url')

            if not progress_url:
                return None, "RapidAPI: No progress URL"

            # Poll for up to 60 seconds
            download_url = None
            max_attempts = 30
            for attempt in range(max_attempts):
                time.sleep(2)
                progress_response = requests.get(progress_url, timeout=30)
                progress_data = progress_response.json()

                download_url = progress_data.get('download_url') or progress_data.get('url')
                if download_url:
                    break

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
            print(f"  VLM error: {e}")
            return None

    def process_videos(
        self,
        videos: List[Dict],
        property_name: str,
        temp_dir: Path
    ) -> Optional[Dict]:
        """Process YouTube videos to find TV evidence."""

        for i, video in enumerate(videos[:3], 1):  # Process up to 3 videos
            video_url = video['url']
            video_title = video['title']

            print(f"    Processing video: {video_title[:60]}...")

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
                continue

            # VLM analysis on best frame (highest YOLO confidence)
            best_frame = max(tv_frames, key=lambda x: x['confidence'])

            vlm_result = self.analyze_frame_vlm(
                best_frame['frame_path'],
                property_name,
                video_title
            )

            if not vlm_result:
                continue

            # Check if it's a valid PROSPECT
            if (vlm_result.get('tv_detected') and
                vlm_result.get('is_entertainment_tv') and
                vlm_result.get('is_common_area') and
                vlm_result.get('confidence') in ['high', 'medium']):

                return {
                    'tier': 'PROSPECT',
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

        Waterfall:
        1. Website images (if available) - NOT IMPLEMENTED YET
        2. YouTube property tours → RapidAPI download → YOLO → VLM
        """

        total_cost = 0.0
        temp_dir = Path("/tmp/mdu_videos") / property_name.replace(" ", "_")
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Channel 1: Website images (TODO - integrate scraper)
        # For now, skip directly to YouTube

        # Channel 2: YouTube property tours
        print(f"  Searching YouTube for property tours...")
        videos = self.search_youtube_videos(property_name, city, state)

        if videos:
            print(f"    Found {len(videos)} videos")
            result = self.process_videos(videos, property_name, temp_dir)

            if result:
                result['cost'] += total_cost
                return result

        # No TV evidence found
        return {
            'tier': 'REJECTED',
            'channel': 'none',
            'evidence_url': '',
            'confidence': 'none',
            'cost': total_cost,
            'reason': 'No TV evidence found in available channels'
        }


def process_property(record: dict) -> dict:
    """Process a single MDU property record."""
    try:
        enricher = MDUEnricherUnified()

        property_name = record.get('property_name', '')
        city = record.get('city', '')
        state = record.get('state', '')
        website = record.get('website', '')

        result = enricher.enrich_property(property_name, city, state, website)

        return {**record, **result}

    except Exception as e:
        return {
            **record,
            'tier': 'REJECTED',
            'channel': 'none',
            'evidence_url': '',
            'confidence': 'none',
            'cost': 0.0,
            'error': str(e)
        }
