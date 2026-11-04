"""Set up, simulate, and score Megagem without coupling gameplay to console I/O."""

import argparse
import importlib
from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from random import Random
from types import TracebackType

from bot_info import build_bot_info
from bot_runner import BotRunner
from bots import Bot, GameSummary, RoundResult
from constants import (
    CARDS_PER_PLAYER,
    COINS_PER_PLAYER,
    GEMS_ON_AUCTION,
    MISSIONS_PER_GAME,
    STANDARD_GEMS,
    AuctionType,
    GemType,
)
from decks import AUCTION_CARDS, GEM_CARDS, MISSION_CARDS, VALUE_CHARTS
from immutable import FrozenMap
from lib import AuctionCard, Deck, MissionCard, ValueChart
from player import Player


# Fully represents the current state of the game, including players, bots, random number generator
@dataclass
class GameState:
    players: list[Player]
    gem_deck: Deck[GemType]
    auction_deck: Deck[AuctionCard]
    available_missions: list[MissionCard]
    value_chart: ValueChart
    rng: Random = field(repr=False)
    auction_gems: deque[GemType] = field(default_factory=deque)
    value_display: Counter[GemType] = field(
        default_factory=lambda: Counter(dict.fromkeys(STANDARD_GEMS, 0))
    )
    previous_winner_id: int | None = None
    round_number: int = 0
    current_auction: AuctionCard | None = None
    auction_history: list[AuctionCard] = field(default_factory=list)
    owned_bots: tuple[BotRunner, ...] = field(default=(), repr=False)
    end_notified: bool = False

    # Releases all workers for the game
    def close(self) -> None:
        """Release workers created by this game; caller-owned runners stay reusable."""
        for bot in self.owned_bots:
            bot.close()

    # Executes when entering a "with" block
    def __enter__(self) -> "GameState":
        return self

    # Executes when leaving a "with" block, makes sure to release all workers
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


# Details the result of a game, including the final state and scores/winners
@dataclass(frozen=True)
class GameResult:
    state: GameState
    scores: tuple[int, ...]
    winner_ids: tuple[int, ...]

    @property
    def winning_score(self) -> int:
        return max(self.scores)


# Instantiates a game based on the number of players, value chart, random number generator, and bot details
def create_game(
    num_players: int,
    *,
    value_chart: ValueChart = VALUE_CHARTS[0],
    rng: Random | None = None,
    bots: Sequence[type[Bot] | BotRunner] | None = None,
    bot_timeout: float | None = 1.0,
    bot_seed: int | None = None,
) -> GameState:
    # Validate number of players
    if num_players not in CARDS_PER_PLAYER:
        raise ValueError("Megagem requires 3, 4, or 5 players")
    rng = rng if rng is not None else Random()
    bot_types = list(bots) if bots is not None else [Bot] * num_players
    if len(bot_types) != num_players:
        raise ValueError("Supply one bot class or runner per player")
    # Make sure each player has a separate bot runner
    if len({id(bot) for bot in bot_types if isinstance(bot, BotRunner)}) != sum(
        isinstance(bot, BotRunner) for bot in bot_types
    ):
        raise ValueError("Each player needs a separate bot runner")
    bot_random = Random(bot_seed)
    # For provided bots that are not already runners, instantiate them
    runners = [
        bot
        if isinstance(bot, BotRunner)
        else BotRunner(bot, timeout=bot_timeout, seed=bot_random.getrandbits(128))
        for bot in bot_types
    ]
    # Get cards per player based on rules
    cards_per_player = CARDS_PER_PLAYER[num_players]

    # Create and shuffle the gems deck
    gems = list(GEM_CARDS)
    rng.shuffle(gems)
    # Create players, assigning them each a hidden hand from the gem deck
    players = [
        Player(
            player_id,
            COINS_PER_PLAYER[num_players],
            gems[player_id * cards_per_player : (player_id + 1) * cards_per_player],
            bot_type=runners[player_id],
        )
        for player_id in range(num_players)
    ]

    # Create and shuffle mission/auction card decks
    missions = list(MISSION_CARDS)
    rng.shuffle(missions)
    auctions = list(AUCTION_CARDS)
    rng.shuffle(auctions)
    # Instantaite the game state, removing from the gem deck the cards that were dealt to players as hidden hands
    game = GameState(
        players=players,
        gem_deck=Deck(gems[num_players * cards_per_player :]),
        auction_deck=Deck(auctions),
        available_missions=missions[:MISSIONS_PER_GAME],
        value_chart=value_chart,
        rng=rng,
        # Bots that had runners created by this game, should be released at the end of the game
        owned_bots=tuple(
            runner
            for runner, bot in zip(runners, bot_types)
            if not isinstance(bot, BotRunner)
        ),
    )
    # Make sure there are two gems from the gem deck ready to be auctioned
    _refill_auction_gems(game)
    try:
        # Send the on_game_start() message to bots through players
        for player in game.players:
            player.on_game_start()
    except BaseException:
        game.close()
        raise
    # Return the game state object
    return game


