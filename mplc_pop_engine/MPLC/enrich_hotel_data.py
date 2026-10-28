#!/usr/bin/env python3
"""
Hotel Data Enrichment

Combines:
1. 352 hospitality accounts (from ROE classification)
2. Franchisee data (from FDD database)
3. Operator data (from operator detector)
4. Room counts (from Serper search)

OUTPUT: Complete hotel dataset for inspection
"""

import csv
import json
import requests
import time
import os
from pathlib import Path

# Input files
HOSPITALITY_ACCOUNTS = "output/runs/hospitality_accounts_to_process_2026-10-23.csv"
FRANCHISEE_DB = "../verticals/hotels/output/hotel_franchisee_database_complete.csv"
OPERATOR_RESULTS = "../verticals/hotels/output/70_hotels_validated_20261026_161622.csv"
OUTPUT_FILE = "output/runs/hotels_enriched_with_franchisee_operator_2026-10-27.csv"

# Serper API
SERPER_API_KEY = os.getenv('SERPER_API_KEY', '')


def search_room_count(hotel_name: str, city: str, state: str) -> dict:
    """
    Search for hotel room count using Serper.

    Returns:
        {'room_count': int, 'source': str, 'confidence': str}
    """
    if not SERPER_API_KEY:
        return {'room_count': None, 'source': None, 'confidence': 'no_api_key'}

    query = f'"{hotel_name}" {city} {state} "rooms" OR "room hotel"'

    try:
        response = requests.post(
            'https://google.serper.dev/search',
            headers={
                'X-API-KEY': SERPER_API_KEY,
                'Content-Type': 'application/json'
            },
            json={'q': query, 'num': 5},
            timeout=10
        )

        if response.status_code != 200:
            return {'room_count': None, 'source': None, 'confidence': 'api_error'}

        data = response.json()

        # Search through results for room count
        import re
        room_pattern = r'(\d+)[\s\-]room'

        # Check organic results
        for result in data.get('organic', [])[:3]:
            snippet = result.get('snippet', '').lower()
            title = result.get('title', '').lower()
            text = snippet + ' ' + title

            match = re.search(room_pattern, text)
            if match:
                room_count = int(match.group(1))
                # Sanity check (hotels typically 20-2000 rooms)
                if 20 <= room_count <= 2000:
                    return {
                        'room_count': room_count,
                        'source': result.get('link', ''),
                        'confidence': 'high'
                    }

        # Check knowledge graph
        kg = data.get('knowledgeGraph', {})
        attributes = kg.get('attributes', {})
        for key, value in attributes.items():
            if 'room' in key.lower():
                match = re.search(r'\d+', str(value))
                if match:
                    room_count = int(match.group())
                    if 20 <= room_count <= 2000:
                        return {
                            'room_count': room_count,
                            'source': 'knowledge_graph',
                            'confidence': 'high'
                        }

        return {'room_count': None, 'source': None, 'confidence': 'not_found'}

    except Exception as e:
        print(f"  Error searching room count: {e}")
        return {'room_count': None, 'source': str(e), 'confidence': 'error'}


def normalize_hotel_name(name: str) -> str:
    """Normalize hotel name for matching."""
    name = name.lower()
    # Remove common suffixes
    name = name.replace(' hotel', '').replace(' inn', '').replace(' suites', '')
    name = name.replace(' resort', '').replace(' & spa', '')
    return name.strip()


