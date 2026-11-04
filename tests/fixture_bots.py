"""Small importable bots used by worker and integration tests."""

import os
import random
import sys
import threading
import time

from bots import Bot, BotInfo
from constants import AuctionType


class InvalidBidBot(Bot):
    def get_bid(self, info: BotInfo) -> int:
        return {0: 100, 1: -1, 2: 1}[info.self_player.id]


class AuditBot(Bot):
    def __init__(self):
        self.games = 0
        self.rounds = 0
        self.ends = 0

    def on_game_start(self):
        self.games += 1
        self.rounds = 0

    def get_bid(self, info):
        if info.round_number == 999:
            return self.games * 100000 + self.ends * 1000 + self.rounds
        self.last_bid_info = info
        return 0

    def choose_hidden_gem(self, info, bids):
        before = self.last_bid_info
        card = info.current_auction
        assert card == before.current_auction
        expected_coins = before.self_player.coins - bids[info.self_player.id]
        if card.type is AuctionType.LOAN:
            expected_coins += card.value
        assert info.self_player.coins == expected_coins
        awarded = (
            min(card.value, len(before.auction_gems))
            if card.type is AuctionType.AUCTION
            else 0
        )
        assert info.auction_gems == before.auction_gems[awarded:]
        assert (
            sum(info.self_player.won_gems.values())
            == sum(before.self_player.won_gems.values()) + awarded
        )
        self.last_reveal_info = info
        self.last_bids = bids
        return 0

    def on_round_end(self, info, result):
        assert result.winner_id in result.bids
        assert result.winning_bid == result.bids[result.winner_id]
        assert info.previous_winner_id == result.winner_id
        self.rounds += 1
        self.last_round = result
        self.last_info = info

    def on_game_end(self, info, result):
        assert not info.self_player.hidden_gems
        assert all(p.hidden_gem_count == 0 for p in info.other_players)
        assert sum(info.unknown_gems.values()) == 0
        self.ends += 1
        self.last_info = info
        self.summary = result


class TimeoutBot(Bot):
    def __init__(self):
        self.value = 7
        self.starts = 0

    def on_game_start(self):
        self.starts += 1

    def get_bid(self, info):
        if info.round_number == 1:
            self.value = 999
            time.sleep(10)
        return self.value + self.starts


class ExceptionBot(TimeoutBot):
    def get_bid(self, info):
        if info.round_number == 1:
            self.value = 999
            raise RuntimeError("Intentional callback failure")
        return self.value + self.starts


class SlowBot(Bot):
    def on_game_start(self):
        time.sleep(0.2)

    def get_bid(self, info):
        time.sleep(0.2)
        return 0

    def choose_hidden_gem(self, info, bids):
        time.sleep(0.2)
        return 0

    def on_round_end(self, info, result):
        time.sleep(0.2)

    def on_game_end(self, info, result):
        time.sleep(0.2)


class MutatingBot(Bot):
    def get_bid(self, info):
        # Even deliberately bypassing the frozen wrapper affects only this copy.
        object.__setattr__(info.self_player, "coins", 999)
        object.__setattr__(info.current_auction, "value", 999)
        assert not hasattr(info, "rng")
        assert sys.argv == ["megagem-bot"]
        assert all(not hasattr(p, "hidden_gems") for p in info.other_players)
        return 1


class ResourceBot(Bot):
    def __init__(self):
        self.lock = threading.Lock()
        self.calls = 0

    def save_state(self):
        return self.calls

    def load_state(self, state):
        self.calls = state
        self.lock = threading.Lock()

    def get_bid(self, info):
        self.calls += 1
        return self.calls


class RandomBot(Bot):
    def get_bid(self, info):
        return random.randrange(min(info.self_player.coins, 5) + 1)


class CrashBot(TimeoutBot):
    def get_bid(self, info):
        if info.round_number == 1:
            self.value = 999
            os._exit(1)
        return self.value + self.starts


class FailedCheckpointBot(Bot):
    def __init__(self):
        self.calls = 0

    def get_bid(self, info):
        self.calls += 1
        if info.round_number == 1:
            self.lock = threading.Lock()
        return self.calls


class RandomTimeoutBot(Bot):
    def get_bid(self, info):
        if info.round_number == 1:
            random.random()
            time.sleep(10)
        return random.randrange(1000000)
