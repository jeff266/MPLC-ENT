"""Investigate Heartland Dental lookup failure"""
import json
from review_eval_set import DENTAL_OFFICES

print("="*80)
print("HEARTLAND DENTAL LOOKUP INVESTIGATION")
print("="*80)

# Find Heartland in eval set
for account in DENTAL_OFFICES:
    if 'heartland' in account['business_name'].lower():
        print(f"\nEval Set Entry:")
        print(f"  Business Name: {account['business_name']}")
        print(f"  Location: {account.get('location', 'NOT SPECIFIED')}")
        print(f"  Expected TV: {account['has_tv']}")
        break

# Check what was actually queried
print("\n\nQuerying Apify actors manually to diagnose...")
print("Need to check:")
print("1. Is 'Heartland Dental' + location resolving to a real place?")
print("2. Does the location have reviews on Google Maps?")
print("3. Is the business name format causing the miss?")

