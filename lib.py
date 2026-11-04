"""Immutable card definitions and a typed deck."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

from constants import STANDARD_GEMS, AuctionType, GemType, WildCardRequirement
from immutable import FrozenMap


# An immutable auction-card definition.
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

    # Return the investment bonus or loan repayment; treasure contributes zero.
    # Invested bid coins are tracked separately on Player.
    @property
    def end_game_value(self) -> int:
        """Investment bonus or loan repayment, excluding invested bid coins."""
        if self.type is AuctionType.INVEST:
            return self.value
        if self.type is AuctionType.LOAN:
            return -self.value
        return 0


# An immutable mission-card definition.
@dataclass(frozen=True, slots=True)
class MissionCard:
    # Coin value awarded at game end for completing this mission.
    value: int
    # Required gem counts, including unspecified colors via WILD_CARD.
    gem_requirements: Mapping[GemType, int]
    # Optional color constraint for unspecified mission gems.
    wild_card_requirement: WildCardRequirement | None = None

    def __post_init__(self) -> None:
        if self.value < 0 or any(count < 0 for count in self.gem_requirements.values()):
            raise ValueError(
                "Mission value and gem requirement counts cannot be negative"
            )
        
        # Copy the requirements into a read-only mapping, without retaining a
        # mutable alias to the caller's mapping.
        object.__setattr__(self, "gem_requirements", FrozenMap(self.gem_requirements))

    # Check whether acquired gem counts satisfy this mission's requirements.
    def is_satisfied(self, collection: Mapping[GemType, int]) -> bool:
        # Reserve required colors; leftover gems can satisfy unspecified colors.
        remaining = tuple(
            collection.get(gem, 0) - self.gem_requirements.get(gem, 0)
            for gem in STANDARD_GEMS
        )
        # Reject collections that lack any required fixed-color gems.
        if any(count < 0 for count in remaining):
            return False

        # Check the required count and color constraint for unspecified gems.
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


# Generic deck element type, used here for gem, auction, and mission cards.
CardT = TypeVar("CardT")


# A generic deck used for gem, auction, and mission cards.
class Deck(Generic[CardT]):
    """Owns its list of cards. Draws from the end; shuffle before constructing."""

    def __init__(self, cards: Iterable[CardT] = ()) -> None:
        self._cards = list(cards)

    def __len__(self) -> int:
        return len(self._cards)

    # Draw from the end; shuffle the input outside this class for random draws.
    def draw(self) -> CardT | None:
        return self._cards.pop() if self._cards else None

# Per-gem coin values indexed by display counts from zero through six.
@dataclass(frozen=True, slots=True)
class ValueChart:
    # Single-letter chart name, A-E.
    name: str
    values: tuple[int, ...]

    # Six entries cover counts 0-5; a seventh can specify the value for count 6.
    def __post_init__(self) -> None:
        values = tuple(self.values)
        if len(values) == 6:
            # The sixth gem uses the five-gem value unless explicitly specified.
            values += (values[-1],)
        elif len(values) != 7:
            raise ValueError("A value chart needs values for counts 0–5 or 0–6")
        object.__setattr__(self, "values", values)

    # Return a gem type's value based on its count in the value display.
    def get_value(self, num_gems: int) -> int:
        if not 0 <= num_gems < len(self.values):
            raise ValueError(f"Gem count must be between 0 and 6, got {num_gems}")
        return self.values[num_gems]
