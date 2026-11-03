#!/usr/bin/env python3
"""
Explicit vertical-to-enricher mapping.

Only verticals with verified, synced enrichers are mapped.
Unmapped verticals are held back (UNRESOLVED treatment).
"""

# Verified enrichers (confirmed via MD5 sync to droplets)
VERIFIED_ENRICHERS = {
    'healthcare': 'healthcare_unified.py',  # MD5: 068a3601425591137667e304697245e3
    'corporate': 'corporate_fixed.py',      # MD5: 8d7fc759c0c1308f3caedab1525411ca
}

# Explicit vertical → enricher mapping
# Only includes verticals with confirmed enricher coverage
VERTICAL_ROUTING = {
    # Healthcare verticals
    'Health_Care_Centers': 'healthcare',
    'Doctors': 'healthcare',
    'Physicians_Clinics': 'healthcare',
    'Hospitals_&_Physicians_Clinics': 'healthcare',
    'Medical_&_Surgical_Hospitals': 'healthcare',
    'Dental_Offices': 'healthcare',
    'Dentists': 'healthcare',

    # Corporate verticals (generic business/office spaces)
    'Activity_Centers': 'corporate',
    'Health_clubs': 'corporate',
    'Fitness_&_Dance_Facilities': 'corporate',
    'Campgrounds': 'corporate',
    'Education': 'corporate',
    'Government_and_Similar_Buildings_&_Services': 'corporate',
    'Short-term_Lodging': 'corporate',
    'Religious_Institutions': 'corporate',
    'Transportation': 'corporate',
    'Membership_Organizations': 'corporate',
    'Real_Estate': 'corporate',
    'Hospitality': 'corporate',
    'Commercial_Establishments_&_Waiting_Areas': 'corporate',
    'Seniors': 'corporate',
    'Amusement_Parks,_Arcades_&_Attractions': 'corporate',
    'Custom_Software_&_IT_Services': 'corporate',
    'Industrial_Machinery_&_Equipment': 'corporate',
    'Apparel_&_Accessories_Retail': 'corporate',
    'Accounting_Services': 'corporate',
    'Insurance': 'corporate',
    'Electronics': 'corporate',
    'Lodging_&_Resorts': 'corporate',
    'Security_Software': 'corporate',
    'Electricity,_Oil_&_Gas': 'corporate',
    'Information_&_Document_Management': 'corporate',
    'Repair_Services': 'corporate',
    'Banking': 'corporate',
    'Hair_Salons': 'corporate',
    'Medical_Devices_&_Equipment': 'corporate',
    'Pharmaceuticals': 'corporate',
    'HR_&_Staffing': 'corporate',
    'Food_&_Beverage': 'corporate',
    'Engineering_Software': 'corporate',
    'Cosmetics,_Beauty_Supply_&_Personal_Care_Products': 'corporate',
    'Sporting_&_Recreational_Equipment_Retail': 'corporate',
    'YMCA,_YWCA,_Boys_&_girl_clubs': 'corporate',
    'Commercial_&_Residential_Construction': 'corporate',
    'Customer_Relationship_Management_(CRM)_Software': 'corporate',
    'Supply_Chain_Management_(SCM)_Software': 'corporate',
    'Holding_Companies_&_Conglomerates': 'corporate',
    'Non-Profit_&_Charitable_Organizations': 'corporate',
    'Management_Consulting': 'corporate',
    'Vitamins,_Supplements_&_Health_Stores': 'corporate',
    'Waste_Treatment,_Environmental_Services_&_Recycling': 'corporate',
    'Barber_Shops_&_Beauty_Salons': 'corporate',
    'Office_Products_Retail_&_Distribution': 'corporate',
    'Animals_&_Livestock': 'corporate',
    'Furniture': 'corporate',
    'Gambling_&_Gaming': 'corporate',
    'Telephony_&_Wireless': 'corporate',
    'Commercial_Printing': 'corporate',
    'Multimedia_&_Graphic_Design': 'corporate',
    'Rail,_Bus_&_Taxi': 'corporate',
    'Blood_&_Organ_Banks': 'corporate',
    'Media_&_Communications': 'corporate',
    'Media_&_Internet': 'corporate',
    'Building_Materials': 'corporate',
    'Grocery_Retail': 'corporate',
    'Marine_Shipping_&_Transportation': 'corporate',
    'Libraries': 'corporate',
    'Research_&_Development': 'corporate',
    'Financial_Software': 'corporate',
    'Training': 'corporate',
    'Food_Service': 'corporate',
}

