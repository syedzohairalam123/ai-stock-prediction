"""
Normalization pipeline for Phase 21A

This package handles schema validation, normalization, deduplication, and event ordering
for esports data from external providers.
"""

from .pipeline import NormalizationPipeline
from .schemas import validate_game, validate_tournament, validate_match, validate_team, validate_player, validate_event

__all__ = [
    "NormalizationPipeline",
    "validate_game",
    "validate_tournament",
    "validate_match",
    "validate_team",
    "validate_player",
    "validate_event",
]
