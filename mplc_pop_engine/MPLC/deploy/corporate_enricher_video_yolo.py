#!/usr/bin/env python3
"""
Corporate PoP Detection - Video+YOLO Pipeline

Uses same proven approach as healthcare:
1. YouTube/Vimeo search for office tours
2. Video download (pytubefix)
3. Frame extraction
4. YOLO TV detection
5. VLM confirmation

Expected: 15-25% PROSPECT rate (vs 0% with static images)
"""

import os
import json
import requests
import base64
import tempfile
import imghdr
import time
from pathlib import Path
from typing import Dict, Optional, List

# API Keys
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


class CorporateEnricherVideoYOLO:
    """Corporate PoP detection with video+YOLO pipeline."""

    def __init__(self):
        self.rapidapi_key = RAPIDAPI_KEY
        self.anthropic_key = ANTHROPIC_API_KEY

        if not self.rapidapi_key:
            raise ValueError("RAPIDAPI_KEY not set")
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

    def search_youtube_videos(self, company_name: str) -> Optional[List[Dict]]:
        """Search YouTube for corporate office videos."""

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

                    # Filter for office/tour videos
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
                print(f"YouTube search error: {e}")
                continue

        return all_videos[:3] if all_videos else None

    def download_video(self, video_url: str, output_dir: Path) -> Optional[Path]:
        """Download YouTube video using pytubefix with retry logic."""

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
                    print(f"Video download error: {e}")
                    return None

        return None

    def extract_frames(self, video_path: Path, interval_seconds: int = 2) -> List[Path]:
        """Extract frames from video at regular intervals."""
        import cv2

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
            print(f"YOLO error: {e}")
            return None

    def analyze_frame_vlm(
        self,
        frame_path: Path,
        company_name: str,
        video_title: str
    ) -> Optional[Dict]:
        """Analyze YOLO-positive frame with VLM."""

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

            from anthropic import Anthropic
            client = Anthropic(api_key=self.anthropic_key)

            prompt = f"""Analyze this corporate office video frame for TV evidence.

Company: {company_name}
Video: {video_title}

Look for TVs in employee-accessible communal spaces (lobby, cafeteria, lounge, break room).

EXCLUDE:
- Meeting room displays
- Computer monitors at desks
- Digital signage/wayfinding
- Reception desk monitors

Answer ONLY with valid JSON:
{{
  "tv_detected": true|false,
  "tv_location": "lobby|cafeteria|employee_lounge|break_room|none",
  "confidence": "high|medium|low",
  "is_entertainment_tv": true|false,
  "is_communal_space": true|false,
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
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1].replace("json", "").strip()

            result = json.loads(text)

            cost = (response.usage.input_tokens / 1_000_000 * 1.50) + \
                   (response.usage.output_tokens / 1_000_000 * 7.50)

            result['cost'] = cost
            return result

        except Exception as e:
            print(f"VLM analysis error: {e}")
            return None

    def enrich_account(self, company_name: str) -> Dict:
        """Enrich corporate account with video+YOLO+VLM pipeline."""

        total_cost = 0.0
        rapidapi_cost = 0.004  # ~$0.001 per search × 4 searches

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Search YouTube
            videos = self.search_youtube_videos(company_name)

            if not videos:
                return {
                    'tier': 'REJECTED',
                    'channel': 'none',
                    'evidence_url': '',
                    'confidence': 'none',
                    'cost': rapidapi_cost,
                    'details': {'reason': 'No office tour videos found'}
                }

            # Process videos
            for video in videos:
                print(f"  Processing: {video['title'][:50]}...")

                video_path = self.download_video(video['url'], tmpdir_path)
                if not video_path:
                    print(f"    Failed to download")
                    continue

                frames = self.extract_frames(video_path)
                if not frames:
                    print(f"    Failed to extract frames")
                    continue

                print(f"    Extracted {len(frames)} frames")

                # YOLO scan
                yolo_positive_frames = []
                for frame in frames:
                    detection = self.yolo_detect_tv(frame)
                    if detection:
                        yolo_positive_frames.append(detection)

                print(f"    YOLO detected TV in {len(yolo_positive_frames)} frames")

                # VLM analyze
                for detection in yolo_positive_frames[:3]:
                    analysis = self.analyze_frame_vlm(
                        detection['frame_path'],
                        company_name,
                        video['title']
                    )

                    if not analysis:
                        continue

                    total_cost += analysis.get('cost', 0.0)

                    if analysis['tv_detected'] and \
                       analysis['is_entertainment_tv'] and \
                       analysis['is_communal_space'] and \
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
                            'cost': total_cost + rapidapi_cost,
                            'details': {
                                'video': video,
                                'yolo_detection': detection,
                                'vlm_analysis': analysis,
                                'frames_checked': len(frames),
                                'yolo_positives': len(yolo_positive_frames)
                            }
                        }

            return {
                'tier': 'REJECTED',
                'channel': 'youtube_video_yolo',
                'evidence_url': '',
                'confidence': 'none',
                'cost': total_cost + rapidapi_cost,
                'details': {
                    'reason': f'No TV evidence in {len(videos)} videos',
                    'videos_checked': len(videos)
                }
            }


def process_account(record: Dict) -> Dict:
    """Process corporate account (unified_worker compatible)."""

    enricher = CorporateEnricherVideoYOLO()

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
