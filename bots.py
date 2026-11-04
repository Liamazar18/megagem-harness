"""The bot-author API. All information received by callbacks is an immutable copy."""

import random
from collections.abc import Mapping
from dataclasses import dataclass

from constants import GemType
from immutable import FrozenMap
from lib import AuctionCard, MissionCard, ValueChart


# Public information about a player, provided to bots
@dataclass(frozen=True, slots=True)
class PlayerInfo:
    id: int # Identifies and indexes the player
    coins: int # Number of coins available to the player to bid with
    hidden_gem_count: int # Number of gems that have yet to be revealed by the player
    revealed_gems: tuple[GemType, ...] # Gems that have been revealed from the private hand of the player, in order of reveal
    won_gems: FrozenMap[GemType, int] # Gems counts that have been won by the player in auction
    auction_cards: tuple[AuctionCard, ...] # Auction cards "owned" by the player (loans and investments)
    mission_cards: tuple[MissionCard, ...] # Mission cards claimed by the player
    invested_coins: int  # Coins of the player that are "locked up" in investments, to be returned at the end of the game


# Extends the public information about a player to include the exact hidden gems of the player
@dataclass(frozen=True, slots=True)
class SelfInfo(PlayerInfo):
    hidden_gems: tuple[GemType, ...]


# Combines player information, self information, and game state information into a single package
# to be sent to bots describing the game state
@dataclass(frozen=True, slots=True)
class BotInfo:
    self_player: SelfInfo # Information about the player that the bot represents, includes hidden gems
    other_players: tuple[PlayerInfo, ...] # Public information about other players in the game, does not include hidden gems
    num_players: int # Number of players in the game
    round_number: int # Current round/auction number, 1-indexed
    current_auction: AuctionCard | None # The auction card currently in play, describes what is up for auction
    gem_deck_count: int # Number of gems left in the hidden draw pile (to be auctioned)
    gems_remaining: int  # Hidden draw pile plus exposed auction gems.
    unknown_gems: FrozenMap[GemType, int]  # Opponents' hands plus hidden draw pile.
    auction_gems: tuple[GemType, ...]  # Gems up for auction, first item is auctioned first.
    value_display: FrozenMap[GemType, int] # All revealed gems from hidden hands
    previous_winner_id: int | None # Player id of the previous auction winner, determines tiebreaker
    value_chart: ValueChart # Current value chart in use
    available_missions: tuple[MissionCard, ...] # Missions available to be claimed
    auction_deck_count: int # Number of cards left in the auction deck (of 25, not including the current auction card)
    auction_cards_remaining: FrozenMap[AuctionCard, int]  # Counts of the remaining auction cards


# Summarizes the result of the past bidding round
@dataclass(frozen=True, slots=True)
class RoundResult:
    auction_card: AuctionCard # Auction card that was in play
    bids: FrozenMap[int, int] # Map of player id to bid amount, in coins
    winner_id: int # Player id of the winning bidder
    winning_bid: int # Number of coins that the winning bidder won with
    revealed_gem: GemType | None # Gem that was revealed from the winning bidder


# Summarizes the result of a game, scores only
@dataclass(frozen=True, slots=True)
class GameSummary:
    scores: FrozenMap[int, int] # Map of player id to final score, in coins
    winner_ids: tuple[int, ...] # The player id's with the highest score (only multiple if there is a tie)
    winning_score: int # The score of the winning player


class Bot:
    """Subclass in an importable module; override any callbacks you need.

    Instance attributes are checkpointed after successful callbacks. Override
    save_state/load_state together when keeping resources that cannot be pickled.
    Randomness here is private to the worker, never the game's random generator.
    """

    # Number of seconds that the bot is alotted for each function
    timeout_seconds: float | None = None

    # Notification of a new game starting
    def on_game_start(self) -> None:
        pass

    # Return how many coins to bid in this round
    def get_bid(self, info: BotInfo) -> int:
        return 0

    # Choose which gem to reveal to other players when you win an auction
    def choose_hidden_gem(self, info: BotInfo, bids: Mapping[int, int]) -> int:
        return random.randrange(len(info.self_player.hidden_gems))

    # Notification of a round of bidding ending and the results
    def on_round_end(self, info: BotInfo, result: RoundResult) -> None:
        pass

    # Notification of a game ending and the results
    def on_game_end(self, info: BotInfo, result: GameSummary) -> None:
        pass

    # Method that is used to back up any persistent memory (attributes) of the bot
    # Most normal python objects are pickleable and will be saved
    # View these docs for help: https://docs.python.org/3/library/pickle.html#what-can-be-pickled-and-unpickled
    def save_state(self) -> object:
        """Return pickleable memory. This executes only inside the bot worker."""
        return self.__dict__.copy()

    # Loads a saved state of the bot, if the bot needs to restart for some reason
    def load_state(self, state: object) -> None:
        """Restore memory without running __init__ or on_game_start again."""
        if not isinstance(state, dict):
            raise TypeError("Default bot memory must be a dictionary")
        self.__dict__.clear()
        self.__dict__.update(state)
