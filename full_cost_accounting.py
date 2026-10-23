#!/usr/bin/env python3
"""
Full cost accounting for all 10 accounts across all channels
"""

import json
import glob

print("="*70)
print("FULL COST ACCOUNTING: 10-ACCOUNT CORPORATE VALIDATION")
print("="*70)

# Load video results
with open('corporation_validation_results.json', 'r') as f:
    video_results = json.load(f)

# Load image results
with open('image_evidence/results.json', 'r') as f:
    image_results = json.load(f)

# Video channel costs
print("\nCHANNEL 1: FACILITY VIDEO")
print("-" * 70)

video_costs = []
for account in video_results:
    vlm_cost = account.get('total_vlm_cost', 0)
    video_costs.append({
        'account': account['company'],
        'download_cost': 0,  # yt-dlp is free
        'yolo_cost': 0,  # local processing
        'vlm_cost': vlm_cost,
        'total': vlm_cost
    })
    
    print(f"{account['company']:<40} VLM: ${vlm_cost:.4f}  Total: ${vlm_cost:.4f}")

video_total = sum(c['total'] for c in video_costs)
print(f"\nVideo Channel Total: ${video_total:.4f}")

# Image channel costs
print("\n\nCHANNEL 2: SERPAPI IMAGE SEARCH")
print("-" * 70)

# SerpAPI costs: ~4 queries per account (4 different search terms)
# Each Google Images search = 1 SerpAPI credit
# SerpAPI credits cost $0.005 per credit (standard plan)
SERPAPI_COST_PER_SEARCH = 0.005
SEARCHES_PER_ACCOUNT = 4

image_costs = []
for account in image_results:
    search_cost = SEARCHES_PER_ACCOUNT * SERPAPI_COST_PER_SEARCH
    yolo_cost = 0  # local processing
    vlm_cost = account.get('total_cost', 0)
    total = search_cost + vlm_cost
    
    image_costs.append({
        'account': account['company'],
        'search_cost': search_cost,
        'yolo_cost': yolo_cost,
        'vlm_cost': vlm_cost,
        'total': total
    })
    
    status = "✓" if account.get('coverage') else "✗"
    print(f"{account['company']:<40} {status} Search: ${search_cost:.4f}  VLM: ${vlm_cost:.4f}  Total: ${total:.4f}")

image_total = sum(c['total'] for c in image_costs)
print(f"\nImage Channel Total: ${image_total:.4f}")

# Grand totals
print("\n\n" + "="*70)
print("GRAND TOTALS")
print("="*70)

grand_total = video_total + image_total
accounts_tested = 10
cost_per_account = grand_total / accounts_tested

print(f"\nTotal Video Channel Cost:        ${video_total:.4f}")
print(f"Total Image Channel Cost:        ${image_total:.4f}")
print(f"──────────────────────────────────────────")
print(f"GRAND TOTAL (10 accounts):       ${grand_total:.4f}")
print(f"Cost per account:                ${cost_per_account:.4f}")

# Projections
print("\n\n" + "="*70)
print("PROJECTIONS")
print("="*70)

full_corp_list = 209  # MPLC's full mid-market corporate list
projected_total = cost_per_account * full_corp_list

print(f"\nFull corporate list size:        {full_corp_list} accounts")
print(f"Projected total cost:            ${projected_total:.2f}")
print(f"  (Video + Images channels)")

# Cost breakdown by component
print("\n\n" + "="*70)
print("COST BREAKDOWN BY COMPONENT")
print("="*70)

total_download = sum(c['download_cost'] for c in video_costs)
total_yolo = 0  # All YOLO is free (local)
total_search = sum(c['search_cost'] for c in image_costs)
total_vlm = video_total + sum(c['vlm_cost'] for c in image_costs)

print(f"\nVideo downloads (yt-dlp):        ${total_download:.4f}  (free)")
print(f"YOLO detection:                  ${total_yolo:.4f}  (free, local)")
print(f"SerpAPI image searches:          ${total_search:.4f}  ({SEARCHES_PER_ACCOUNT * len(image_results)} searches)")
print(f"VLM confirmations:               ${total_vlm:.4f}  (Anthropic)")
print(f"──────────────────────────────────────────")
print(f"TOTAL:                           ${grand_total:.4f}")

# Save to JSON
cost_data = {
    'accounts_tested': accounts_tested,
    'video_channel': {
        'accounts': video_costs,
        'total': round(video_total, 4)
    },
    'image_channel': {
        'accounts': image_costs,
        'total': round(image_total, 4)
    },
    'grand_total': round(grand_total, 4),
    'cost_per_account': round(cost_per_account, 4),
    'projection': {
        'full_corporate_list_size': full_corp_list,
        'projected_total_cost': round(projected_total, 2)
    }
}

with open('full_cost_accounting.json', 'w') as f:
    json.dump(cost_data, f, indent=2)

print(f"\n\nFull cost data saved to: full_cost_accounting.json")

