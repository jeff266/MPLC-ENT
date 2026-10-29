#!/usr/bin/env python3
"""
Healthcare PoP Detection - RapidAPI + Video Download + YOLO + VLM

Pipeline:
1. RapidAPI YouTube search (no quota limits)
2. Download video with yt-dlp
3. Extract frames (every 2 seconds)
4. YOLO detection on frames (filter for 'tv'/'monitor')
5. VLM confirmation on YOLO-positive frames only

Cost: ~$0.015-0.025/account (much cheaper than analyzing all thumbnails)
Expected coverage: 15-25% (similar to MDU video channel)
"""

import os
import json
import requests
import base64
import tempfile
import imghdr
from pathlib import Path
from typing import Dict, Optional, List

# API Keys
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


class HealthcareEnricherVideoYOLO:
    """Healthcare PoP detection with proper video processing pipeline."""

    def __init__(self):
        self.rapidapi_key = RAPIDAPI_KEY
        self.anthropic_key = ANTHROPIC_API_KEY

        if not self.rapidapi_key:
            raise ValueError("RAPIDAPI_KEY not set")
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        # Check for required dependencies
        self._check_dependencies()

    def _check_dependencies(self):
        """Check for pytubefix, cv2, and YOLO."""
        try:
            from pytubefix import YouTube
        except ImportError:
            raise RuntimeError("pytubefix not installed. Install: pip install pytubefix")

        try:
            import cv2
        except ImportError:
            raise RuntimeError("opencv-python not installed. Install: pip install opencv-python")

        try:
            from ultralytics import YOLO
        except ImportError:
            raise RuntimeError("ultralytics not installed. Install: pip install ultralytics")

    def search_youtube_videos(
        self,
        facility_name: str,
        city: str,
        state: str
    ) -> Optional[List[Dict]]:
        """Search YouTube using RapidAPI (no YouTube quota needed)."""

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

                params = {
                    "query": query,
                    "type": "video"
                }

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

                    # Filter for tour videos
                    if any(kw in title_lower for kw in ["tour", "virtual", "facility", "hospital", "welcome", "inside"]):
                        all_videos.append({
                            "video_id": video_id,
                            "title": title,
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "channel_title": item.get("channelTitle", ""),
                            "description": item.get("description", "")
                        })

                if all_videos:
                    break  # Found videos, no need for more queries

            except Exception as e:
                print(f"YouTube search error: {e}")
                continue

        return all_videos[:3] if all_videos else None  # Return top 3 videos

    def download_video(self, video_url: str, output_dir: Path) -> tuple[Optional[Path], Optional[str]]:
        """Download YouTube video using pytubefix with timeout and pytube fallback.

        Returns:
            (video_path, error_message) - video_path is None if failed, error_message describes failure
        """
        import time
        import signal
        from contextlib import contextmanager

        @contextmanager
        def timeout(seconds):
            def timeout_handler(signum, frame):
                raise TimeoutError(f"Download exceeded {seconds}s timeout")

            # Set alarm
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(seconds)
            try:
                yield
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

        # Try pytubefix first
        max_retries = 2
        for attempt in range(max_retries):
            try:
                with timeout(60):  # 60 second timeout
                    from pytubefix import YouTube

                    yt = YouTube(video_url)

                    stream = yt.streams.filter(
                        file_extension='mp4',
                        only_video=True
                    ).order_by('resolution').first()

                    if not stream:
                        stream = yt.streams.filter(file_extension='mp4').first()

                    if not stream:
                        return None, "No suitable video stream found"

                    output_file = stream.download(
                        output_path=str(output_dir),
                        filename=f"{yt.video_id}.mp4"
                    )

                    return Path(output_file), None

            except TimeoutError as e:
                print(f"    pytubefix timeout: {e}")
                break  # Don't retry on timeout, try fallback

            except Exception as e:
                if '503' in str(e) and attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5
                    print(f"    Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"    pytubefix error: {e}")
                    break  # Try fallback

        # Fallback to pytube
        print(f"    Trying pytube fallback...")
        try:
            with timeout(60):
                from pytube import YouTube

                yt = YouTube(video_url)

                stream = yt.streams.filter(
                    file_extension='mp4',
                    only_video=True
                ).order_by('resolution').first()

                if not stream:
                    stream = yt.streams.filter(file_extension='mp4').first()

                if not stream:
                    return None, "pytube: No suitable stream"

                output_file = stream.download(
                    output_path=str(output_dir),
                    filename=f"{yt.video_id}.mp4"
                )

                return Path(output_file), None

        except TimeoutError:
            return None, "pytube: Download timeout (60s)"
        except Exception as e:
            return None, f"pytube: {str(e)[:100]}"

    def extract_frames(self, video_path: Path, interval_seconds: int = 2) -> List[Path]:
        """Extract frames from video at regular intervals."""
        import cv2

        frames = []
        video = cv2.VideoCapture(str(video_path))

        if not video.isOpened():
            return frames

        fps = video.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30  # Default fallback

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

                # Limit to 30 frames max (60 seconds of video at 2 sec intervals)
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
        facility_name: str,
        video_title: str
    ) -> Optional[Dict]:
        """Analyze YOLO-positive frame with VLM for TV evidence."""

        try:
            # Read frame
            with open(frame_path, 'rb') as f:
                img_content = f.read()

            img_b64 = base64.b64encode(img_content).decode('utf-8')

            # Detect image format
            img_format = imghdr.what(None, h=img_content)
            if img_format == 'png':
                media_type = "image/png"
            elif img_format in ['jpeg', 'jpg']:
                media_type = "image/jpeg"
            else:
                media_type = "image/jpeg"

            # VLM analysis
            from anthropic import Anthropic
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

            # Calculate cost
            cost = (response.usage.input_tokens / 1_000_000 * 1.50) + \
                   (response.usage.output_tokens / 1_000_000 * 7.50)

            result['cost'] = cost
            return result

        except Exception as e:
            print(f"VLM analysis error: {e}")
            return None

    def enrich_facility(
        self,
        facility_name: str,
        city: str,
        state: str
    ) -> Dict:
        """Enrich healthcare facility with video+YOLO+VLM pipeline."""

        total_cost = 0.0
        rapidapi_cost = 0.003  # ~$0.001 per search × 3 searches

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Step 1: Search YouTube via RapidAPI
            videos = self.search_youtube_videos(facility_name, city, state)

            if not videos:
                return {
                    'tier': 'REJECTED',
                    'channel': 'none',
                    'evidence_url': '',
                    'confidence': 'none',
                    'cost': rapidapi_cost,
                    'details': {'reason': 'No facility tour videos found (RapidAPI)'}
                }

            # Step 2: Process videos
            video_errors = []
            for video in videos:
                print(f"  Processing video: {video['title'][:50]}...")

                # Download video (returns tuple: path, error)
                video_path, error = self.download_video(video['url'], tmpdir_path)
                if not video_path:
                    print(f"    Failed to download: {error}")
                    video_errors.append({'video': video['title'][:50], 'error': error})
                    continue

                # Extract frames
                frames = self.extract_frames(video_path)
                if not frames:
                    print(f"    Failed to extract frames")
                    continue

                print(f"    Extracted {len(frames)} frames")

                # YOLO scan frames
                yolo_positive_frames = []
                for frame in frames:
                    detection = self.yolo_detect_tv(frame)
                    if detection:
                        yolo_positive_frames.append(detection)

                print(f"    YOLO detected TV in {len(yolo_positive_frames)} frames")

                # VLM analyze YOLO-positive frames
                for detection in yolo_positive_frames[:3]:  # Check up to 3 frames
                    analysis = self.analyze_frame_vlm(
                        detection['frame_path'],
                        facility_name,
                        video['title']
                    )

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
                'error': f'{len(video_errors)} video download failures' if video_errors else '',
                'details': {
                    'reason': f'No TV evidence in {len(videos)} videos',
                    'videos_checked': len(videos),
                    'video_errors': video_errors
                }
            }


def process_account(record: Dict) -> Dict:
    """Process healthcare account (unified_worker compatible)."""

    enricher = HealthcareEnricherVideoYOLO()

    facility_name = record.get('clean_name') or record.get('account_name', '')
    city = record.get('account_state', '')
    state = record.get('state_abbrev', '')

    if not facility_name:
        return {
            **record,
            'tier': 'REJECTED',
            'channel': 'none',
            'error': 'Missing facility name'
        }

    result = enricher.enrich_facility(facility_name, city, state)

    return {**record, **result}
