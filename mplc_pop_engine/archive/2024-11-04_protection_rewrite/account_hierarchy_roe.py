"""
Account Hierarchy Rules of Engagement for MPLC
Determines which accounts to process based on parent-child relationships
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple


class AccountHierarchyROE:
    """Apply ROE rules to account hierarchies"""

    def __init__(self, activity_window_days: int = 90):
        self.activity_window_days = activity_window_days
        self.cutoff_date = datetime.now() - timedelta(days=activity_window_days)

    def is_account_active(self, row: pd.Series) -> bool:
        """
        Check if account has activity within window.

        Activity indicators:
        - Last meeting date
        - Last email date
        - Last call date
        - Last modified date
        - Any task/event date
        """
        activity_fields = [
            'Last_Meeting_Date__c',
            'Last_Email_Date__c',
            'Last_Call_Date__c',
            'LastActivityDate',
            'LastModifiedDate'
        ]

        for field in activity_fields:
            if field in row and pd.notna(row[field]):
                try:
                    activity_date = pd.to_datetime(row[field])
                    if activity_date >= self.cutoff_date:
                        return True
                except:
                    continue

        return False

    def apply_hierarchy_roe(self, accounts_df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply parent-child ROE logic.

        Strategy: "Parent Protects Children with Bubble-Up"
        1. If parent is active → entire hierarchy stays
        2. If ANY child is active → entire hierarchy stays
        3. If entire hierarchy inactive → can be reassigned

        Returns DataFrame with ROE_Status column:
        - 'ACTIVE': Keep with current owner
        - 'INACTIVE': Available for reassignment
        - 'PROTECTED': Inactive but protected by parent/sibling
        """

        # Add ROE status column
        accounts_df['ROE_Status'] = 'UNKNOWN'
        accounts_df['ROE_Reason'] = ''

        # Separate accounts with and without parents
        has_parent = accounts_df['ParentId'].notna()
        parent_accounts = accounts_df[~has_parent].copy()
        child_accounts = accounts_df[has_parent].copy()

        # Process parent accounts first
        for idx, parent in parent_accounts.iterrows():
            parent_id = parent['18 Digit Account ID']
            parent_active = self.is_account_active(parent)

            # Find all children of this parent
            children = child_accounts[child_accounts['ParentId'] == parent_id]

            if parent_active:
                # Parent active → protect entire hierarchy
                accounts_df.loc[idx, 'ROE_Status'] = 'ACTIVE'
                accounts_df.loc[idx, 'ROE_Reason'] = 'Parent account has recent activity'

                # Protect all children
                child_mask = (accounts_df['ParentId'] == parent_id)
                accounts_df.loc[child_mask, 'ROE_Status'] = 'PROTECTED'
                accounts_df.loc[child_mask, 'ROE_Reason'] = 'Protected by active parent account'

            else:
                # Parent inactive - check if ANY child is active
                any_child_active = any(self.is_account_active(child) for _, child in children.iterrows())

                if any_child_active:
                    # Child active → protect entire hierarchy
                    accounts_df.loc[idx, 'ROE_Status'] = 'PROTECTED'
                    accounts_df.loc[idx, 'ROE_Reason'] = 'Protected by active child location(s)'

                    # Mark children
                    for child_idx, child in children.iterrows():
                        if self.is_account_active(child):
                            accounts_df.loc[child_idx, 'ROE_Status'] = 'ACTIVE'
                            accounts_df.loc[child_idx, 'ROE_Reason'] = 'Child account has recent activity'
                        else:
                            accounts_df.loc[child_idx, 'ROE_Status'] = 'PROTECTED'
                            accounts_df.loc[child_idx, 'ROE_Reason'] = 'Protected by active sibling location'
                else:
                    # Entire hierarchy inactive
                    accounts_df.loc[idx, 'ROE_Status'] = 'INACTIVE'
                    accounts_df.loc[idx, 'ROE_Reason'] = f'No activity in {self.activity_window_days} days'

                    child_mask = (accounts_df['ParentId'] == parent_id)
                    accounts_df.loc[child_mask, 'ROE_Status'] = 'INACTIVE'
                    accounts_df.loc[child_mask, 'ROE_Reason'] = f'No activity across account hierarchy'

        # Process orphan children (have ParentId but parent not in dataset)
        orphan_children = child_accounts[~child_accounts['ParentId'].isin(parent_accounts['18 Digit Account ID'])]

        for idx, child in orphan_children.iterrows():
            if self.is_account_active(child):
                accounts_df.loc[idx, 'ROE_Status'] = 'ACTIVE'
                accounts_df.loc[idx, 'ROE_Reason'] = 'Child account active (parent not in dataset)'
            else:
                accounts_df.loc[idx, 'ROE_Status'] = 'INACTIVE'
                accounts_df.loc[idx, 'ROE_Reason'] = 'Child account inactive (parent not in dataset)'

        return accounts_df

    def get_processable_accounts(self, accounts_df: pd.DataFrame) -> pd.DataFrame:
        """
        Get accounts that should be processed for MPLC PoP detection.

        For MPLC, we want to process:
        - All ACTIVE accounts (current owner working them)
        - All INACTIVE accounts (available for prospecting/reassignment)
        - PROTECTED accounts only if they're parent accounts
          (child locations don't need separate PoP if parent is being worked)
        """

        # Apply ROE logic
        accounts_with_roe = self.apply_hierarchy_roe(accounts_df)

        # Filter processable accounts
        processable = accounts_with_roe[
            (accounts_with_roe['ROE_Status'].isin(['ACTIVE', 'INACTIVE'])) |
            ((accounts_with_roe['ROE_Status'] == 'PROTECTED') &
             (accounts_with_roe['ParentId'].isna()))  # Parent accounts only
        ].copy()

        return processable

    def generate_roe_report(self, accounts_df: pd.DataFrame) -> Dict:
        """Generate summary report of ROE decisions"""

        accounts_with_roe = self.apply_hierarchy_roe(accounts_df)

        report = {
            'total_accounts': len(accounts_with_roe),
            'parent_accounts': len(accounts_with_roe[accounts_with_roe['ParentId'].isna()]),
            'child_accounts': len(accounts_with_roe[accounts_with_roe['ParentId'].notna()]),
            'roe_status_breakdown': accounts_with_roe['ROE_Status'].value_counts().to_dict(),
            'processable_accounts': len(self.get_processable_accounts(accounts_df)),
            'protected_by_parent': len(accounts_with_roe[
                accounts_with_roe['ROE_Reason'].str.contains('active parent', case=False, na=False)
            ]),
            'protected_by_sibling': len(accounts_with_roe[
                accounts_with_roe['ROE_Reason'].str.contains('sibling', case=False, na=False)
            ]),
            'inactive_hierarchies': len(accounts_with_roe[
                (accounts_with_roe['ROE_Status'] == 'INACTIVE') &
                (accounts_with_roe['ParentId'].isna())
            ])
        }

        return report


