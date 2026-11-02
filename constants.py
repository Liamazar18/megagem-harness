"""Gem labels, auction types, and player-count-dependent setup rules."""

from enum import Enum
from types import MappingProxyType


class GemType(Enum):
    BLUE_CIRCLE = 0
    GREEN_OVAL = 1
    PURPLE_TRIANGLE = 2
    YELLOW_SQUARE = 3
    PINK_PENTAGON = 4
    WILD_CARD = 5  # A mission requirement for unspecified colors, not a physical card.


class AuctionType(Enum):
    AUCTION = 0
    INVEST = 1
    LOAN = 2


class WildCardRequirement(Enum):
    SAME = 0
    DIFFERENT = 1
    PAIRS = 2


STANDARD_GEMS = (
    GemType.BLUE_CIRCLE,
    GemType.GREEN_OVAL,
    GemType.PURPLE_TRIANGLE,
    GemType.YELLOW_SQUARE,
    GemType.PINK_PENTAGON,
)

# MappingProxyType creates a read-only view of the dictionary.
CARDS_PER_PLAYER = MappingProxyType({3: 5, 4: 4, 5: 3})
COINS_PER_PLAYER = MappingProxyType({3: 35, 4: 25, 5: 20})
MISSIONS_PER_GAME = 4
GEMS_ON_AUCTION = 2
