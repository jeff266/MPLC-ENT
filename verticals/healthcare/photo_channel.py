"""
Healthcare Photo Channel - TV Detection in Facility Images

Downloads facility website photos and uses YOLO to detect TVs.
Similar to corporate pipeline but targets assisted living websites.
"""

import os
import sys
import logging
import requests
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Optional YOLO dependency
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False

log = logging.getLogger(__name__)


class HealthcarePhotoChannel:
    """Detect TVs in assisted living facility photos."""

    def __init__(self, yolo_model_path: str = 'yolo11n.pt'):
        self.yolo_model_path = yolo_model_path
        self.yolo_model = None

        if YOLO_AVAILABLE:
            # Load YOLO model lazily
            if Path(yolo_model_path).exists():
                self.yolo_model = YOLO(yolo_model_path)
                log.info(f"Loaded YOLO model: {yolo_model_path}")
            else:
                log.warning(f"YOLO model not found: {yolo_model_path}")
        else:
            log.warning("YOLO not available (pip install ultralytics)")

    def search_photos(self, name: str, website: str) -> Dict:
        """
        Search facility website photos for TV evidence.

        Returns dict with 'found' bool and 'evidence' dict.
        """
        if not self.yolo_model:
            log.debug(f"    YOLO not available, skipping photo search")
            return {'found': False, 'evidence': {}}

        try:
            # Scrape facility images from website
            images = self._scrape_facility_images(website)

            if not images:
                log.debug(f"    No facility images found on website")
                return {'found': False, 'evidence': {}}

            log.debug(f"    Found {len(images)} images to analyze")

            # Download and analyze images for TVs
            for img_url in images[:20]:  # Limit to first 20 images
                tv_detected, confidence = self._detect_tv_in_image(img_url)

                if tv_detected and confidence > 0.5:
                    log.info(f"    ✓ TV detected in image (confidence: {confidence:.2f})")
                    return {
                        'found': True,
                        'evidence': {
                            'TVEvidenceFound': True,
                            'Channel': 'website_photos',
                            'EvidenceLocation': 'Common Area/Lounge',
                            'EvidenceQuote': f'TV detected in facility photo (YOLO confidence: {confidence:.2f})',
                            'SourceURL': img_url,
                            'Confidence': 'High' if confidence > 0.7 else 'Medium',
                            'YOLOConfidence': confidence
                        }
                    }

            log.debug(f"    No TVs detected in facility photos")
            return {'found': False, 'evidence': {}}

        except Exception as e:
            log.warning(f"    Photo search error: {e}")
            return {'found': False, 'evidence': {}}

    def _scrape_facility_images(self, website: str) -> List[str]:
        """
        Scrape facility images from website.

        Returns list of image URLs.
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }

            resp = requests.get(website, headers=headers, timeout=10)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, 'html.parser')

            images = []
            for img in soup.find_all('img', src=True):
                src = img['src']

                # Filter for facility photos (not logos/icons)
                if any(k in src.lower() for k in ['.jpg', '.jpeg', '.png', '.webp']):
                    if not any(skip in src.lower() for skip in ['logo', 'icon', 'avatar', 'banner', 'header']):
                        full_url = urljoin(website, src)
                        images.append(full_url)

            return images

        except Exception as e:
            log.debug(f"    Error scraping images: {e}")
            return []

    def _detect_tv_in_image(self, img_url: str) -> Tuple[bool, float]:
        """
        Download image and run YOLO TV detection.

        Returns (tv_detected, confidence).
        """
        try:
            # Download image
            resp = requests.get(img_url, timeout=10)
            if resp.status_code != 200:
                return False, 0.0

            # Save to temp file
            temp_dir = Path('/tmp/healthcare_images')
            temp_dir.mkdir(parents=True, exist_ok=True)

            img_filename = img_url.split('/')[-1][:50]  # Limit filename length
            if not any(img_filename.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                img_filename += '.jpg'

            temp_path = temp_dir / img_filename
            temp_path.write_bytes(resp.content)

            # Run YOLO detection
            results = self.yolo_model(str(temp_path), verbose=False)

            # Check for TV (class 62 in COCO dataset)
            for result in results:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    confidence = float(box.conf[0])

                    if class_id == 62:  # TV/monitor class
                        return True, confidence

            return False, 0.0

        except Exception as e:
            log.debug(f"    Error detecting TV in {img_url}: {e}")
            return False, 0.0


# Example usage
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    channel = HealthcarePhotoChannel()

    # Test with Claiborne
    result = channel.search_photos(
        'Claiborne Senior Living',
        'https://www.theclaiborne.com'
    )

    print("\nPhoto Channel Result:")
    print("="*60)
    print(f"Found: {result['found']}")
    if result['found']:
        for key, value in result['evidence'].items():
            print(f"{key}: {value}")