# Unmapped verticals (held back until enricher is ready)
UNMAPPED_VERTICALS = {
    # MDU - enricher exists but NOT fully synced (Droplet 1 stale)
    'Communal_Living_Facilities': 'UNRESOLVED - MDU enricher not synced to Droplet 1',

    # Restaurants/Bars - no verified enricher exists
    'Restaurants,_Clubs,_Pubs': 'UNRESOLVED - No verified enricher (text mining claimed but not found)',
    'Bars,_Restaurants': 'UNRESOLVED - No verified enricher (text mining claimed but not found)',

    # Auto - no production enricher
    'Car_Dealerships': 'UNRESOLVED - No production enricher (exploratory only)',
    'Auto_Dealerships': 'UNRESOLVED - No production enricher (exploratory only)',
    'Automobile_Dealers': 'UNRESOLVED - No production enricher (exploratory only)',
    'Automotive_Service_&_Collision_Repair': 'UNRESOLVED - No production enricher (exploratory only)',

    # Misc/catchall
    'Misc': 'UNRESOLVED - Unclear vertical classification',
    'MAP': 'UNRESOLVED - Unknown vertical type',
    'CLU': 'UNRESOLVED - Unknown vertical type',
}


def route_vertical(vertical: str) -> dict:
    """
    Route a vertical to an enricher.

    Args:
        vertical: Vertical name from CSV

    Returns:
        dict with 'enricher' (str or None) and 'status' ('mapped' or 'unresolved')
    """
    # Check explicit mapping
    if vertical in VERTICAL_ROUTING:
        enricher = VERTICAL_ROUTING[vertical]
        return {
            'enricher': enricher,
            'status': 'mapped',
            'reason': f'Routed to {enricher}'
        }

    # Check unmapped (held back)
    if vertical in UNMAPPED_VERTICALS:
        return {
            'enricher': None,
            'status': 'unresolved',
            'reason': UNMAPPED_VERTICALS[vertical]
        }

    # Unknown vertical (not in either list)
    return {
        'enricher': None,
        'status': 'unresolved',
        'reason': f'UNRESOLVED - Vertical \'{vertical}\' not in routing table'
    }


def get_routing_summary(verticals_with_counts: dict) -> dict:
    """
    Get routing summary for a set of verticals.

    Args:
        verticals_with_counts: {vertical_name: count}

    Returns:
        dict with enricher breakdown and unresolved counts
    """
    summary = {
        'healthcare': 0,
        'corporate': 0,
        'unresolved': 0,
        'unresolved_breakdown': {}
    }

    for vertical, count in verticals_with_counts.items():
        route = route_vertical(vertical)
        if route['status'] == 'mapped':
            enricher = route['enricher']
            summary[enricher] += count
        else:
            summary['unresolved'] += count
            summary['unresolved_breakdown'][vertical] = {
                'count': count,
                'reason': route['reason']
            }

    return summary


if __name__ == '__main__':
    # Test with 1,396-account batch breakdown
    import csv

    # Read actual batch
    with open('/Users/jeffignacio/mplc_pop_engine/pipeline_output_WEEKLY_RUN/2026-11-03_ALL_READY_batch.csv', 'r') as f:
        reader = csv.DictReader(f)
        verticals = {}
        for row in reader:
            v = row.get('Vertical', '')
            verticals[v] = verticals.get(v, 0) + 1

    summary = get_routing_summary(verticals)

    print("\n" + "="*80)
    print("VERTICAL ROUTING SUMMARY - 1,396 ACCOUNTS")
    print("="*80 + "\n")

    print(f"Healthcare: {summary['healthcare']} accounts")
    print(f"Corporate:  {summary['corporate']} accounts")
    print(f"Unresolved: {summary['unresolved']} accounts")
    print()

    if summary['unresolved'] > 0:
        print("="*80)
        print("UNRESOLVED BREAKDOWN:")
        print("="*80 + "\n")
        for vertical, info in sorted(summary['unresolved_breakdown'].items(), key=lambda x: -x[1]['count']):
            print(f"{info['count']:4d}  {vertical}")
            print(f"       Reason: {info['reason']}")
            print()

    total = summary['healthcare'] + summary['corporate'] + summary['unresolved']
    print("="*80)
    print(f"TOTAL: {total} accounts")
    print("="*80)
