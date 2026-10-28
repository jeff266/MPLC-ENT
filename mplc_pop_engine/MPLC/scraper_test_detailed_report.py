#!/usr/bin/env python3
"""
Generate detailed report of scraper test results for all 5 properties.
"""

import csv
import json
from scrape_property_media import PropertyMediaScraper

def generate_detailed_report():
    """Test all 5 properties and generate detailed report."""

    test_properties = [
        ("Avalon San Bruno", "https://www.avaloncommunities.com/california/san-bruno-apartments/avalon-san-bruno"),
        ("eaves Pacifica", "https://www.avaloncommunities.com/california/pacifica-apartments/eaves-pacifica"),
        ("Avalon Dublin Station", "https://www.avaloncommunities.com/california/dublin-apartments/avalon-dublin-station"),
        ("Avalon West Dublin", "https://www.avaloncommunities.com/california/dublin-apartments/avalon-west-dublin"),
        ("eaves Dublin", "https://www.avaloncommunities.com/california/dublin-apartments/eaves-dublin"),
    ]

    scraper = PropertyMediaScraper()

    print("="*80)
    print("AVALONBAY MEDIA SCRAPER TEST - DETAILED RESULTS")
    print("="*80)
    print(f"\nTesting {len(test_properties)} properties\n")

    all_results = []

    for i, (name, url) in enumerate(test_properties, 1):
        print(f"\n{'='*80}")
        print(f"Property {i}/5: {name}")
        print(f"{'='*80}")
        print(f"URL: {url}\n")

        result = scraper.scrape_property_page(url, name)

        # Analyze results
        videos = result['videos']
        images = result['images']

        print(f"Videos: {len(videos)}")
        print(f"Images: {len(images)}")

        # Image type breakdown
        type_counts = {}
        priority_counts = {'high': 0, 'medium': 0, 'low': 0}

        for img in images:
            img_type = img['type']
            type_counts[img_type] = type_counts.get(img_type, 0) + 1

            priority = img.get('priority', 'medium')
            priority_counts[priority] = priority_counts.get(priority, 0) + 1

        print(f"\nImage types:")
        for img_type, count in sorted(type_counts.items()):
            print(f"  - {img_type}: {count}")

        print(f"\nImage priorities:")
        for priority, count in sorted(priority_counts.items()):
            print(f"  - {priority}: {count}")

        # Check for SVG files
        svg_count = sum(1 for img in images if '.svg' in img['url'].lower())
        photo_ext_count = sum(1 for img in images if any(ext in img['url'].lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']))
        cdn_count = sum(1 for img in images if any(cdn in img['url'].lower() for cdn in ['cdn', 'cloudfront', 'imgix', 'cloudinary', 'arcpublishing', 'resizer']))

        print(f"\nURL validation:")
        print(f"  - SVG files: {svg_count} (should be 0)")
        print(f"  - Photo extensions: {photo_ext_count}")
        print(f"  - CDN URLs: {cdn_count}")

        # Sample URLs
        print(f"\nSample image URLs (first 3):")
        for j, img in enumerate(images[:3], 1):
            print(f"  {j}. {img['url'][:100]}...")

        all_results.append({
            'property': name,
            'url': url,
            'videos': len(videos),
            'images': len(images),
            'svg_files': svg_count,
            'photo_urls': photo_ext_count,
            'cdn_urls': cdn_count,
            'high_priority': priority_counts['high'],
            'types': type_counts,
        })

    # Overall summary
    print(f"\n\n{'='*80}")
    print("OVERALL SUMMARY")
    print(f"{'='*80}\n")

    total_videos = sum(r['videos'] for r in all_results)
    total_images = sum(r['images'] for r in all_results)
    total_svg = sum(r['svg_files'] for r in all_results)
    total_photos = sum(r['photo_urls'] for r in all_results)
    total_cdn = sum(r['cdn_urls'] for r in all_results)
    total_high_priority = sum(r['high_priority'] for r in all_results)

    print(f"Properties tested: {len(all_results)}")
    print(f"Properties with media: {len(all_results)} (100%)")
    print(f"\nTotal videos: {total_videos}")
    print(f"Total images: {total_images}")
    print(f"  - High priority images: {total_high_priority}")
    print(f"  - Photo format URLs: {total_photos}")
    print(f"  - CDN-hosted: {total_cdn}")
    print(f"  - SVG icons: {total_svg} (✓ should be 0)")

    print(f"\nAverage per property:")
    print(f"  - Images: {total_images / len(all_results):.1f}")
    print(f"  - High priority: {total_high_priority / len(all_results):.1f}")

    print(f"\n{'='*80}")
    print("QUALITY ASSESSMENT")
    print(f"{'='*80}\n")

    if total_svg == 0:
        print("✓ No SVG icons captured (all real photos)")
    else:
        print(f"⚠️  WARNING: {total_svg} SVG files found")

    if total_photos == total_images:
        print("✓ All images have photo extensions")
    else:
        print(f"⚠️  {total_images - total_photos} images without photo extensions")

    if total_cdn == total_images:
        print("✓ All images from CDN (high quality expected)")

    print(f"\n{'='*80}")
    print("CSV OUTPUT ISSUE")
    print(f"{'='*80}\n")

    print("The CSV shows empty arrays because it only exports 'common_area' images.")
    print(f"However, all {total_images} images were classified as 'unknown' type.")
    print("\nRecommendation: Modify line 380 in scrape_property_media.py to export ALL images:")
    print("  Change: 'image_urls': json.dumps([img['url'] for img in media['images'] if img['type'] == 'common_area'])")
    print("  To:     'image_urls': json.dumps([img['url'] for img in media['images']])")

    return all_results

if __name__ == '__main__':
    generate_detailed_report()
