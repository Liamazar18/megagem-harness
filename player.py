"""Mutable player state and the validation boundary for bot decisions."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field
from random import Random

from bot_runner import BotRunner
from bots import Bot, BotInfo, GameSummary, RoundResult
from constants import AuctionType, GemType
from lib import AuctionCard, MissionCard


# Represents the state of a player, to only be used by the harness and never exposed to the bot
@dataclass
class Player:
    id: int # Identifies and indexes the player
    coins: int # Number of coins available to the player to bid with
    hidden_gem_hand: list[GemType] # Hidden gems (yet to be revealed to value display) of the player
    bot_type: InitVar[type[Bot] | BotRunner] = Bot # Type of the bot — either given an implemented bot or a bot runner already wrapping it
    bot_timeout: InitVar[float | None] = 1.0 # Timeout given to the bot for decision/information store functions
    bot: BotRunner = field(init=False, repr=False) # Bot runner wrapping the provided bot, callable
    invested_coins: int = field(default=0, init=False) # Coins of the player that are "locked up" in investments, to be returned at the end of the game
    auction_cards: list[AuctionCard] = field(default_factory=list, init=False) # Auction cards "owned" by the player (loans and investments)
    mission_cards: list[MissionCard] = field(default_factory=list, init=False) # Mission cards claimed by the player
    public_gem_hand: list[GemType] = field(default_factory=list, init=False) # Gems that have been revealed by the player from their hidden gem hand to the value display
    gem_collection: Counter[GemType] = field(default_factory=Counter, init=False) # Gems that have been won from the player in auction
    _fallback_rng: Random = field(default_factory=Random, init=False, repr=False) # Random number generator to be used if the bot returns an invalid action or times out, makes games reproducible

    def __post_init__(
        self, bot_type: type[Bot] | BotRunner, bot_timeout: float | None
    ) -> None:
        self.hidden_gem_hand = list(self.hidden_gem_hand)
        # Wrap the bot in a BotRunner instance, if necessary
        self.bot = (
            bot_type
            if isinstance(bot_type, BotRunner)
            else BotRunner(bot_type, timeout=bot_timeout)
        )
        # Name the bot with the player id
        self.bot.label = f"Player {self.id} ({self.bot.bot_class.__name__})"

    # Forward the on_game_start notification to the bot
    def on_game_start(self) -> None:
        self.bot.call("on_game_start")

    # Get the bid decision from the bot and fallback 0 coins if provided bid invalid
    def get_bid(self, info: BotInfo) -> int:
        bid = self.bot.call("get_bid", info)
        card = info.current_auction
        available = self.coins
        if card is not None and card.type is AuctionType.LOAN:
            available += card.value
        return bid if type(bid) is int and 0 <= bid <= available else 0

    # Get the hidden gem reveal decision from the bot and fallback to a random gem if the provided one is invalid
    def choose_hidden_gem(self, info: BotInfo, bids: Mapping[int, int]) -> int:
        # Bot is expected to provide the index of a gem in its hand, rather than the gem itself
        index = self.bot.call("choose_hidden_gem", info, bids)
        if type(index) is int and 0 <= index < len(self.hidden_gem_hand):
            return index
        return self._fallback_rng.randrange(len(self.hidden_gem_hand))

    # Gets the gem decision from the bot and reveals it for the player. Returns the revealed gem
    def reveal_gem(self, info: BotInfo, bids: Mapping[int, int]) -> GemType | None:
        if not self.hidden_gem_hand:
            return None
        gem = self.hidden_gem_hand.pop(self.choose_hidden_gem(info, bids))
        self.public_gem_hand.append(gem)
        return gem

    # Converts all remaining gems into public gems and returns those revealed (to be used at end of game)
    def reveal_remaining_gems(self) -> tuple[GemType, ...]:
        revealed = tuple(self.hidden_gem_hand)
        self.public_gem_hand.extend(revealed)
        self.hidden_gem_hand.clear()
        return revealed

    # Forwards the round end notification to the bot and allows it to aggregate info
    def on_round_end(self, info: BotInfo, result: RoundResult) -> None:
        self.bot.call("on_round_end", info, result)

    # Forwards the game end notification to the bot and allows it to aggregate info
    def on_game_end(self, info: BotInfo, result: GameSummary) -> None:
        self.bot.call("on_game_end", info, result)
