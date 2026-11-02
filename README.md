# Megagem harness

A standard-library-only simulator for 3–5 players, using Python 3.10 or newer.
Bidding and hidden-gem selection still use placeholder random policies.

```sh
python3 harness.py 3 --seed 42
python3 harness.py 5 --chart C --seed 42
```

Without a player-count argument, the CLI asks for one. Chart A is the default.

## Using the simulator

```python
from random import Random
from harness import play_game

result = play_game(3, rng=Random(42))
print(result.scores, result.winner_ids)
```

`play_game()` returns a `GameResult` without printing. Its `state` contains the
final players, claimed missions, and value display. Scores are a snapshot; the
state remains mutable for inspection. Console output lives in `print_result()`.

For round-by-round inspection, use `create_game()`, call `play_round()` while
`game.auction_gems` is nonempty, and then call `finish_game()`. Finalization reveals
all remaining hand cards and can be repeated without counting them twice.
Each game shares one random generator across setup, tie resolution, and placeholder
player decisions, so a seeded game is reproducible without changing global random
state. Player IDs follow seating order, with increasing IDs going to the left.

## Layout

- `constants.py`: enums and setup rules.
- `lib.py`: immutable cards and charts, `Deck[T]`, and mutable player state.
- `decks.py`: immutable catalogs of gems, missions, auctions, and value charts.
- `harness.py`: setup, round resolution, scoring, and the CLI.
- `tests/test_megagem.py`: ownership, rule boundaries, and complete-game checks.

`Deck[T]` replaces the three card-collection subclasses. It copies its input,
draws from the end, and returns `None` when empty. Shuffle cards before constructing
a deck. Acquired gems use `Counter[GemType]`; wildcard mission requirements are
checked against real gem counts rather than a second, manually maintained total.
Card catalogs can be shared safely because their cards and nested requirements
are immutable. Per-game changes belong to players and `GameState`.
Mission cards expose their coin payout as `value` and their required gem counts
as `gem_requirements`.

## Checks

Tests require no third-party packages:

```sh
python3 -B -m unittest discover -s tests -v
```

If Ruff and mypy are installed:

```sh
ruff check .
ruff format --check .
mypy
```
