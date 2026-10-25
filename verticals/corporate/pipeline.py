"""
Corporate Vertical Pipeline

Channel: SerpAPI image search + YOLO + VLM
Cost: ~$0.022/account
Coverage: 16.7% (validated at n=42)

Evidence standard:
  - TV/display in employee-accessible communal space
  - Corporate HQ or office environment (NOT vehicle interiors, showrooms, or staff-only areas)
  - TV appears powered on with content visible
"""

import sys
import base64
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from anthropic import Anthropic
    from ultralytics import YOLO
except ImportError as e:
    print(f"Missing dependency for corporate pipeline: {e}")
    sys.exit(1)

from config import SERPAPI_API_KEY, ANTHROPIC_API_KEY

VERTICAL_NAME = "Corporate"

# Initialize models (singleton pattern)
_anthropic_client = None
_yolo_model = None

def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client

def _get_yolo_model():
    global _yolo_model
    if _yolo_model is None:
        model_path = _REPO_ROOT / 'mplc_pop_engine' / 'yolo11n.pt'
        _yolo_model = YOLO(str(model_path))
    return _yolo_model


def run_account(account: dict, verbose: bool = False, evidence_dir: Optional[Path] = None) -> dict:
    """
    Run the corporate detection pipeline for one account.

    Args:
        account: Dict with keys: account_id, account_name, website (optional)
        verbose: Print progress to stdout
        evidence_dir: Directory to save evidence photos

    Returns:
        Evidence record dict conforming to the project evidence persistence schema.
    """
    name = account.get("account_name", "")
    account_id = account.get("account_id", "")

    if evidence_dir is None:
        evidence_dir = Path("output/corporate_evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"  [corporate] {name}")

    result = {
        'account_id': account_id,
        'account_name': name,
        'vertical': VERTICAL_NAME,
        'channel': 'image_search',
        'tier': 'REJECTED',
        'evidence_photo_location': '',
        'evidence_description': '',
        'source_url': '',
        'space_type': '',
        'tv_powered_on': False,
        'cost': 0,
        'yolo_confidence': 0,
        'vlm_confidence': '',
        'additional_metadata': {}
    }

    # Search for HQ images
    images = _search_hq_images(name)

    if not images:
        result['evidence_description'] = 'No HQ interior images found'
        if verbose:
            print(f"    ✗ No images found")
        return result

    # Download images
    account_dir = evidence_dir / name.lower().replace(' ', '_').replace(',', '')[:30]
    account_dir.mkdir(exist_ok=True)

    image_paths = []
    for i, img in enumerate(images):
        save_path = account_dir / f"image_{i+1}.jpg"
        downloaded_path = _download_image(img['url'], save_path)
        if downloaded_path:
            image_paths.append(downloaded_path)

    if not image_paths:
        result['evidence_description'] = 'Failed to download images'
        if verbose:
            print(f"    ✗ {len(images)} found but failed to download")
        return result

    # Run YOLO for TV detection
    tv_detections = _run_yolo_batch(image_paths)

    if not tv_detections:
        result['evidence_description'] = f'Downloaded {len(image_paths)} images, no TVs detected by YOLO'
        if verbose:
            print(f"    ✗ No TVs detected in {len(image_paths)} images")
        return result

    # Run VLM on YOLO-positive images
    for detection in tv_detections:
        tier, cost = _classify_with_vlm(detection['path'])
        result['cost'] += cost

        if tier in ('PROSPECT', 'SUSPECT'):
            result['tier'] = tier
            result['evidence_photo_location'] = detection['path']
            result['yolo_confidence'] = detection['confidence']
            result['vlm_confidence'] = 'high' if tier == 'PROSPECT' else 'medium'
            result['evidence_description'] = f"TV detected in corporate space (YOLO: {detection['confidence']:.2f})"
            result['source_url'] = images[0].get('url', '')  # First image source
            result['space_type'] = 'corporate_office'
            result['tv_powered_on'] = (tier == 'PROSPECT')

            if verbose:
                marker = "✓" if tier == "PROSPECT" else "?"
                print(f"    {marker} {tier} | YOLO {detection['confidence']:.2f}, VLM confirmed")

            return result

    # VLM rejected all YOLO detections
    result['evidence_description'] = f'{len(tv_detections)} YOLO detections, all rejected by VLM'
    result['cost'] = sum(0.02 for _ in tv_detections)  # Approximate VLM cost

    if verbose:
        print(f"    ✗ {len(tv_detections)} YOLO hits, VLM rejected all")

    return result


def _search_hq_images(company_name: str) -> list:
    """Search for HQ interior images via SerpAPI."""
    queries = [
        f"{company_name} headquarters inside",
        f"{company_name} employee cafeteria",
        f"{company_name} office breakroom"
    ]

    images = []
    for query in queries:
        try:
            params = {
                "engine": "google_images",
                "q": query,
                "api_key": SERPAPI_API_KEY,
                "num": 10
            }

            response = requests.get("https://serpapi.com/search", params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                for img in data.get("images_results", [])[:5]:
                    images.append({
                        "url": img.get("original"),
                        "query": query
                    })
        except:
            continue

    return images


def _download_image(url: str, save_path: Path) -> Optional[str]:
    """Download and save image with correct extension."""
    try:
        response = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        if response.status_code == 200:
            # Detect actual image type
            content_type = response.headers.get('Content-Type', '').lower()

            if 'webp' in content_type or response.content[:4] == b'RIFF':
                save_path = Path(save_path).with_suffix('.webp')
            elif 'png' in content_type or response.content[:8] == b'\x89PNG\r\n\x1a\n':
                save_path = Path(save_path).with_suffix('.png')
            elif 'gif' in content_type or response.content[:6] in [b'GIF87a', b'GIF89a']:
                save_path = Path(save_path).with_suffix('.gif')
            else:
                save_path = Path(save_path).with_suffix('.jpg')

            with open(save_path, 'wb') as f:
                f.write(response.content)
            return str(save_path)
    except:
        pass
    return None


def _run_yolo_batch(image_paths: list) -> list:
    """Run YOLO on batch of images, return those with TV detected."""
    yolo_model = _get_yolo_model()
    tv_images = []

    for img_path in image_paths:
        try:
            results = yolo_model(img_path, verbose=False)
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    cls_id = int(box.cls[0])
                    class_name = yolo_model.names[cls_id]
                    conf = float(box.conf[0])

                    if class_name == 'tv' and conf >= 0.3:
                        tv_images.append({
                            'path': img_path,
                            'confidence': conf,
                            'class': class_name
                        })
                        break
        except:
            continue

    return tv_images


def _classify_with_vlm(image_path: str) -> tuple:
    """Classify image with VLM. Returns (tier, cost)."""
    try:
        with open(image_path, 'rb') as f:
            image_data = base64.standard_b64encode(f.read()).decode('utf-8')

        # Determine media type
        ext = Path(image_path).suffix.lower()
        media_type = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }.get(ext, 'image/jpeg')

        client = _get_anthropic_client()
        response = client.messages.create(
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
                        "text": """Is this a corporate office space (breakroom, cafeteria, lobby, waiting area) with a TV/display visible and likely powered on?

Reply with ONE of:
- PROSPECT: Corporate space, TV visible and appears powered on
- SUSPECT: Corporate space with TV but unclear if powered on
- REJECTED: Not corporate space OR no TV OR clearly staff-only area"""
                    }
                ]
            }]
        )

        result = response.content[0].text.strip().upper()
        # Haiku 5.5 pricing: $0.25/MTok input, $1.25/MTok output
        cost = (response.usage.input_tokens * 0.25 + response.usage.output_tokens * 1.25) / 1_000_000

        if result.startswith('PROSPECT'):
            return 'PROSPECT', cost
        elif result.startswith('SUSPECT'):
            return 'SUSPECT', cost
        else:
            return 'REJECTED', cost

    except Exception as e:
        return 'ERROR', 0


def run_batch(accounts: list[dict], verbose: bool = True) -> list[dict]:
    """Run pipeline for a list of accounts. Returns list of evidence records."""
    results = []
    total = len(accounts)

    evidence_dir = Path("output/corporate_evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    for i, account in enumerate(accounts, 1):
        if verbose:
            print(f"[{i}/{total}] {account.get('account_name', '?')}")
        record = run_account(account, verbose=verbose, evidence_dir=evidence_dir)
        results.append(record)

    return results
