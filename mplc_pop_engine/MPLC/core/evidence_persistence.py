#!/usr/bin/env python3
"""
Structured evidence persistence module
Saves detailed evidence records for every Prospect/Suspect account
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path

class EvidenceRecorder:
    """Records structured evidence for TV detection claims."""
    
    def __init__(self, output_dir="evidence_records"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.records = []
    
    def add_evidence(self, 
                    account_name,
                    channel,
                    tier,
                    evidence_photo_location,
                    evidence_description,
                    yolo_confidence,
                    vlm_confidence,
                    source_url,
                    space_type,
                    tv_powered_on,
                    cost,
                    vertical="Corporations",
                    additional_metadata=None):
        """
        Add a structured evidence record.
        
        Parameters:
        -----------
        account_name : str
            Company/account name
        channel : str
            'video', 'image', or 'text'
        tier : str
            'PROSPECT', 'SUSPECT', or 'REJECTED'
        evidence_photo_location : str
            File path or URL to saved image/frame
        evidence_description : str
            Plain-language description of what's visible
        yolo_confidence : float
            YOLO detection confidence (0-1), or None if not applicable
        vlm_confidence : str
            VLM-stated confidence level ('high', 'medium', 'low', 'unclear')
        source_url : str
            Original source URL where evidence was found
        space_type : str
            Type of space ('employee_breakroom', 'cafeteria', 'gym', 
            'lobby', 'patient_waiting', 'service_lounge', etc.)
        tv_powered_on : bool
            Whether TV is confirmed powered on with visible content
        cost : float
            Total cost spent on this account across all channels
        vertical : str
            Business vertical ('Corporations', 'Dental', 'Auto', etc.)
        additional_metadata : dict
            Any additional metadata specific to this evidence
        """
        
        record = {
            'account_name': account_name,
            'channel': channel,
            'tier': tier,
            'vertical': vertical,
            'evidence': {
                'photo_location': evidence_photo_location,
                'description': evidence_description,
                'source_url': source_url
            },
            'confidence': {
                'yolo_detection': yolo_confidence,
                'vlm_assessment': vlm_confidence
            },
            'space_classification': {
                'type': space_type,
                'tv_powered_on': tv_powered_on
            },
            'cost': {
                'total_account_cost': cost
            },
            'metadata': {
                'timestamp': datetime.now().isoformat(),
                'evidence_id': self._generate_evidence_id(account_name, source_url),
                **(additional_metadata or {})
            }
        }
        
        self.records.append(record)
        return record
    
    def _generate_evidence_id(self, account_name, source_url):
        """Generate unique evidence ID from account name and source."""
        unique_string = f"{account_name}_{source_url}_{datetime.now().isoformat()}"
        return hashlib.md5(unique_string.encode()).hexdigest()[:12]
    
    def save(self, filename=None):
        """Save all evidence records to JSON file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"evidence_records_{timestamp}.json"
        
        output_path = self.output_dir / filename
        
        with open(output_path, 'w') as f:
            json.dump({
                'summary': {
                    'total_accounts': len(set(r['account_name'] for r in self.records)),
                    'total_evidence_items': len(self.records),
                    'by_tier': {
                        'PROSPECT': len([r for r in self.records if r['tier'] == 'PROSPECT']),
                        'SUSPECT': len([r for r in self.records if r['tier'] == 'SUSPECT']),
                        'REJECTED': len([r for r in self.records if r['tier'] == 'REJECTED'])
                    },
                    'by_channel': {
                        'video': len([r for r in self.records if r['channel'] == 'video']),
                        'image': len([r for r in self.records if r['channel'] == 'image']),
                        'text': len([r for r in self.records if r['channel'] == 'text'])
                    },
                    'total_cost': sum(r['cost']['total_account_cost'] for r in self.records)
                },
                'records': self.records
            }, f, indent=2)
        
        return str(output_path)
    
    def get_by_tier(self, tier):
        """Get all records for a specific tier."""
        return [r for r in self.records if r['tier'] == tier]
    
    def get_by_account(self, account_name):
        """Get all evidence records for a specific account."""
        return [r for r in self.records if r['account_name'] == account_name]


# Example usage
if __name__ == '__main__':
    # Create recorder
    recorder = EvidenceRecorder()
    
    # Add a PROSPECT evidence record (corporate)
    recorder.add_evidence(
        account_name="Costco Wholesale",
        channel="image",
        tier="PROSPECT",
        evidence_photo_location="image_evidence/costco/image_009.jpg",
        evidence_description="Employee breakroom with wall-mounted TV powered on, displaying news broadcast. Multiple dining tables and industrial warehouse ceiling visible.",
        yolo_confidence=0.769,
        vlm_confidence="high",
        source_url="https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRWnlyYitFlzj-gka24kRlTVYWezXysawkFPU11EdVidQ&s=10",
        space_type="employee_breakroom",
        tv_powered_on=True,
        cost=0.0237,
        vertical="Corporations"
    )
    
    # Add a SUSPECT evidence record (corporate lobby - wrong space type)
    recorder.add_evidence(
        account_name="TJX Companies",
        channel="image",
        tier="SUSPECT",
        evidence_photo_location="image_evidence/tjx/image_018.jpg",
        evidence_description="Corporate lobby with two-story atrium, reception desk, and TV displaying content. Space is visitor-facing, not employee-only.",
        yolo_confidence=0.411,
        vlm_confidence="medium",
        source_url="https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSvF6S-V4VutG0IbphCBUMXtykUSfx29sPEdFZofN9Dug&s=10",
        space_type="lobby_reception",
        tv_powered_on=True,
        cost=0.0284,
        vertical="Corporations"
    )
    
    # Save to file
    output_file = recorder.save()
    print(f"Evidence records saved to: {output_file}")
    
    # Example: retrieve all PROSPECT records
    prospects = recorder.get_by_tier('PROSPECT')
    print(f"\nFound {len(prospects)} PROSPECT records")

