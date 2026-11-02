"""Card definitions, a typed deck, and mutable player state."""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from random import Random
from types import MappingProxyType
from typing import Generic, TypeVar

from constants import STANDARD_GEMS, AuctionType, GemType, WildCardRequirement


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

    @property
    def end_game_value(self) -> int:
        """Investment bonus or loan repayment, excluding invested bid coins."""
        if self.type is AuctionType.INVEST:
            return self.value
        if self.type is AuctionType.LOAN:
            return -self.value
        return 0


@dataclass(frozen=True, slots=True)
class MissionCard:
    value: int
    gem_requirements: Mapping[GemType, int]
    wild_card_requirement: WildCardRequirement | None = None

    def __post_init__(self) -> None:
        # Copy before wrapping so callers cannot mutate a card through their input.
        gem_requirements = dict(self.gem_requirements)
        if self.value < 0 or any(count < 0 for count in gem_requirements.values()):
            raise ValueError(
                "Mission value and gem requirement counts cannot be negative"
            )
        object.__setattr__(self, "gem_requirements", MappingProxyType(gem_requirements))

    def is_satisfied(self, collection: Mapping[GemType, int]) -> bool:
        """Check acquired gems; initial hand cards never satisfy missions."""
        remaining = tuple(
            collection.get(gem, 0) - self.gem_requirements.get(gem, 0)
            for gem in STANDARD_GEMS
        )
        if any(count < 0 for count in remaining):
            return False

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


CardT = TypeVar("CardT")


class Deck(Generic[CardT]):
    """Owns its list of cards. Draws from the end; shuffle before constructing."""

    def __init__(self, cards: Iterable[CardT] = ()) -> None:
        self._cards = list(cards)

    def __len__(self) -> int:
        return len(self._cards)

    # Does not implement a random draw. Deck must be shuffled for a random draw
    def draw(self) -> CardT | None:
        return self._cards.pop() if self._cards else None


@dataclass(frozen=True, slots=True)
class ValueChart:
    name: str
    values: tuple[int, ...]

    def __post_init__(self) -> None:
        values = tuple(self.values)
        if len(values) == 6:
            # The sixth gem uses the five-gem value unless explicitly specified.
            values += (values[-1],)
        elif len(values) != 7:
            raise ValueError("A value chart needs values for counts 0–5 or 0–6")
        object.__setattr__(self, "values", values)

    def get_value(self, num_gems: int) -> int:
        if not 0 <= num_gems < len(self.values):
            raise ValueError(f"Gem count must be between 0 and 6, got {num_gems}")
        return self.values[num_gems]


@dataclass
class Player:
    id: int
    coins: int
    hidden_gem_hand: list[GemType]
    rng: Random = field(default_factory=Random, repr=False, compare=False)
    invested_coins: int = field(default=0, init=False)
    auction_cards: list[AuctionCard] = field(default_factory=list, init=False)
    mission_cards: list[MissionCard] = field(default_factory=list, init=False)
    public_gem_hand: list[GemType] = field(default_factory=list, init=False)
    gem_collection: Counter[GemType] = field(default_factory=Counter, init=False)

    def __post_init__(self) -> None:
        self.hidden_gem_hand = list(self.hidden_gem_hand)

    def get_bid(self) -> int:
        """Placeholder policy until players receive decision context."""
        return self.rng.randrange(5)

    def choose_hidden_gem(self) -> int:
        """Return an index into this player's remaining hidden hand."""
        return self.rng.randrange(len(self.hidden_gem_hand))

    def reveal_gem(self) -> GemType | None:
        if not self.hidden_gem_hand:
            return None
        index = self.choose_hidden_gem() % len(self.hidden_gem_hand)
        gem = self.hidden_gem_hand.pop(index)
        self.public_gem_hand.append(gem)
        return gem

    def reveal_remaining_gems(self) -> tuple[GemType, ...]:
        revealed = tuple(self.hidden_gem_hand)
        self.public_gem_hand.extend(revealed)
        self.hidden_gem_hand.clear()
        return revealed
