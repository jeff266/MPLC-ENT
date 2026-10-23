#!/usr/bin/env python3
"""
Run facility video pipeline on real MPLC corporation customers.
Measures actual coverage rate on ground-truth positive accounts.
"""

import subprocess
import json
import os
import glob
import base64
import sys
from pathlib import Path

# Import config
sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import ANTHROPIC_API_KEY

try:
    from anthropic import Anthropic
    from ultralytics import YOLO
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

def search_youtube_video(company_name):
    """Search for facility tour video on YouTube."""
    search_terms = [
        f"{company_name} headquarters tour",
        f"{company_name} office tour",
        f"{company_name} facility tour",
        f"{company_name} campus tour",
        f"{company_name} HQ tour"
    ]
    
    for search_term in search_terms:
        try:
            # Use yt-dlp to search and get first video URL
            result = subprocess.run(
                ['yt-dlp', '--get-id', f'ytsearch1:{search_term}'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout.strip():
                video_id = result.stdout.strip()
                video_url = f'https://www.youtube.com/watch?v={video_id}'
                
                # Get video title
                title_result = subprocess.run(
                    ['yt-dlp', '--get-title', video_url],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                title = title_result.stdout.strip() if title_result.returncode == 0 else "Unknown"
                
                return {'url': video_url, 'title': title, 'search_term': search_term}
        except Exception as e:
            continue
    
    return None

def download_video(video_url, output_file):
    """Download video at max 480p."""
    try:
        subprocess.run(
            ['yt-dlp', '-f', 'bestvideo[height<=480]+bestaudio/best[height<=480]',
             '--merge-output-format', 'mp4', '-o', output_file, video_url],
            check=True,
            capture_output=True,
            timeout=300
        )
        return True
    except Exception as e:
        print(f"Download failed: {e}")
        return False

def extract_frames(video_file, frames_dir):
    """Extract frames using scene-change detection."""
    os.makedirs(frames_dir, exist_ok=True)
    
    try:
        subprocess.run(
            ['ffmpeg', '-i', video_file,
             '-vf', "select='gt(scene,0.15)'",
             '-vsync', 'vfr', f'{frames_dir}/frame_%03d.jpg', '-y'],
            check=True,
            capture_output=True,
            timeout=300
        )
        
        frames = sorted(glob.glob(f'{frames_dir}/*.jpg'))
        return frames
    except Exception as e:
        print(f"Frame extraction failed: {e}")
        return []

def yolo_detect_tvs(frames, conf_threshold=0.20):
    """Run YOLO detection on frames, flag those with TV/monitor."""
    model = YOLO('yolo11n.pt')
    flagged_frames = []
    
    for frame_path in frames:
        try:
            results = model(frame_path, conf=conf_threshold, verbose=False)
            
            for result in results:
                if result.boxes:
                    for box in result.boxes:
                        class_id = int(box.cls[0])
                        class_name = model.names[class_id]
                        confidence = float(box.conf[0])
                        
                        if class_name in ['tv', 'monitor', 'laptop']:
                            flagged_frames.append({
                                'frame': frame_path,
                                'class': class_name,
                                'conf': confidence
                            })
                            break
        except Exception as e:
            continue
    
    return flagged_frames

def vlm_confirm_amenity_space(frame_path):
    """Use VLM to confirm if frame shows amenity space with TV."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    with open(frame_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')
    
    prompt = """Look at this image from a corporate facility video.

Does this show a TV or monitor in an AMENITY/COMMON area (breakroom, cafeteria, gym, lobby, waiting area)?

Reply with ONLY:
- YES if it clearly shows a TV/monitor in a shared employee amenity space
- NO if it's a conference room, personal office, or no TV visible
- UNSURE if you cannot tell

One word answer:"""
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        
        answer = response.content[0].text.strip().upper()
        cost = (response.usage.input_tokens * 0.003 / 1000) + (response.usage.output_tokens * 0.015 / 1000)
        
        return {
            'answer': answer,
            'cost': cost,
            'input_tokens': response.usage.input_tokens,
            'output_tokens': response.usage.output_tokens
        }
    except Exception as e:
        return {'answer': 'ERROR', 'cost': 0, 'error': str(e)}

def run_pipeline_for_account(account):
    """Run complete pipeline for one account."""
    company_name = account['name']
    print(f"\n{'='*60}")
    print(f"Testing: {company_name}")
    print(f"{'='*60}")
    
    result = {
        'company': company_name,
        'website': account['website'],
        'video_found': False,
        'video_downloaded': False,
        'frames_extracted': 0,
        'yolo_detections': 0,
        'vlm_confirmations': 0,
        'total_vlm_cost': 0,
        'coverage': False
    }
    
    # Step 1: Search for video
    video_info = search_youtube_video(company_name)
    if not video_info:
        print(f"❌ No facility video found")
        return result
    
    result['video_found'] = True
    result['video_url'] = video_info['url']
    result['video_title'] = video_info['title']
    print(f"✓ Found video: {video_info['title']}")
    
    # Step 2: Download video
    video_file = f"corp_validation/{company_name.replace(' ', '_')}.mp4"
    os.makedirs("corp_validation", exist_ok=True)
    
    if not download_video(video_info['url'], video_file):
        print(f"❌ Video download failed")
        return result
    
    result['video_downloaded'] = True
    print(f"✓ Downloaded video")
    
    # Step 3: Extract frames
    frames_dir = f"corp_validation/{company_name.replace(' ', '_')}_frames"
    frames = extract_frames(video_file, frames_dir)
    result['frames_extracted'] = len(frames)
    
    if not frames:
        print(f"❌ No frames extracted")
        return result
    
    print(f"✓ Extracted {len(frames)} scene-change frames")
    
    # Step 4: YOLO detection
    flagged = yolo_detect_tvs(frames)
    result['yolo_detections'] = len(flagged)
    
    if not flagged:
        print(f"❌ No TV/monitor detections")
        return result
    
    print(f"✓ YOLO flagged {len(flagged)} frames")
    
    # Step 5: VLM confirmation (sample up to 10 flagged frames)
    sample_size = min(10, len(flagged))
    vlm_cost_total = 0
    confirmations = 0
    
    for detection in flagged[:sample_size]:
        vlm_result = vlm_confirm_amenity_space(detection['frame'])
        vlm_cost_total += vlm_result.get('cost', 0)
        
        if vlm_result['answer'] == 'YES':
            confirmations += 1
    
    result['vlm_confirmations'] = confirmations
    result['total_vlm_cost'] = round(vlm_cost_total, 4)
    result['coverage'] = confirmations > 0
    
    if confirmations > 0:
        print(f"✅ COVERAGE CONFIRMED - {confirmations} amenity space TV detections")
        print(f"   Total VLM cost: ${result['total_vlm_cost']:.4f}")
    else:
        print(f"❌ No amenity space TVs confirmed (VLM filtered all detections)")
    
    return result

# Main execution
if __name__ == '__main__':
    # Load corporation validation set
    with open('corporation_validation_set.json', 'r') as f:
        corporations = json.load(f)
    
    # Run pipeline on first 10 accounts
    test_accounts = corporations[:10]
    
    results = []
    for account in test_accounts:
        try:
            result = run_pipeline_for_account(account)
            results.append(result)
        except KeyboardInterrupt:
            print("\n\nStopping early...")
            break
        except Exception as e:
            print(f"ERROR processing {account['name']}: {e}")
            results.append({
                'company': account['name'],
                'website': account['website'],
                'error': str(e),
                'coverage': False
            })
    
    # Save results
    with open('corporation_validation_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    # Summary
    print(f"\n{'='*60}")
    print("VALIDATION SUMMARY")
    print(f"{'='*60}")
    
    total = len(results)
    covered = sum(1 for r in results if r.get('coverage', False))
    coverage_rate = (covered / total * 100) if total > 0 else 0
    
    total_vlm_cost = sum(r.get('total_vlm_cost', 0) for r in results)
    
    print(f"Accounts tested: {total}")
    print(f"Coverage confirmed: {covered}")
    print(f"Coverage rate: {coverage_rate:.1f}%")
    print(f"Total VLM cost: ${total_vlm_cost:.4f}")
    print(f"\nDetailed results saved to: corporation_validation_results.json")

