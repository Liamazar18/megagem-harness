from bots import Bot, BotInfo, RoundResult
from cards import AUCTION_CARDS


class LiamsBot(Bot):
    def __init__(self) -> None:
        self.games_played = 0
        self.rounds_seen = 0

    def on_game_start(self) -> None:
        self.games_played += 1
        self.rounds_seen = 0

    def get_bid(self, info: BotInfo) -> int:
        # if the auction card shows a card that the bot already has, bid 1 coin, otherwise bid 0 coins
        # if the auction card shows 1 gem, bet 1 coint, if the auction card shows 2 gems, bet 2 coins
        if info.current_auction == AUCTION_CARDS[4]:
            return min(1, info.self_player.coins)
        elif info.current_auction == AUCTION_CARDS[5]:
            return min(2, info.self_player.coins)
        return min(1, info.self_player.coins)

    def on_round_end(self, info: BotInfo, result: RoundResult) -> None:
        self.rounds_seen += 1