# Gives information to bots and collects their bids
def _collect_bids(game: GameState) -> list[int]:
    # Build every view before invoking any bot: bidding is simultaneous.
    views = [build_bot_info(game, player) for player in game.players]
    return [player.get_bid(info) for player, info in zip(game.players, views)]


# Returns the index of the winner based on bids, taking into account tiebreakers
def _select_winner(
    bids: Sequence[int], previous_winner_id: int | None, rng: Random
) -> int:
    highest_bid = max(bids)
    tied_ids = [player_id for player_id, bid in enumerate(bids) if bid == highest_bid]
    # There is no tie
    if len(tied_ids) == 1:
        return tied_ids[0]
    # First auction of the game is a tie, goes to random choice
    if previous_winner_id is None:
        return rng.choice(tied_ids)
    # Tie goes to player closest clockwise of the last auction winner
    return min(
        tied_ids,
        key=lambda player_id: (player_id - previous_winner_id - 1) % len(bids),
    )


# Applies the result of the auction to the winner, depending on the type of auction card
def _apply_auction(
    game: GameState, winner: Player, card: AuctionCard, bid: int
) -> None:
    match card.type:
        case AuctionType.AUCTION:
            for _ in range(min(card.value, len(game.auction_gems))):
                winner.gem_collection[game.auction_gems.popleft()] += 1
        case AuctionType.LOAN:
            winner.auction_cards.append(card)
            winner.coins += card.value
        case AuctionType.INVEST:
            winner.auction_cards.append(card)
            winner.invested_coins += bid
    winner.coins -= bid


# Make sure there are two gems from the gem deck ready to be auctioned
def _refill_auction_gems(game: GameState) -> None:
    while len(game.auction_gems) < GEMS_ON_AUCTION:
        gem = game.gem_deck.draw()
        if gem is None:
            break
        game.auction_gems.append(gem)


# For a player, check if missions can be claimed. If so, give the missions to the player,
# and remove them from the public pool that can be claimed
def _claim_missions(game: GameState, player: Player) -> None:
    remaining = []
    for mission in game.available_missions:
        if mission.is_satisfied(player.gem_collection):
            player.mission_cards.append(mission)
        else:
            remaining.append(mission)
    game.available_missions = remaining


# Execute a full round of play
def play_round(game: GameState) -> None:
    """Resolve one auction, reveal information, replenish gems, and claim missions."""
    if not game.auction_gems:
        raise ValueError("All gems have already been auctioned")
    card = game.auction_deck.draw()
    if card is None:
        raise RuntimeError("Auction cards ran out before all gems were sold")

    game.round_number += 1
    game.current_auction = card
    game.auction_history.append(card)
    bids = _collect_bids(game)
    winner_id = _select_winner(bids, game.previous_winner_id, game.rng)
    winner = game.players[winner_id]
    _apply_auction(game, winner, card, bids[winner_id])
    game.previous_winner_id = winner_id

    # Bid information to give to the auction winner
    bid_map = FrozenMap({player.id: bid for player, bid in zip(game.players, bids)})
    revealed_gem = winner.reveal_gem(build_bot_info(game, winner), bid_map)
    # Update the value display with the revealed gem
    if revealed_gem is not None:
        game.value_display[revealed_gem] += 1
    _refill_auction_gems(game)
    _claim_missions(game, winner)
    # Create the round result object to share with players via notification
    result = RoundResult(card, bid_map, winner_id, bids[winner_id], revealed_gem)
    # Notify all players of the round result
    for player in game.players:
        player.on_round_end(build_bot_info(game, player), result)


# Calculate the final score for each a player based on their holdings and the value of gems (determined by the value chart)
def _score_player(player: Player, gem_values: Mapping[GemType, int]) -> int:
    return (
        player.coins
        + player.invested_coins
        + sum(player.gem_collection[gem] * gem_values[gem] for gem in STANDARD_GEMS)
        + sum(mission.value for mission in player.mission_cards)
        + sum(card.end_game_value for card in player.auction_cards)
    )


