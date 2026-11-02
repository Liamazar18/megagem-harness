"""Set up, simulate, and score Megagem without coupling gameplay to console I/O."""

import argparse
from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from random import Random

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
from lib import AuctionCard, Deck, MissionCard, Player, ValueChart


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


@dataclass(frozen=True)
class GameResult:
    state: GameState
    scores: tuple[int, ...]
    winner_ids: tuple[int, ...]

    @property
    def winning_score(self) -> int:
        return max(self.scores)


def create_game(
    num_players: int,
    *,
    value_chart: ValueChart = VALUE_CHARTS[0],
    rng: Random | None = None,
) -> GameState:
    if num_players not in CARDS_PER_PLAYER:
        raise ValueError("Megagem requires 3, 4, or 5 players")
    rng = rng if rng is not None else Random()
    cards_per_player = CARDS_PER_PLAYER[num_players]

    gems = list(GEM_CARDS)
    rng.shuffle(gems)
    players = [
        Player(
            player_id,
            COINS_PER_PLAYER[num_players],
            gems[player_id * cards_per_player : (player_id + 1) * cards_per_player],
            rng=rng,
        )
        for player_id in range(num_players)
    ]

    missions = list(MISSION_CARDS)
    rng.shuffle(missions)
    auctions = list(AUCTION_CARDS)
    rng.shuffle(auctions)
    game = GameState(
        players=players,
        gem_deck=Deck(gems[num_players * cards_per_player :]),
        auction_deck=Deck(auctions),
        available_missions=missions[:MISSIONS_PER_GAME],
        value_chart=value_chart,
        rng=rng,
    )
    _refill_auction_gems(game)
    return game


def _collect_bids(players: Sequence[Player], card: AuctionCard) -> list[int]:
    bids = []
    for player in players:
        bid = player.get_bid()
        available_coins = player.coins
        if card.type is AuctionType.LOAN:
            available_coins += card.value
        bids.append(bid if 0 <= bid <= available_coins else 0)
    return bids


def _select_winner(
    bids: Sequence[int], previous_winner_id: int | None, rng: Random
) -> int:
    highest_bid = max(bids)
    tied_ids = [player_id for player_id, bid in enumerate(bids) if bid == highest_bid]
    if len(tied_ids) == 1:
        return tied_ids[0]
    if previous_winner_id is None:
        return rng.choice(tied_ids)
    return min(
        tied_ids,
        key=lambda player_id: (player_id - previous_winner_id - 1) % len(bids),
    )


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


def _refill_auction_gems(game: GameState) -> None:
    while len(game.auction_gems) < GEMS_ON_AUCTION:
        gem = game.gem_deck.draw()
        if gem is None:
            break
        game.auction_gems.append(gem)


def _claim_missions(game: GameState, player: Player) -> None:
    remaining = []
    for mission in game.available_missions:
        if mission.is_satisfied(player.gem_collection):
            player.mission_cards.append(mission)
        else:
            remaining.append(mission)
    game.available_missions = remaining


def play_round(game: GameState) -> None:
    """Resolve one auction, reveal information, replenish gems, and claim missions."""
    if not game.auction_gems:
        raise ValueError("All gems have already been auctioned")
    card = game.auction_deck.draw()
    if card is None:
        raise RuntimeError("Auction cards ran out before all gems were sold")

    bids = _collect_bids(game.players, card)
    winner_id = _select_winner(bids, game.previous_winner_id, game.rng)
    winner = game.players[winner_id]
    _apply_auction(game, winner, card, bids[winner_id])
    game.previous_winner_id = winner_id

    revealed_gem = winner.reveal_gem()
    if revealed_gem is not None:
        game.value_display[revealed_gem] += 1
    _refill_auction_gems(game)
    _claim_missions(game, winner)


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
    for player in game.players:
        game.value_display.update(player.reveal_remaining_gems())
    gem_values = {
        gem: game.value_chart.get_value(game.value_display[gem])
        for gem in STANDARD_GEMS
    }
    scores = tuple(_score_player(player, gem_values) for player in game.players)
    winning_score = max(scores)
    winner_ids = tuple(
        player.id
        for player, score in zip(game.players, scores)
        if score == winning_score
    )
    return GameResult(game, scores, winner_ids)


def play_game(
    num_players: int,
    *,
    value_chart: ValueChart = VALUE_CHARTS[0],
    rng: Random | None = None,
) -> GameResult:
    game = create_game(num_players, value_chart=value_chart, rng=rng)
    while game.auction_gems:
        play_round(game)
    return finish_game(game)


def print_result(result: GameResult) -> None:
    print("Game Over:")
    for player, score in zip(result.state.players, result.scores):
        print(f" Player {player.id}: {score}")
    winners = ", ".join(str(player_id) for player_id in result.winner_ids)
    if len(result.winner_ids) == 1:
        print(f"\n Player {winners} wins with {result.winning_score} coins!")
    else:
        print(f"\n Players {winners} win with {result.winning_score} coins!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a game of Megagem")
    parser.add_argument("players", type=int, choices=tuple(CARDS_PER_PLAYER), nargs="?")
    parser.add_argument("--seed", type=int, help="Seed for a reproducible game")
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
    print_result(play_game(num_players, value_chart=chart, rng=Random(args.seed)))


if __name__ == "__main__":
    main()
