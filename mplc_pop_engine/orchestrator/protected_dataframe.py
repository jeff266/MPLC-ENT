"""
Runtime-enforced wrapper that prevents bypassing Stage A protection filtering.
"""

import pandas as pd


class ProtectedDataFrame:
    """
    Wrapper that can ONLY be created by Stage A protection filter.

    Attempting to construct directly raises RuntimeError, preventing
    accidental processing of unprotected account data.

    This is runtime enforcement - not just type hints.
    """

    _stage_a_token = object()  # Private singleton token

    def __init__(self, df: pd.DataFrame, token: object):
        if token is not self._stage_a_token:
            raise RuntimeError(
                "ProtectedDataFrame can only be created by stage_a_protection.run_protection_filter(). "
                "You cannot bypass Stage A protection - all accounts must be filtered first."
            )
        self._df = df.copy()
        self._verified = True

    def get_dataframe(self) -> pd.DataFrame:
        """
        Access underlying DataFrame after verification.

        Returns a copy to prevent modification of the protected data.
        """
        return self._df.copy()

    @property
    def shape(self):
        """Passthrough to underlying DataFrame shape."""
        return self._df.shape

    def __len__(self):
        """Passthrough to underlying DataFrame length."""
        return len(self._df)

    @classmethod
    def _create_from_stage_a(cls, df: pd.DataFrame) -> 'ProtectedDataFrame':
        """
        Internal factory method - only callable from stage_a_protection.py.

        DO NOT call this directly from other code.
        """
        return cls(df, cls._stage_a_token)