def finish_game(game: GameState) -> GameResult:
    """Reveal remaining hands and score the game. Safe to call more than once."""
    if game.auction_gems or game.gem_deck:
        raise ValueError("Cannot score a game before all gems have been auctioned")
    # Add all remaining hidden gems to the value display
    for player in game.players:
        game.value_display.update(player.reveal_remaining_gems())
    # Calculate the value of gems based on the value display counts and value chart coin values
    gem_values = {
        gem: game.value_chart.get_value(game.value_display[gem])
        for gem in STANDARD_GEMS
    }
    # Calculate the scores of all players
    scores = tuple(_score_player(player, gem_values) for player in game.players)
    winning_score = max(scores)
    winner_ids = tuple(
        player.id
        for player, score in zip(game.players, scores)
        if score == winning_score
    )
    # Create the game result object to be shared with players
    result = GameResult(game, scores, winner_ids)
    # Notifies players of the game result
    if not game.end_notified:
        summary = GameSummary(
            FrozenMap(
                {player.id: score for player, score in zip(game.players, scores)}
            ),
            winner_ids,
            winning_score,
        )
        game.end_notified = True
        for player in game.players:
            player.on_game_end(build_bot_info(game, player), summary)
    return result


# Plays a complete game from start to finish (setup, auction rounds, and finalization)
def play_game(
    num_players: int,
    *,
    value_chart: ValueChart = VALUE_CHARTS[0],
    rng: Random | None = None,
    bots: Sequence[type[Bot] | BotRunner] | None = None,
    bot_timeout: float | None = 1.0,
    bot_seed: int | None = None,
) -> GameResult:
    with create_game(
        num_players,
        value_chart=value_chart,
        rng=rng,
        bots=bots,
        bot_timeout=bot_timeout,
        bot_seed=bot_seed,
    ) as game:
        while game.auction_gems:
            play_round(game)
        return finish_game(game)


# Prints a formatted result of the game based on a game result object
def print_result(result: GameResult) -> None:
    print("Game Over:")
    for player, score in zip(result.state.players, result.scores):
        print(f" Player {player.id}: {score}")
    winners = ", ".join(str(player_id) for player_id in result.winner_ids)
    if len(result.winner_ids) == 1:
        print(f"\n Player {winners} wins with {result.winning_score} coins!")
    else:
        print(f"\n Players {winners} win with {result.winning_score} coins!")


# Run with this module, includes a CLI for quick simulation
def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a game of Megagem")
    parser.add_argument("players", type=int, choices=tuple(CARDS_PER_PLAYER), nargs="?")
    parser.add_argument("--seed", type=int, help="Seed for a reproducible game")
    parser.add_argument(
        "--bot-seed", type=int, help="Independent seed for bot randomness"
    )
    parser.add_argument(
        "--bots",
        nargs="+",
        metavar="MODULE:CLASS",
        help="One bot class for everyone, or one per player (default: bots:Bot)",
    )
    parser.add_argument(
        "--bot-timeout",
        default="1.0",
        metavar="SECONDS|none",
        help="Per-callback wall-clock budget; 'none' disables it (default: 1 second)",
    )
    parser.add_argument(
        "--chart", choices=[chart.name for chart in VALUE_CHARTS], default="A"
    )
    args = parser.parse_args()
    num_players = args.players
    if num_players is None:
        try:
            num_players = int(input("Number of players: "))
        except ValueError:
            parser.error("Player count must be an integer")
        if num_players not in CARDS_PER_PLAYER:
            parser.error("Megagem requires 3, 4, or 5 players")
    chart = next(chart for chart in VALUE_CHARTS if chart.name == args.chart)
    try:
        timeout = (
            None if args.bot_timeout.lower() == "none" else float(args.bot_timeout)
        )
        bot_classes = [_load_bot_class(spec) for spec in (args.bots or ["bots:Bot"])]
        if len(bot_classes) == 1:
            bot_classes *= num_players
        print_result(
            play_game(
                num_players,
                value_chart=chart,
                rng=Random(args.seed),
                bots=bot_classes,
                bot_timeout=timeout,
                bot_seed=args.bot_seed,
            )
        )
    except (ValueError, TypeError, ImportError, AttributeError) as exc:
        parser.error(str(exc))


# Get a bot type from a spec string
def _load_bot_class(spec: str) -> type[Bot]:
    module, separator, name = spec.partition(":")
    if not separator:
        raise ValueError("Bot classes must be written as module:Class")
    candidate = getattr(importlib.import_module(module), name)
    if not isinstance(candidate, type) or not issubclass(candidate, Bot):
        raise ValueError(f"{spec} must inherit from Bot")
    return candidate


if __name__ == "__main__":
    main()
