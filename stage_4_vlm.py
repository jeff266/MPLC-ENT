"""
Stage 4: VLM Confirmation with Anthropic (PAID - Minimize Volume)
Only called for images that passed YOLO detection
"""

import anthropic
import base64
import json
from typing import Dict, List, Optional
from pathlib import Path

import config
from cost_tracker import CostTracker


class VLMConfirmation:
    """Confirm public/shared space TVs using Anthropic Vision"""

    def __init__(self, tracker: CostTracker, run_id: str):
        self.tracker = tracker
        self.run_id = run_id
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def _encode_image(self, image_path: str) -> str:
        """Encode image to base64"""
        with open(image_path, 'rb') as f:
            return base64.standard_b64encode(f.read()).decode('utf-8')

    def _get_media_type(self, image_path: str) -> str:
        """Get media type from file extension"""
        ext = Path(image_path).suffix.lower()
        media_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.webp': 'image/webp',
            '.gif': 'image/gif'
        }
        return media_types.get(ext, 'image/jpeg')

    def analyze_image(self, image_path: str, image_url: str,
                     account_id: str, yolo_detections: List[str]) -> Dict:
        """
        Analyze image with Anthropic Vision API.

        Returns: {
            tv_present: bool,
            room_type: str,
            public_facing: bool,
            confidence: int (0-100),
            reasoning: str
        }
        """
        # Check circuit breaker BEFORE making call
        should_continue, reason = self.tracker.check_circuit_breaker(self.run_id)
        if not should_continue:
            raise RuntimeError(f"Circuit breaker tripped: {reason}")

        # Encode image
        try:
            image_b64 = self._encode_image(image_path)
            media_type = self._get_media_type(image_path)
        except Exception as e:
            return {
                'tv_present': None,
                'room_type': 'error',
                'public_facing': False,
                'confidence': 0,
                'reasoning': f"Error encoding image: {e}",
                'error': True
            }

        # Construct prompt
        prompt = f"""An object detection system flagged this image as potentially containing a screen-shaped object (TV).
Objects detected: {', '.join(yolo_detections)}

Analyze this image and determine:

1. Is there a TV or large display screen visible in this image?
2. Based on the surrounding furniture, layout, and context, does this appear to be:
   - A public or shared space for group viewing (lobby, waiting room, cafeteria, gym, break room, bar/restaurant, etc.)
   - OR personal equipment (individual office monitor, desk setup, signage, etc.)

3. Your confidence level in this assessment (0-100)

IMPORTANT: If the image is genuinely ambiguous or unclear, answer "unclear" rather than guessing.

Respond with ONLY valid JSON in this exact format:
{{
  "tv_present": true/false,
  "room_type": "lobby" | "waiting_room" | "cafeteria" | "gym" | "break_room" | "bar_restaurant" | "office" | "signage" | "unclear",
  "public_facing": true/false,
  "confidence": 0-100,
  "reasoning": "Brief explanation of your assessment"
}}"""

        try:
            # Make API call
            message = self.client.messages.create(
                model=config.VLM_MODEL,
                max_tokens=500,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }]
            )

            # Extract tokens for cost tracking
            tokens_in = message.usage.input_tokens
            tokens_out = message.usage.output_tokens

            # Log cost BEFORE using result
            self.tracker.log_anthropic_call(
                account_id=account_id,
                stage="stage_4_vlm",
                model=config.VLM_MODEL,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                result_status="success"
            )

            # Parse response
            response_text = message.content[0].text

            # Clean up response (remove markdown code blocks if present)
            response_text = response_text.strip()
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                response_text = '\n'.join(lines[1:-1])

            result = json.loads(response_text)

            # Add metadata
            result['image_url'] = image_url
            result['model'] = config.VLM_MODEL
            result['tokens_used'] = tokens_in + tokens_out

            return result

        except json.JSONDecodeError as e:
            return {
                'tv_present': None,
                'room_type': 'error',
                'public_facing': False,
                'confidence': 0,
                'reasoning': f"Failed to parse JSON response: {e}",
                'error': True,
                'raw_response': response_text if 'response_text' in locals() else None
            }

        except Exception as e:
            return {
                'tv_present': None,
                'room_type': 'error',
                'public_facing': False,
                'confidence': 0,
                'reasoning': f"API error: {e}",
                'error': True
            }

    def analyze_batch(self, yolo_results: List[Dict], account_id: str) -> List[Dict]:
        """
        Analyze multiple images that passed YOLO.
        Returns results for each image.
        """
        vlm_results = []

        for yolo_result in yolo_results:
            image_path = yolo_result['image_path']
            image_url = yolo_result['image_url']
            detections = [d['class'] for d in yolo_result['detections']]

            # Analyze with VLM
            result = self.analyze_image(
                image_path=image_path,
                image_url=image_url,
                account_id=account_id,
                yolo_detections=detections
            )

            vlm_results.append(result)

            # Small delay between API calls
            import time
            time.sleep(0.5)

        return vlm_results


if __name__ == "__main__":
    # Test VLM confirmation
    from cost_tracker import CostTracker
    from datetime import datetime

    tracker = CostTracker("test_vlm.db")
    run_id = f"test_vlm_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    tracker.create_run(run_id, max_cost_usd=1.0, max_serper_credits=10, accounts_total=1)

    vlm = VLMConfirmation(tracker, run_id)

    # Test with sample image (would need real path)
    test_yolo_results = [
        # {
        #     'image_url': 'http://example.com/image.jpg',
        #     'image_path': '/path/to/cached/image.jpg',
        #     'detections': [
        #         {'class': 'tv', 'confidence': 0.85},
        #         {'class': 'couch', 'confidence': 0.75}
        #     ]
        # }
    ]

    if test_yolo_results:
        results = vlm.analyze_batch(test_yolo_results, "001TEST123")

        print("\n" + "=" * 80)
        print("VLM Confirmation Test Results")
        print("=" * 80)

        for result in results:
            print(f"\n{result.get('image_url', 'N/A')}")
            print(f"  TV present: {result.get('tv_present')}")
            print(f"  Room type: {result.get('room_type')}")
            print(f"  Public facing: {result.get('public_facing')}")
            print(f"  Confidence: {result.get('confidence')}%")
            print(f"  Reasoning: {result.get('reasoning', 'N/A')}")

        totals = tracker.get_run_totals(run_id)
        print(f"\nTotal cost: ${totals['total_anthropic_cost']:.4f}")
        print(f"Tokens used: {totals['total_tokens_input'] + totals['total_tokens_output']}")
    else:
        print("No test images provided. Add YOLO results to test.")

    tracker.complete_run(run_id)
    tracker.close()