def load_franchisee_data():
    """Load franchisee database."""
    franchisee_path = Path(__file__).parent / FRANCHISEE_DB

    if not franchisee_path.exists():
        print(f"Warning: Franchisee database not found: {franchisee_path}")
        return {}

    franchisee_map = {}
    with open(franchisee_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            hotel_name = row.get('hotel_name', '')
            if hotel_name:
                key = normalize_hotel_name(hotel_name)
                franchisee_map[key] = {
                    'franchisee': row.get('franchisee', ''),
                    'franchisee_source': row.get('franchisee_source', 'FDD')
                }

    print(f"Loaded {len(franchisee_map)} franchisee records")
    return franchisee_map


def load_operator_data():
    """Load operator detection results."""
    operator_path = Path(__file__).parent / OPERATOR_RESULTS

    if not operator_path.exists():
        print(f"Warning: Operator results not found: {operator_path}")
        return {}

    operator_map = {}
    with open(operator_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            hotel_name = row.get('hotel_name', '')
            if hotel_name:
                key = normalize_hotel_name(hotel_name)
                operator_map[key] = {
                    'operator': row.get('operator', ''),
                    'operator_source': row.get('operator_source', ''),
                    'operator_confidence': row.get('operator_confidence', ''),
                    'operator_evidence': row.get('operator_evidence', ''),
                    'operator_source_url': row.get('operator_source_url', '')
                }

    print(f"Loaded {len(operator_map)} operator records")
    return operator_map


def enrich_hotels():
    """Enrich hotel accounts with franchisee + operator + room count."""

    print("=" * 80)
    print("HOTEL DATA ENRICHMENT")
    print("=" * 80)

    # Load data
    accounts_path = Path(__file__).parent / HOSPITALITY_ACCOUNTS

    if not accounts_path.exists():
        print(f"ERROR: {HOSPITALITY_ACCOUNTS} not found")
        return

    with open(accounts_path, 'r') as f:
        reader = csv.DictReader(f)
        accounts = list(reader)

    print(f"\nInput: {len(accounts)} hospitality accounts")

    # Load enrichment data
    franchisee_map = load_franchisee_data()
    operator_map = load_operator_data()

    # Enrich accounts
    print("\n" + "=" * 80)
    print("ENRICHING ACCOUNTS")
    print("=" * 80)

    enriched = []
    stats = {
        'franchisee_found': 0,
        'operator_found': 0,
        'room_count_found': 0,
        'total': len(accounts)
    }

    for i, account in enumerate(accounts, 1):
        account_name = account['account_name']
        city = account.get('account_city', '')
        state = account.get('account_state', '')

        print(f"\n[{i}/{len(accounts)}] {account_name}")

        # Match franchisee
        key = normalize_hotel_name(account_name)
        franchisee_data = franchisee_map.get(key, {})

        if franchisee_data:
            account.update(franchisee_data)
            stats['franchisee_found'] += 1
            print(f"  ✅ Franchisee: {franchisee_data.get('franchisee', 'Unknown')}")
        else:
            account['franchisee'] = ''
            account['franchisee_source'] = ''
            print(f"  ❌ Franchisee: Not found")

        # Match operator
        operator_data = operator_map.get(key, {})

        if operator_data:
            account.update(operator_data)
            stats['operator_found'] += 1
            print(f"  ✅ Operator: {operator_data.get('operator', 'Unknown')}")
        else:
            account['operator'] = ''
            account['operator_source'] = ''
            account['operator_confidence'] = ''
            account['operator_evidence'] = ''
            account['operator_source_url'] = ''
            print(f"  ❌ Operator: Not found")

        # Search room count (only if we have API key and for first 50 to test)
        if SERPER_API_KEY and i <= 50:
            print(f"  🔍 Searching room count...", end=" ")
            room_data = search_room_count(account_name, city, state)
            account['room_count'] = room_data['room_count'] or ''
            account['room_count_source'] = room_data['source'] or ''
            account['room_count_confidence'] = room_data['confidence']

            if room_data['room_count']:
                stats['room_count_found'] += 1
                print(f"✅ {room_data['room_count']} rooms")
            else:
                print(f"❌ Not found")

            time.sleep(0.5)  # Rate limiting
        else:
            account['room_count'] = ''
            account['room_count_source'] = ''
            account['room_count_confidence'] = 'not_searched' if not SERPER_API_KEY else 'pending'

        enriched.append(account)

    # Save enriched data
    output_path = Path(__file__).parent / OUTPUT_FILE
    output_path.parent.mkdir(exist_ok=True, parents=True)

    # Define output fieldnames
    fieldnames = list(accounts[0].keys()) + [
        'franchisee', 'franchisee_source',
        'operator', 'operator_source', 'operator_confidence',
        'operator_evidence', 'operator_source_url',
        'room_count', 'room_count_source', 'room_count_confidence'
    ]

    # Remove duplicates while preserving order
    fieldnames = list(dict.fromkeys(fieldnames))

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched)

    # Summary
    print("\n" + "=" * 80)
    print("ENRICHMENT RESULTS")
    print("=" * 80)

    print(f"\nTotal Accounts: {stats['total']}")
    print(f"Franchisee Found: {stats['franchisee_found']} ({stats['franchisee_found']/stats['total']*100:.1f}%)")
    print(f"Operator Found: {stats['operator_found']} ({stats['operator_found']/stats['total']*100:.1f}%)")
    print(f"Room Count Found: {stats['room_count_found']} ({stats['room_count_found']/stats['total']*100:.1f}%)")

    print(f"\n✅ Enriched data saved: {output_path}")
    print(f"\nNext Steps:")
    print(f"1. Review the CSV to inspect franchisee + operator data")
    print(f"2. For room counts, either:")
    print(f"   - Add SERPER_API_KEY and re-run")
    print(f"   - Manually enrich room counts")
    print(f"   - Use STR database ($750/year)")

    return enriched


if __name__ == '__main__':
    enrich_hotels()
