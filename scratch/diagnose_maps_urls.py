"""
Diagnose what URLs Maps images are coming from
Check the cost_tracker DB to see URLs logged for the dental test run
"""

import sqlite3
from pathlib import Path

# Connect to the most recent cost tracker DB
db_path = '/Users/jeffignacio/mplc_pop_engine/mplc_pipeline.db'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get the dental test run (mplc_run_20261022_003403)
run_id = 'mplc_run_20261022_003403'

print("="*80)
print(f"MAPS URL DIAGNOSIS - {run_id}")
print("="*80)
print()

# Check playwright requests for this run
cursor.execute("""
    SELECT url, account_id
    FROM playwright_requests
    WHERE run_id = ?
    ORDER BY timestamp DESC
""", (run_id,))

playwright_urls = cursor.fetchall()

print(f"Playwright requests: {len(playwright_urls)}")
for url, account_id in playwright_urls[:10]:
    print(f"  {account_id}: {url[:100]}")

print()
print("="*80)
print("Sample of images that were saved (from image cache):")
print("="*80)

# List some of the saved images from Oct 22 00:35
cache_dir = Path('/Users/jeffignacio/mplc_pop_engine/cache/images')
import os
from datetime import datetime

saved_images = []
for img_path in cache_dir.glob('*.png'):
    mtime = os.path.getmtime(img_path)
    if datetime.fromtimestamp(mtime).strftime('%H:%M') == '00:35':
        saved_images.append(img_path)

print(f"\nFound {len(saved_images)} PNG images saved at 00:35")
print("\nThese are the images YOLO detected 'keyboard' in (map tiles)")
print("Need to add URL filters to skip these in Playwright response handler")

conn.close()
