"""Gem labels, auction types, and player-count-dependent setup rules."""

from enum import Enum
from types import MappingProxyType


# Five physical gem types and one sentinel for unspecified mission gems.
class GemType(Enum):
    BLUE_CIRCLE = 0
    GREEN_OVAL = 1
    PURPLE_TRIANGLE = 2
    YELLOW_SQUARE = 3
    PINK_PENTAGON = 4
    WILD_CARD = 5  # A mission requirement for unspecified colors, not a physical card.


# Auction types: treasure awards one or two gems; investments return the bid
# plus a fixed bonus at game end; loans provide coins that must be repaid.
class AuctionType(Enum):
    AUCTION = 0
    INVEST = 1
    LOAN = 2


# Color constraints for unspecified mission gems: matching colors, distinct
# colors, or pairs of matching colors.
class WildCardRequirement(Enum):
    SAME = 0
    DIFFERENT = 1
    PAIRS = 2


# Physical gem types in the order used by catalogs and gem-count operations.
STANDARD_GEMS = (
    GemType.BLUE_CIRCLE,
    GemType.GREEN_OVAL,
    GemType.PURPLE_TRIANGLE,
    GemType.YELLOW_SQUARE,
    GemType.PINK_PENTAGON,
)

# MappingProxyType creates a read-only view, whereas FrozenMap copies entries.
# These inline dictionaries have no separate mutable aliases.

CARDS_PER_PLAYER = MappingProxyType({3: 5, 4: 4, 5: 3})
COINS_PER_PLAYER = MappingProxyType({3: 35, 4: 25, 5: 20})
MISSIONS_PER_GAME = 4
GEMS_ON_AUCTION = 2
