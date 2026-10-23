#!/usr/bin/env python3
"""
Channel 2: Widened text proxy vocabulary search
Company websites + Glassdoor benefits pages for: cafeteria, gym, fitness center, lobby, entertainment
Test on 4 remaining uncovered accounts
"""

import requests
import json
import re
import sys
from bs4 import BeautifulSoup

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import SERPER_API_KEY

# 4 remaining uncovered accounts (not found by video or images)
UNCOVERED_ACCOUNTS = [
    {"name": "TJX Companies", "website": "www.tjx.com"},
    {"name": "Tractor Supply", "website": "www.tractorsupply.com"},
    {"name": "Costco Wholesale", "website": "www.costco.com"},
    {"name": "Nutanix", "website": "www.nutanix.com"}
]

# Widened vocabulary for amenity spaces
PROXY_VOCABULARY = [
    "cafeteria",
    "breakroom",
    "break room", 
    "gym",
    "fitness center",
    "fitness room",
    "lobby",
    "employee lounge",
    "recreation room",
    "game room",
    "entertainment area",
    "common area"
]

def search_company_website(company_name, website):
    """Search company website for amenity vocabulary."""
    
    # Use Serper to search company website for amenity terms
    amenity_mentions = {}
    
    for term in PROXY_VOCABULARY:
        try:
            # Search: site:company.com "amenity term"
            domain = website.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]
            query = f'site:{domain} "{term}"'
            
            params = {
                "q": query,
                "api_key": SERPER_API_KEY,
                "num": 5
            }
            
            response = requests.get("https://google.serper.dev/search", params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("organic", [])
                
                if results:
                    amenity_mentions[term] = len(results)
                    
        except Exception as e:
            continue
    
    return amenity_mentions

def search_glassdoor_benefits(company_name):
    """Search Glassdoor for amenity mentions in benefits/perks."""
    
    try:
        # Search: "Company Name" glassdoor cafeteria OR gym OR "fitness center"
        query = f'"{company_name}" glassdoor (cafeteria OR gym OR "fitness center" OR breakroom OR lobby)'
        
        params = {
            "q": query,
            "api_key": SERPER_API_KEY,
            "num": 10
        }
        
        response = requests.get("https://google.serper.dev/search", params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            results = data.get("organic", [])
            
            # Count amenity vocabulary mentions in snippets
            amenity_counts = {}
            
            for result in results:
                snippet = result.get("snippet", "").lower()
                title = result.get("title", "").lower()
                full_text = snippet + " " + title
                
                for term in PROXY_VOCABULARY:
                    if term.lower() in full_text:
                        amenity_counts[term] = amenity_counts.get(term, 0) + 1
            
            return amenity_counts
    except Exception as e:
        return {}
    
    return {}

def test_account(account):
    """Test one account with text proxy vocabulary."""
    company_name = account['name']
    website = account['website']
    
    print(f"\n{'='*60}")
    print(f"Testing: {company_name}")
    print(f"{'='*60}")
    
    result = {
        'company': company_name,
        'website': website,
        'website_amenities': {},
        'glassdoor_amenities': {},
        'total_amenity_mentions': 0,
        'coverage': False
    }
    
    # Search company website
    website_mentions = search_company_website(company_name, website)
    result['website_amenities'] = website_mentions
    
    if website_mentions:
        print(f"✓ Found amenity mentions on website: {website_mentions}")
    else:
        print(f"  No amenity mentions on company website")
    
    # Search Glassdoor
    glassdoor_mentions = search_glassdoor_benefits(company_name)
    result['glassdoor_amenities'] = glassdoor_mentions
    
    if glassdoor_mentions:
        print(f"✓ Found amenity mentions on Glassdoor: {glassdoor_mentions}")
    else:
        print(f"  No amenity mentions on Glassdoor")
    
    # Count total unique amenity mentions
    all_amenities = set(website_mentions.keys()) | set(glassdoor_mentions.keys())
    result['total_amenity_mentions'] = len(all_amenities)
    
    # Coverage if we found 2+ different amenity types (strengthens signal)
    result['coverage'] = len(all_amenities) >= 2
    
    if result['coverage']:
        print(f"✅ COVERAGE CONFIRMED - {len(all_amenities)} amenity types mentioned")
    else:
        print(f"❌ Insufficient amenity evidence ({len(all_amenities)} types)")
    
    return result

# Main execution
if __name__ == '__main__':
    results = []
    
    for account in UNCOVERED_ACCOUNTS:
        try:
            result = test_account(account)
            results.append(result)
        except KeyboardInterrupt:
            print("\n\nStopping early...")
            break
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                'company': account['name'],
                'website': account['website'],
                'error': str(e),
                'coverage': False
            })
    
    # Save results
    with open('text_proxy_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    # Summary
    print(f"\n{'='*60}")
    print("CHANNEL 2: Text Proxy Vocabulary Results")
    print(f"{'='*60}")
    
    total = len(results)
    covered = sum(1 for r in results if r.get('coverage', False))
    coverage_rate = (covered / total * 100) if total > 0 else 0
    
    print(f"Accounts tested: {total}")
    print(f"Additional coverage: {covered}")
    print(f"Coverage rate: {coverage_rate:.1f}%")
    print(f"\nCumulative coverage (Video + Images + Text): {6 + covered}/10 = {(6 + covered)*10:.1f}%")

