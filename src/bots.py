"""The bot-author API. All information received by callbacks is an immutable copy."""

import random
from collections.abc import Mapping
from dataclasses import dataclass

from constants import GemType
from immutable import FrozenMap
from lib import AuctionCard, MissionCard, ValueChart


# Public information about a player, provided to bots.
@dataclass(frozen=True, slots=True)
class PlayerInfo:
    id: int  # Player ID and seat index.
    coins: int  # Available coins, excluding invested coins.
    hidden_gem_count: int  # Number of gems remaining in the player's hidden hand.
    # Starting-hand gems in the order they were revealed.
    revealed_gems: tuple[GemType, ...]
    # Counts of gems acquired through treasure auctions.
    won_gems: FrozenMap[GemType, int]
    # Loan and investment cards acquired by this player.
    auction_cards: tuple[AuctionCard, ...]
    mission_cards: tuple[MissionCard, ...]  # Missions claimed by this player.
    invested_coins: int  # Invested bid coins, returned at game end.


# Public player information extended with this bot's own hidden gems.
@dataclass(frozen=True, slots=True)
class SelfInfo(PlayerInfo):
    hidden_gems: tuple[GemType, ...]


# An immutable view of public game information and this bot's private hand.
@dataclass(frozen=True, slots=True)
class BotInfo:
    self_player: SelfInfo  # This bot's player information, including hidden gems.
    # Other players in seating order, without hidden gem identities.
    other_players: tuple[PlayerInfo, ...]
    num_players: int  # Number of players in the game.
    # Current auction number; setup is round zero and auctions start at one.
    round_number: int
    # Current auction card; None before the first auction.
    current_auction: AuctionCard | None
    gem_deck_count: int  # Number of gems in the hidden draw pile.
    gems_remaining: int  # Hidden draw pile plus exposed auction gems.
    # Inferred counts across opponents' hidden hands and the hidden draw pile.
    unknown_gems: FrozenMap[GemType, int]
    auction_gems: tuple[GemType, ...]  # Exposed auction gems, with the first gem first.
    # Counts of starting-hand gems revealed in the value display.
    value_display: FrozenMap[GemType, int]
    # Previous winner while bidding; current winner after resolution.
    previous_winner_id: int | None
    value_chart: ValueChart  # Selected value chart.
    # Unclaimed missions available to all players.
    available_missions: tuple[MissionCard, ...]
    # Number of undrawn auction cards, excluding the current auction.
    auction_deck_count: int
    # Counts of undrawn auction cards, without their order.
    auction_cards_remaining: FrozenMap[AuctionCard, int]


# Summary of the completed auction round.
@dataclass(frozen=True, slots=True)
class RoundResult:
    auction_card: AuctionCard  # Auction card resolved in this round.
    bids: FrozenMap[int, int]  # Validated bid amounts keyed by player ID.
    winner_id: int  # Player ID of the winning bidder.
    winning_bid: int  # Winning bid amount, in coins.
    # Starting-hand gem revealed by the winner, or None for an empty hand.
    revealed_gem: GemType | None


# Final scores and winner IDs, without live game state.
@dataclass(frozen=True, slots=True)
class GameSummary:
    scores: FrozenMap[int, int]  # Final scores keyed by player ID.
    winner_ids: tuple[int, ...]  # Player IDs sharing the highest score.
    winning_score: int  # Highest final score, in coins.


class Bot:
    """Subclass in an importable module; override any callbacks you need.

    Instance attributes are checkpointed after successful callbacks. Override
    save_state/load_state together when keeping resources that cannot be pickled.
    Randomness here is private to the worker, never the game's random generator.
    """

    # Callback allowance in seconds; None disables the timeout.
    timeout_seconds: float | None = None

    # Prepare for a new game, selectively resetting bot memory if needed.
    def on_game_start(self) -> None:
        pass

    # Return the number of coins to bid in this auction.
    def get_bid(self, info: BotInfo) -> int:
        return 0

    # Return an index into the hidden hand after winning an auction.
    def choose_hidden_gem(self, info: BotInfo, bids: Mapping[int, int]) -> int:
        return random.randrange(len(info.self_player.hidden_gems))

    # Receive the completed round and its results.
    def on_round_end(self, info: BotInfo, result: RoundResult) -> None:
        pass

    # Receive the completed game and its final scores.
    def on_game_end(self, info: BotInfo, result: GameSummary) -> None:
        pass

    # Checkpoint pickleable instance attributes from __dict__; override both
    # state hooks for slot-backed fields or resources that need reconstruction.
    # Pickle documentation: https://docs.python.org/3/library/pickle.html
    def save_state(self) -> object:
        """Return pickleable memory. This executes only inside the bot worker."""
        return self.__dict__.copy()

    # Restore saved memory when a replacement worker starts.
    def load_state(self, state: object) -> None:
        """Restore memory without running __init__ or on_game_start again."""
        if not isinstance(state, dict):
            raise TypeError("Default bot memory must be a dictionary")
        self.__dict__.clear()
        self.__dict__.update(state)
