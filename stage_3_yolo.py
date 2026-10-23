"""
Stage 3: YOLO Object Detection (Free, Local CPU)
Detects TVs and context objects in images to filter candidates for VLM
"""

import requests
from typing import List, Dict, Optional
from pathlib import Path
import hashlib

try:
    from ultralytics import YOLO
    import cv2
    import numpy as np
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("WARNING: Ultralytics YOLO not installed. Run: pip install ultralytics opencv-python")

import config
from cost_tracker import CostTracker


class YOLODetector:
    """Detect TVs and context objects in images using YOLO"""

    def __init__(self, tracker: CostTracker, run_id: str):
        self.tracker = tracker
        self.run_id = run_id
        self.model = None
        self.cache_dir = config.CACHE_DIR / "images"
        self.cache_dir.mkdir(exist_ok=True, parents=True)

        if YOLO_AVAILABLE:
            self._load_model()

    def _load_model(self):
        """Load YOLO model (downloads if not cached)"""
        try:
            # Use YOLO11n (nano) for fast CPU inference
            self.model = YOLO(config.YOLO_MODEL)
            print(f"✓ YOLO model loaded: {config.YOLO_MODEL}")
        except Exception as e:
            print(f"Error loading YOLO model: {e}")
            self.model = None

    def _download_image(self, url: str) -> Optional[Path]:
        """Download image and cache it"""
        # Generate cache key from URL
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = self.cache_dir / f"{url_hash}.jpg"

        # Return cached if exists
        if cache_path.exists() and config.CACHE_ENABLED:
            return cache_path

        try:
            # Download image
            response = requests.get(url, timeout=10, stream=True)
            if response.status_code != 200:
                return None

            # Save to cache
            with open(cache_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return cache_path

        except Exception as e:
            print(f"Error downloading image {url}: {e}")
            return None

    def detect_objects(self, image_path: Path) -> List[Dict]:
        """
        Run YOLO inference on image.
        Returns list of detected objects with class names and confidence.
        """
        if not self.model:
            return []

        try:
            # Run inference
            results = self.model(
                str(image_path),
                conf=config.YOLO_CONFIDENCE_THRESHOLD,
                verbose=False
            )

            detections = []

            for result in results:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    class_name = result.names[class_id]
                    confidence = float(box.conf[0])

                    detections.append({
                        'class': class_name,
                        'confidence': confidence
                    })

            return detections

        except Exception as e:
            print(f"Error running YOLO inference: {e}")
            return []

    def analyze_context(self, detections: List[Dict]) -> Dict:
        """
        Analyze detected objects to determine if this is a public space TV.

        Returns: {
            has_tv: bool,
            has_supportive_context: bool,
            has_personal_context: bool,
            context_objects: list,
            pass_to_vlm: bool
        }
        """
        detected_classes = [d['class'] for d in detections]

        # Check for TV
        has_tv = any(cls in config.YOLO_TARGET_CLASSES for cls in detected_classes)

        # Check for supportive context (public/shared space)
        supportive = [obj for obj in detected_classes if obj in config.YOLO_CONTEXT_CLASSES]
        has_supportive_context = len(supportive) > 0

        # Check for personal context (desk/monitor scenario)
        personal = [obj for obj in detected_classes if obj in config.YOLO_PERSONAL_CONTEXT]
        has_personal_context = len(personal) > 0

        # Decision: pass to VLM if TV + supportive context, not personal context
        pass_to_vlm = has_tv and has_supportive_context and not has_personal_context

        return {
            'has_tv': has_tv,
            'has_supportive_context': has_supportive_context,
            'has_personal_context': has_personal_context,
            'supportive_objects': supportive,
            'personal_objects': personal,
            'pass_to_vlm': pass_to_vlm,
            'all_detections': detections
        }

    def process_images(self, image_urls: List[str], account_id: str) -> List[Dict]:
        """
        Process multiple images and return those that pass to VLM.
        Returns list of {image_url, image_path, detections, analysis}
        """
        if not YOLO_AVAILABLE or not self.model:
            print("YOLO not available, skipping object detection")
            return []

        passed_images = []

        for url in image_urls[:20]:  # Limit to 20 images per account
            # Download image
            image_path = self._download_image(url)
            if not image_path:
                continue

            # Run YOLO detection
            detections = self.detect_objects(image_path)

            # Log inference (free but tracked)
            detection_summary = [d['class'] for d in detections]
            self.tracker.log_yolo_inference(
                account_id=account_id,
                image_url=url,
                detections=detection_summary
            )

            # Analyze context
            analysis = self.analyze_context(detections)

            # If passes filter, add to results
            if analysis['pass_to_vlm']:
                passed_images.append({
                    'image_url': url,
                    'image_path': str(image_path),
                    'detections': detections,
                    'analysis': analysis
                })

        return passed_images

    def process_image_files(self, image_paths: List[str], image_urls: List[str], account_id: str) -> List[Dict]:
        """
        Process already-saved image files (bypasses download step).
        Used when Playwright saves response bodies directly.

        Args:
            image_paths: List of file paths to images on disk
            image_urls: Corresponding URLs for reference/logging
            account_id: Account ID for tracking

        Returns:
            List of {image_url, image_path, detections, analysis} for images that pass to VLM
        """
        if not YOLO_AVAILABLE or not self.model:
            print("YOLO not available, skipping object detection")
            return []

        passed_images = []

        for i, image_path in enumerate(image_paths[:20]):  # Limit to 20 images per account
            if not Path(image_path).exists():
                continue

            # Run YOLO detection
            detections = self.detect_objects(Path(image_path))

            # Get corresponding URL for logging (or use path if no URL)
            image_url = image_urls[i] if i < len(image_urls) else image_path

            # Log inference (free but tracked)
            detection_summary = [d['class'] for d in detections]
            self.tracker.log_yolo_inference(
                account_id=account_id,
                image_url=image_url,
                detections=detection_summary
            )

            # Analyze context
            analysis = self.analyze_context(detections)

            # If passes filter, add to results
            if analysis['pass_to_vlm']:
                passed_images.append({
                    'image_url': image_url,
                    'image_path': str(image_path),
                    'detections': detections,
                    'analysis': analysis
                })

        return passed_images


if __name__ == "__main__":
    # Test YOLO detection
    from cost_tracker import CostTracker
    from datetime import datetime

    if not YOLO_AVAILABLE:
        print("Install YOLO first: pip install ultralytics opencv-python")
        exit(1)

    tracker = CostTracker("test_yolo.db")
    run_id = f"test_yolo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    tracker.create_run(run_id, max_cost_usd=5.0, max_serper_credits=50, accounts_total=1)

    detector = YOLODetector(tracker, run_id)

    # Test with sample images (would need real URLs)
    test_images = [
        # Add real image URLs here for testing
    ]

    if test_images:
        results = detector.process_images(test_images, "001TEST123")

        print("\n" + "=" * 80)
        print("YOLO Detection Test Results")
        print("=" * 80)

        print(f"\nImages processed: {len(test_images)}")
        print(f"Images passed to VLM: {len(results)}")

        for img in results:
            print(f"\n✓ {img['image_url']}")
            print(f"  Supportive objects: {img['analysis']['supportive_objects']}")
            print(f"  Detections: {[d['class'] for d in img['detections']]}")
    else:
        print("No test images provided. Add image URLs to test.")

    totals = tracker.get_run_totals(run_id)
    print(f"\nYOLO inferences: {totals['total_yolo_inferences']}")

    tracker.complete_run(run_id)
    tracker.close()
