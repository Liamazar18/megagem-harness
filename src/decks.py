"""Immutable card catalogs shared by games; each game owns its deck containers."""

from itertools import combinations

from constants import STANDARD_GEMS, AuctionType, GemType, WildCardRequirement
from lib import AuctionCard, MissionCard, ValueChart

# Thirty gem cards: six copies of each of the five physical gem types.
GEM_CARDS = tuple(gem for gem in STANDARD_GEMS for _ in range(6))

# Thirty mission cards from the Megagem rules.
MISSION_CARDS = (
    MissionCard(5, {GemType.WILD_CARD: 2}, WildCardRequirement.SAME),
    MissionCard(10, {GemType.WILD_CARD: 3}, WildCardRequirement.SAME),
    MissionCard(5, {GemType.WILD_CARD: 3}, WildCardRequirement.DIFFERENT),
    MissionCard(10, {GemType.WILD_CARD: 4}, WildCardRequirement.DIFFERENT),
    MissionCard(15, {GemType.WILD_CARD: 4}, WildCardRequirement.PAIRS),
    *(
        MissionCard(10, dict.fromkeys(gems, 1))
        for gems in combinations(STANDARD_GEMS, 3)
    ),
    *(
        MissionCard(5, dict.fromkeys(gems, 1))
        for gems in combinations(STANDARD_GEMS, 2)
    ),
    *(MissionCard(5, {gem: 2}) for gem in STANDARD_GEMS),
)

# Twenty-five auction cards: seventeen treasure, four loan, and four investment.
AUCTION_CARDS = tuple(
    AuctionCard(auction_type, value)
    for auction_type, value, copies in (
        (AuctionType.LOAN, 10, 2),
        (AuctionType.LOAN, 20, 2),
        (AuctionType.INVEST, 5, 2),
        (AuctionType.INVEST, 10, 2),
        (AuctionType.AUCTION, 1, 12),
        (AuctionType.AUCTION, 2, 5),
    )
    for _ in range(copies)
)

# Five value charts, retaining the names A-E used by Megagem.
VALUE_CHARTS = (
    ValueChart("A", (0, 4, 8, 12, 16, 20)),
    ValueChart("B", (20, 16, 12, 8, 4, 0)),
    ValueChart("C", (0, 2, 5, 9, 14, 20)),
    ValueChart("D", (20, 18, 15, 11, 6, 0)),
    ValueChart("E", (0, 4, 10, 18, 6, 0)),
)
