"""Mutable player state and the validation boundary for bot decisions."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field
from random import Random

from bot_runner import BotRunner
from bots import Bot, BotInfo, GameSummary, RoundResult
from constants import AuctionType, GemType
from lib import AuctionCard, MissionCard


# Mutable player state used by the harness; bots receive snapshots only.
@dataclass
class Player:
    id: int  # Player ID and seat index.
    coins: int  # Available coins, excluding invested coins.
    # Starting-hand gems not yet revealed in the value display.
    hidden_gem_hand: list[GemType]
    # Bot subclass or an existing runner; not a bot instance.
    bot_type: InitVar[type[Bot] | BotRunner] = Bot
    # Callback timeout for a new runner; an existing runner keeps its setting.
    bot_timeout: InitVar[float | None] = 1.0
    # Runner used to invoke the bot callbacks.
    bot: BotRunner = field(init=False, repr=False)
    # Invested bid coins, returned at game end.
    invested_coins: int = field(default=0, init=False)
    # Loan and investment cards acquired by this player.
    auction_cards: list[AuctionCard] = field(default_factory=list, init=False)
    # Missions claimed by this player.
    mission_cards: list[MissionCard] = field(default_factory=list, init=False)
    # Starting-hand gems already revealed in the value display.
    public_gem_hand: list[GemType] = field(default_factory=list, init=False)
    # Gems acquired by this player through treasure auctions.
    gem_collection: Counter[GemType] = field(default_factory=Counter, init=False)
    # Independent, unseeded randomness for invalid or failed reveal decisions.
    _fallback_rng: Random = field(default_factory=Random, init=False, repr=False)

    def __post_init__(
        self, bot_type: type[Bot] | BotRunner, bot_timeout: float | None
    ) -> None:
        self.hidden_gem_hand = list(self.hidden_gem_hand)
        # Create a runner for a bot class, or reuse the supplied runner.
        self.bot = (
            bot_type
            if isinstance(bot_type, BotRunner)
            else BotRunner(bot_type, timeout=bot_timeout)
        )
        # Include the player ID in diagnostic messages.
        self.bot.label = f"Player {self.id} ({self.bot.bot_class.__name__})"

    # Notify the bot that a new game is starting.
    def on_game_start(self) -> None:
        self.bot.call("on_game_start")

    # Validate the bid, falling back to zero for invalid or failed decisions.
    def get_bid(self, info: BotInfo) -> int:
        bid = self.bot.call("get_bid", info)
        card = info.current_auction
        available = self.coins
        if card is not None and card.type is AuctionType.LOAN:
            available += card.value
        return bid if type(bid) is int and 0 <= bid <= available else 0

    # Validate the reveal index, falling back to a random valid index on failure.
    def choose_hidden_gem(self, info: BotInfo, bids: Mapping[int, int]) -> int:
        # Expect an index into the hidden hand, not a GemType value.
        index = self.bot.call("choose_hidden_gem", info, bids)
        if type(index) is int and 0 <= index < len(self.hidden_gem_hand):
            return index
        return self._fallback_rng.randrange(len(self.hidden_gem_hand))

    # Reveal the chosen gem, or return None when the hidden hand is empty.
    def reveal_gem(self, info: BotInfo, bids: Mapping[int, int]) -> GemType | None:
        if not self.hidden_gem_hand:
            return None
        gem = self.hidden_gem_hand.pop(self.choose_hidden_gem(info, bids))
        self.public_gem_hand.append(gem)
        return gem

    # Reveal and return all remaining starting-hand gems at game end.
    def reveal_remaining_gems(self) -> tuple[GemType, ...]:
        revealed = tuple(self.hidden_gem_hand)
        self.public_gem_hand.extend(revealed)
        self.hidden_gem_hand.clear()
        return revealed

    # Notify the bot of the completed round so it can update its memory.
    def on_round_end(self, info: BotInfo, result: RoundResult) -> None:
        self.bot.call("on_round_end", info, result)

    # Notify the bot of the final results so it can update its memory.
    def on_game_end(self, info: BotInfo, result: GameSummary) -> None:
        self.bot.call("on_game_end", info, result)
