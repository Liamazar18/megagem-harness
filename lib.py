"""Immutable card definitions and a typed deck."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

from constants import STANDARD_GEMS, AuctionType, GemType, WildCardRequirement
from immutable import FrozenMap


# Represents an auction card
@dataclass(frozen=True, slots=True)
class AuctionCard:
    """Value is a gem count for treasure, or a coin amount for loans/investments."""

    type: AuctionType
    value: int

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError("An auction card must have a positive value")
        if self.type is AuctionType.AUCTION and self.value not in (1, 2):
            raise ValueError("A treasure auction must award one or two gems")

    # The value of the card, in coins, at the end of the game
    # Does not include the return of coins bid for an invest card, these are 
    # tracked separately as a property of players
    @property
    def end_game_value(self) -> int:
        """Investment bonus or loan repayment, excluding invested bid coins."""
        if self.type is AuctionType.INVEST:
            return self.value
        if self.type is AuctionType.LOAN:
            return -self.value
        return 0


# Represents a mission card
@dataclass(frozen=True, slots=True)
class MissionCard:
    # Number of coins to be paid at the end of the game for completing the mission
    value: int
    # Type and number of gems required to complete the mission
    gem_requirements: Mapping[GemType, int]
    # If the mission requires wild-card gems, the condition attached to those wild-cards
    wild_card_requirement: WildCardRequirement | None = None

    def __post_init__(self) -> None:
        if self.value < 0 or any(count < 0 for count in self.gem_requirements.values()):
            raise ValueError(
                "Mission value and gem requirement counts cannot be negative"
            )
        
        # Makes gem_requirements a FrozenMap, so that the number of gems required for each
        # type cannot be modified and is not connected to the original mapping as a view (copied)
        object.__setattr__(self, "gem_requirements", FrozenMap(self.gem_requirements))

    # Utility to calculate if a collection of gems (counts) satisfies the requirements
    # of this mission card, allowing it to be claimed
    def is_satisfied(self, collection: Mapping[GemType, int]) -> bool:
        # Check mission requirements for all the standard gems
        # Left over gems may be used for wild-card requirements
        remaining = tuple(
            collection.get(gem, 0) - self.gem_requirements.get(gem, 0)
            for gem in STANDARD_GEMS
        )
        # Reject the collection if there is a standard gem requirement it does not satisfy
        if any(count < 0 for count in remaining):
            return False

        # Checks the wild-card requirement
        required = self.gem_requirements.get(GemType.WILD_CARD, 0)
        match self.wild_card_requirement:
            case None:
                return sum(remaining) >= required
            case WildCardRequirement.SAME:
                return max(remaining) >= required
            case WildCardRequirement.DIFFERENT:
                return sum(count > 0 for count in remaining) >= required
            case WildCardRequirement.PAIRS:
                return sum(count // 2 for count in remaining) * 2 >= required
        raise ValueError(f"Unknown wildcard requirement: {self.wild_card_requirement}")


# Generic card type (AuctionCard, MissionCard, GemType) to comprise a deck
CardT = TypeVar("CardT")


# Represents a deck of cards of generic type, so that it can be used to 
# draw gem, auction, and mission cards
class Deck(Generic[CardT]):
    """Owns its list of cards. Draws from the end; shuffle before constructing."""

    def __init__(self, cards: Iterable[CardT] = ()) -> None:
        self._cards = list(cards)

    def __len__(self) -> int:
        return len(self._cards)

    # Does not implement a random draw. Cards list must be shuffled outside of
    # the class for a random draw
    def draw(self) -> CardT | None:
        return self._cards.pop() if self._cards else None

# Represents a value chart as a tuple coin values for gem counts 0-6 
@dataclass(frozen=True, slots=True)
class ValueChart:
    # Corresponds to the single-letter, A-E name of the value chart
    name: str
    values: tuple[int, ...]

    # Value chart can be instantiated in six-value form (the last value is
    # for 5+ gems), or in seven-value form
    def __post_init__(self) -> None:
        values = tuple(self.values)
        if len(values) == 6:
            # The sixth gem uses the five-gem value unless explicitly specified.
            values += (values[-1],)
        elif len(values) != 7:
            raise ValueError("A value chart needs values for counts 0–5 or 0–6")
        object.__setattr__(self, "values", values)

    # Returns the value-per-gem based on the number of gems of the given type
    def get_value(self, num_gems: int) -> int:
        if not 0 <= num_gems < len(self.values):
            raise ValueError(f"Gem count must be between 0 and 6, got {num_gems}")
        return self.values[num_gems]