if __name__ == "__main__":
    # Example usage
    import numpy as np

    # Create sample account hierarchy
    sample_data = {
        '18 Digit Account ID': [
            'PAR001HILTON0001',  # Parent
            'CHD001HILTONSF01',  # Child (active)
            'CHD002HILTONNY01',  # Child (inactive)
            'PAR002MARRIOTT01',  # Parent (inactive)
            'CHD003MARRIOTLA01',  # Child (inactive)
        ],
        'Account Name': [
            'Hilton Hotels Corporation',
            'Hilton San Francisco',
            'Hilton New York',
            'Marriott International',
            'Marriott Los Angeles'
        ],
        'ParentId': [
            None,
            'PAR001HILTON0001',
            'PAR001HILTON0001',
            None,
            'PAR002MARRIOTT01'
        ],
        'LastActivityDate': [
            '2024-08-15',  # 67 days ago (inactive)
            '2024-10-01',  # 20 days ago (active)
            '2024-06-01',  # 142 days ago (inactive)
            '2024-05-01',  # 173 days ago (inactive)
            '2024-07-01',  # 112 days ago (inactive)
        ],
        'Segment': ['ENT', 'ENT', 'ENT', 'ENT', 'MM']
    }

    df = pd.DataFrame(sample_data)

    # Apply ROE
    roe = AccountHierarchyROE(activity_window_days=90)
    result = roe.apply_hierarchy_roe(df)

    print("\n" + "="*80)
    print("ACCOUNT HIERARCHY ROE RESULTS")
    print("="*80)

    for _, row in result.iterrows():
        indent = "  └─ " if pd.notna(row['ParentId']) else ""
        print(f"\n{indent}{row['Account Name']}")
        print(f"{indent}  Status: {row['ROE_Status']}")
        print(f"{indent}  Reason: {row['ROE_Reason']}")

    # Generate report
    report = roe.generate_roe_report(df)

    print("\n" + "="*80)
    print("ROE SUMMARY REPORT")
    print("="*80)
    for key, value in report.items():
        print(f"{key}: {value}")

    # Show processable accounts
    processable = roe.get_processable_accounts(df)
    print(f"\n\nProcessable for MPLC PoP Detection: {len(processable)} accounts")
    print(processable[['Account Name', 'ROE_Status', 'ROE_Reason']])
