"""Reuse bot runners across games and print per-entrant totals.

Run from any working directory with:
    python3 /path/to/megagem-harness/experiments/sample_experiment.py

Each tied winner receives one win. Seats stay fixed throughout this simple
example. Change PARTICIPANTS and the settings below to run your own experiment.
"""

import sys
from pathlib import Path

# Allow direct script execution without installing the project as a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collections import Counter
from contextlib import ExitStack
from random import Random

from bot_runner import BotRunner
from bots import Bot
from custom_bots import SmallBidBot
from harness import play_game, print_result

NUM_GAMES = 5
GAME_SEED = 42
BOT_SEED = 7
BOT_TIMEOUT = 1.0  # Use None to disable callback timeouts.

# Labels identify individual entrants, even when they use the same bot class.
PARTICIPANTS: tuple[tuple[str, type[Bot]], ...] = (
    ("SmallBidBot", SmallBidBot),
    ("DefaultBot A", Bot),
    ("DefaultBot B", Bot),
)


def main() -> None:
    total_points: Counter[str] = Counter()
    games_won: Counter[str] = Counter()

    # Each runner is created once and reused in every game. ExitStack closes all
    # workers at the end of the experiment, including when a game raises an error.
    with ExitStack() as stack:
        runners = [
            stack.enter_context(
                BotRunner(bot_class, timeout=BOT_TIMEOUT, seed=BOT_SEED + index)
            )
            for index, (_, bot_class) in enumerate(PARTICIPANTS)
        ]
        for game_index in range(NUM_GAMES):
            print(f"\nGame {game_index + 1}/{NUM_GAMES}")
            print(
                "Seats: "
                + ", ".join(
                    f"{index} = {label}"
                    for index, (label, _) in enumerate(PARTICIPANTS)
                )
            )
            result = play_game(
                len(runners), bots=runners, rng=Random(GAME_SEED + game_index)
            )
            print_result(result)

            for player_id, score in enumerate(result.scores):
                total_points[PARTICIPANTS[player_id][0]] += score
            # Every tied winner receives one win; wins can sum to more than NUM_GAMES.
            for player_id in result.winner_ids:
                games_won[PARTICIPANTS[player_id][0]] += 1

    print(f"\nAggregate results across {NUM_GAMES} games")
    print(f"{'Bot':<24} {'Total points':>12} {'Games won':>10}")
    print("-" * 48)
    for label, _ in PARTICIPANTS:
        print(f"{label:<24} {total_points[label]:>12} {games_won[label]:>10}")


if __name__ == "__main__":
    main()
