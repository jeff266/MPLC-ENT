"""
Corporate Video Channel - TV Detection in Office/Corporate Videos

Searches YouTube for corporate office tours, "Life at [Company]" videos,
employee testimonials, and headquarters tours. Analyzes frames for TV evidence
in common areas (lobbies, break rooms, cafeterias, lounges).
"""

import os
import sys
import logging
import subprocess
from typing import Dict, List, Optional, Tuple
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Optional dependencies
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False

try:
    from googleapiclient.discovery import build
    YOUTUBE_API_AVAILABLE = True
except ImportError:
    YOUTUBE_API_AVAILABLE = False

try:
    from anthropic import Anthropic
    import base64
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

log = logging.getLogger(__name__)


class CorporateVideoChannel:
    """Detect TVs in corporate office tour videos and employee culture videos."""

    def __init__(self, yolo_model_path: str = 'yolo11n.pt', youtube_api_key: Optional[str] = None, anthropic_api_key: Optional[str] = None):
        self.yolo_model_path = yolo_model_path
        self.yolo_model = None
        self.youtube_api_key = youtube_api_key or os.getenv('YOUTUBE_API_KEY')
        self.anthropic_client = None

        # Set up environment for yt-dlp with deno
        self.env = os.environ.copy()
        deno_path = os.path.expanduser('~/.deno/bin')
        if deno_path not in self.env.get('PATH', ''):
            self.env['PATH'] = f"{deno_path}:{self.env.get('PATH', '')}"

        if YOLO_AVAILABLE:
            if Path(yolo_model_path).exists():
                self.yolo_model = YOLO(yolo_model_path)
                log.info(f"Loaded YOLO model: {yolo_model_path}")
            else:
                log.warning(f"YOLO model not found: {yolo_model_path}")
        else:
            log.warning("YOLO not available (pip install ultralytics)")

        if ANTHROPIC_AVAILABLE:
            api_key = anthropic_api_key or os.getenv('ANTHROPIC_API_KEY')
            if api_key:
                self.anthropic_client = Anthropic(api_key=api_key)
                log.info("Anthropic VLM client initialized")
            else:
                log.warning("Anthropic API key not found - VLM verification disabled")
        else:
            log.warning("Anthropic not available (pip install anthropic) - VLM verification disabled")

    def search_videos(self, name: str, website: str) -> Dict:
        """
        Search YouTube for corporate office/culture videos and analyze for TVs.

        Returns dict with 'found' bool, 'evidence' dict, and 'cost' float.
        """
        if not self.yolo_model:
            log.debug(f"    YOLO not available, skipping video search")
            return {'found': False, 'evidence': {}, 'cost': 0.0}

        try:
            # Search YouTube for corporate videos
            video_urls = self._search_youtube_corporate_videos(name)

            if not video_urls:
                log.debug(f"    No corporate videos found on YouTube")
                return {'found': False, 'evidence': {}, 'cost': 0.0}

            log.debug(f"    Found {len(video_urls)} corporate video(s) to analyze")

            # Analyze each video for TVs (limit to first 2 videos)
            total_cost = 0.0
            all_vlm_rejections = []

            for video_url in video_urls[:2]:
                tv_detected, confidence, frame_path, vlm_cost, vlm_classification = self._analyze_video_for_tv(video_url, name)
                total_cost += vlm_cost

                if tv_detected and confidence > 0.5:
                    log.info(f"    ✓ TV detected in corporate video (confidence: {confidence:.2f}), VLM cost: ${total_cost:.4f}")
                    return {
                        'found': True,
                        'evidence': {
                            'TVEvidenceFound': True,
                            'Channel': 'corporate_videos',
                            'EvidenceLocation': 'Common Area (Office)',
                            'EvidenceQuote': f'TV detected in corporate video (YOLO confidence: {confidence:.2f}, VLM: {vlm_classification})',
                            'SourceURL': video_url,
                            'Confidence': 'High' if confidence > 0.7 else 'Medium',
                            'YOLOConfidence': confidence,
                            'FramePath': frame_path,
                            'VLMClassification': vlm_classification,
                            'VLMCost': total_cost
                        },
                        'cost': total_cost
                    }
                else:
                    all_vlm_rejections.append(vlm_classification)

            log.debug(f"    No TVs detected in corporate videos (VLM rejections: {all_vlm_rejections}), Total cost: ${total_cost:.4f}")
            return {'found': False, 'evidence': {}, 'cost': total_cost}

        except Exception as e:
            log.warning(f"    Video search error: {e}")
            return {'found': False, 'evidence': {}, 'cost': 0.0}

    def _verify_common_area(self, frame_path: str) -> Tuple[bool, str, float]:
        """
        Use VLM to verify if the TV is in a common employee area (not private office/conference room).

        Returns (is_common_area, classification, cost).
        """
        if not self.anthropic_client:
            log.debug("    VLM verification skipped (no API key)")
            return True, 'UNKNOWN', 0.0  # Skip verification if VLM not available

        try:
            # Read and encode image
            with open(frame_path, 'rb') as f:
                image_data = base64.standard_b64encode(f.read()).decode('utf-8')

            # Determine media type
            ext = Path(frame_path).suffix.lower()
            media_type = 'image/jpeg' if ext in ['.jpg', '.jpeg'] else 'image/png'

            # Call Claude to classify space type
            response = self.anthropic_client.messages.create(
                model="claude-haiku-5-5",
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data
                            }
                        },
                        {
                            "type": "text",
                            "text": """Is this a COMMON EMPLOYEE area (break room, cafeteria, lobby, lounge, reception) or a PRIVATE space (individual office, conference room, executive suite)?

Look for these indicators:
- COMMON: Open shared space, multiple seating areas, kitchen/break room amenities, cafeteria tables, lobby reception, public waiting area
- PRIVATE: Closed office, single desk, conference table, executive furniture, small enclosed room, private workspace

Reply with ONE of:
- COMMON: This is a common employee area (break room, cafeteria, lobby, lounge)
- PRIVATE: This is a private office, conference room, or executive space
- UNCLEAR: Cannot determine from this image"""
                        }
                    ]
                }]
            )

            # Extract text from response (skip thinking blocks if present)
            result_text = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    result_text = block.text.strip().upper()
                    break

            # Haiku 5.5 pricing: $0.25/MTok input, $1.25/MTok output
            cost = (response.usage.input_tokens * 0.25 + response.usage.output_tokens * 1.25) / 1_000_000

            if result_text.startswith('COMMON'):
                return True, 'COMMON', cost
            elif result_text.startswith('PRIVATE'):
                return False, 'PRIVATE', cost
            else:
                return False, 'UNCLEAR', cost

        except Exception as e:
            log.warning(f"    VLM verification error: {e}")
            return False, 'ERROR', 0.0

    def _search_youtube_corporate_videos(self, name: str) -> List[str]:
        """
        Search YouTube for corporate office tours, employee culture videos, and headquarters tours.

        Multi-query fallback strategy:
        1. "Life at [Company]" / "Working at [Company]" (employee culture videos)
        2. Office tour / headquarters tour videos
        3. "Day in the life" employee testimonials
        4. Behind-the-scenes corporate videos

        Returns list of video URLs.
        """
        video_urls = []

        # Try YouTube API if available
        if YOUTUBE_API_AVAILABLE and self.youtube_api_key:
            try:
                youtube = build('youtube', 'v3', developerKey=self.youtube_api_key)

                # Multi-query fallback: try in priority order
                # Corporate culture videos often show common areas more than formal tours
                search_queries = [
                    f'life at {name}',
                    f'working at {name}',
                    f'{name} office tour',
                    f'{name} headquarters tour',
                    f'day in the life {name}',
                    f'{name} campus tour',
                    f'behind the scenes {name}'
                ]

                for query in search_queries:
                    request = youtube.search().list(
                        part='snippet',
                        q=query,
                        type='video',
                        maxResults=3,
                        order='relevance'
                    )
                    response = request.execute()

                    for item in response.get('items', []):
                        video_id = item['id']['videoId']
                        video_urls.append(f'https://www.youtube.com/watch?v={video_id}')

                    if video_urls:
                        log.debug(f"    Found videos with query: '{query}'")
                        break  # Found videos, no need to try other queries

                return video_urls

            except Exception as e:
                log.debug(f"    YouTube API error: {e}")

        # Fallback: Use yt-dlp to search YouTube
        try:
            # Try queries in priority order
            search_queries = [
                f'life at {name}',
                f'working at {name}',
                f'{name} office tour',
                f'{name} headquarters tour',
                f'day in the life {name}'
            ]

            for search_query in search_queries:
                cmd = [
                    'yt-dlp',
                    f'ytsearch3:{search_query}',  # Search for top 3 results
                    '--get-id',
                    '--no-playlist'
                ]

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=self.env)
                if result.returncode == 0 and result.stdout.strip():
                    video_ids = result.stdout.strip().split('\n')
                    video_urls = [f'https://www.youtube.com/watch?v={vid}' for vid in video_ids if vid]
                    if video_urls:
                        log.debug(f"    Found videos with query: '{search_query}'")
                        return video_urls

        except Exception as e:
            log.debug(f"    yt-dlp search error: {e}")

        return []

    def _analyze_video_for_tv(self, video_url: str, company_name: str) -> Tuple[bool, float, Optional[str], float, str]:
        """
        Download video, extract frames, and run YOLO TV detection with VLM verification.

        Returns (tv_detected, confidence, frame_path, vlm_cost, vlm_classification).
        """
        try:
            # Create temp directory for video and frames
            temp_dir = Path(f'/tmp/corporate_videos/{company_name.replace(" ", "_")}')
            temp_dir.mkdir(parents=True, exist_ok=True)

            # Download video using yt-dlp (let yt-dlp add the extension)
            video_basename = temp_dir / 'corporate_video'

            download_cmd = [
                'yt-dlp',
                '--remote-components', 'ejs:github',  # Enable remote components for YouTube
                '-f', 'bestvideo[height<=480]+bestaudio/best[height<=480]',  # Lower quality for speed
                '-o', str(video_basename) + '.%(ext)s',  # Let yt-dlp add correct extension
                video_url,
                '--max-filesize', '100M',  # Limit file size
            ]

            result = subprocess.run(download_cmd, timeout=120, check=True, env=self.env, capture_output=True, text=True)

            # Find the downloaded video file (yt-dlp adds the extension)
            video_files = list(temp_dir.glob('corporate_video.*'))
            if not video_files:
                log.debug(f"    Failed to download video: {video_url}")
                return False, 0.0, None, 0.0, 'DOWNLOAD_FAILED'

            video_path = video_files[0]  # Use the first (and should be only) match

            # Extract frames (1 frame every 3 seconds, max 20 frames)
            frames_dir = temp_dir / 'frames'
            frames_dir.mkdir(exist_ok=True)

            extract_cmd = [
                'ffmpeg',
                '-i', str(video_path),
                '-vf', 'fps=1/3',  # 1 frame every 3 seconds
                '-frames:v', '20',  # Max 20 frames
                '-y',
                str(frames_dir / 'frame_%03d.jpg')
            ]

            subprocess.run(extract_cmd, capture_output=True, timeout=60)

            # Run YOLO on each frame, then VLM verify common area
            tv_detections = []  # List of (frame_path, confidence) tuples

            for frame_path in sorted(frames_dir.glob('frame_*.jpg')):
                results = self.yolo_model(str(frame_path), verbose=False)

                # Check for TV (class 62 in COCO dataset)
                for result in results:
                    for box in result.boxes:
                        class_id = int(box.cls[0])
                        confidence = float(box.conf[0])

                        if class_id == 62 and confidence > 0.5:
                            tv_detections.append((str(frame_path), confidence))
                            break  # Only need one detection per frame

            # Verify each detection with VLM to filter out private offices/conference rooms
            total_vlm_cost = 0.0
            vlm_rejections = []

            for frame_path, yolo_conf in tv_detections:
                is_common, classification, vlm_cost = self._verify_common_area(frame_path)
                total_vlm_cost += vlm_cost

                if is_common and classification == 'COMMON':
                    log.debug(f"      YOLO: {yolo_conf:.2f}, VLM: {classification} (common area confirmed), Cost: ${vlm_cost:.4f}")
                    return True, yolo_conf, frame_path, total_vlm_cost, classification
                else:
                    log.debug(f"      YOLO: {yolo_conf:.2f}, VLM: {classification} (rejected - not common area), Cost: ${vlm_cost:.4f}")
                    vlm_rejections.append(classification)

            # No common area TVs found
            if tv_detections:
                log.debug(f"      {len(tv_detections)} TV(s) detected but all rejected by VLM: {vlm_rejections}, Total cost: ${total_vlm_cost:.4f}")
            return False, 0.0, None, total_vlm_cost, 'NO_COMMON_AREA_TV'

        except subprocess.TimeoutExpired:
            log.debug(f"    Video download/processing timeout: {video_url}")
            return False, 0.0, None, 0.0, 'TIMEOUT'
        except subprocess.CalledProcessError as e:
            log.debug(f"    Video download failed for {video_url}")
            return False, 0.0, None, 0.0, 'DOWNLOAD_FAILED'
        except Exception as e:
            log.debug(f"    Error analyzing video {video_url}: {e}")
            return False, 0.0, None, 0.0, 'ERROR'


# Example usage
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    channel = CorporateVideoChannel()

    # Test with a corporate account
    result = channel.search_videos(
        'Costco Wholesale',
        'https://www.costco.com'
    )

    print("\nCorporate Video Channel Result:")
    print("="*60)
    print(f"Found: {result['found']}")
    if result['found']:
        for key, value in result['evidence'].items():
            print(f"{key}: {value}")
