"""A minimal stateful example; run with --bots custom_bots:SmallBidBot."""

from bots import Bot, BotInfo, RoundResult


class SmallBidBot(Bot):
    """Bid one coin when affordable, keeping lifetime and per-game statistics."""

    def __init__(self) -> None:
        self.games_played = 0
        self.rounds_seen = 0

    def on_game_start(self) -> None:
        self.games_played += 1
        self.rounds_seen = 0

    def get_bid(self, info: BotInfo) -> int:
        return min(1, info.self_player.coins)

    def on_round_end(self, info: BotInfo, result: RoundResult) -> None:
        self.rounds_seen += 1
