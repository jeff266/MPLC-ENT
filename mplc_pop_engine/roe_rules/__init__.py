"""
ROE (Rules of Engagement) Segmentation Rules

Pluggable per-vertical rules for SB/MM/ENT classification.
"""

from .base import ROERule, SegmentResult

__all__ = ['ROERule', 'SegmentResult']
