"""Gem labels, auction types, and player-count-dependent setup rules."""

from enum import Enum
from types import MappingProxyType


# The different types of gem cards (5 total, 1 wild-card value for missions)
class GemType(Enum):
    BLUE_CIRCLE = 0
    GREEN_OVAL = 1
    PURPLE_TRIANGLE = 2
    YELLOW_SQUARE = 3
    PINK_PENTAGON = 4
    WILD_CARD = 5  # A mission requirement for unspecified colors, not a physical card.


# The different types of auction cards

# Auction => Auction for 1 or 2 gems
# Invest => Auction for an investment of known coin return
# Loan => Auction for an immediate loan of coins to bid with
class AuctionType(Enum):
    AUCTION = 0
    INVEST = 1
    LOAN = 2


# Requirements for mission cards with wild-card gems
# The wild-card gems must either be all the same, all different, or pairs of identical gems
class WildCardRequirement(Enum):
    SAME = 0
    DIFFERENT = 1
    PAIRS = 2


# A utility tuple of all non-wild-card gems. Can be useful as an iterable for for-loops
STANDARD_GEMS = (
    GemType.BLUE_CIRCLE,
    GemType.GREEN_OVAL,
    GemType.PURPLE_TRIANGLE,
    GemType.YELLOW_SQUARE,
    GemType.PINK_PENTAGON,
)

# MappingProxyType creates a read-only *view* of the dictionary.
# Does not create a copy of the dictionary, like FrozenMap, but this 
# is unimportant, since the original dictionaries will not change

CARDS_PER_PLAYER = MappingProxyType({3: 5, 4: 4, 5: 3})
COINS_PER_PLAYER = MappingProxyType({3: 35, 4: 25, 5: 20})
MISSIONS_PER_GAME = 4
GEMS_ON_AUCTION = 2
