"""Bot observations, validation, worker isolation, and checkpoint recovery."""

import pickle
import time
import unittest
from collections import Counter
from dataclasses import FrozenInstanceError, replace
from random import Random
from unittest.mock import patch

from bot_info import build_bot_info
from bot_runner import BotRunner
from bots import Bot, GameSummary, RoundResult
from constants import AuctionType, GemType
from decks import GEM_CARDS
from harness import create_game, finish_game, play_game, play_round
from immutable import FrozenMap
from lib import AuctionCard, Deck
from tests.fixture_bots import (
    AuditBot,
    CrashBot,
    ExceptionBot,
    FailedCheckpointBot,
    MutatingBot,
    RandomBot,
    RandomTimeoutBot,
    ResourceBot,
    SlowBot,
    TimeoutBot,
)


class InfoTests(unittest.TestCase):
    def test_frozen_maps_have_mapping_equality_and_consistent_hashes(self):
        first = FrozenMap({0: 2, 1: 3})
        second = FrozenMap({1: 3, 0: 2})
        self.assertEqual(first, second)
        self.assertEqual(first, {0: 2, 1: 3})
        self.assertEqual(hash(first), hash(second))

    @classmethod
    def setUpClass(cls):
        cls.runners = [BotRunner(seed=i) for i in range(3)]

    @classmethod
    def tearDownClass(cls):
        for runner in cls.runners:
            runner.close()

    def make_game(self):
        return create_game(3, bots=self.runners, rng=Random(9))

    def test_views_are_immutable_detached_and_pickleable(self):
        game = self.make_game()
        player = game.players[0]
        info = build_bot_info(game, player)
        self.assertEqual(pickle.loads(pickle.dumps(info)), info)
        with self.assertRaises(FrozenInstanceError):
            info.self_player.coins = 999
        with self.assertRaises(TypeError):
            info.value_display[next(iter(info.value_display))] = 999
        with self.assertRaises(TypeError):
            info.available_missions[0].gem_requirements[GemType.WILD_CARD] = 999
        player.coins -= 1
        player.hidden_gem_hand.clear()
        self.assertEqual(info.self_player.coins, 35)
        self.assertEqual(len(info.self_player.hidden_gems), 5)
        self.assertFalse(hasattr(info, "rng"))
        self.assertTrue(all(not hasattr(p, "hidden_gems") for p in info.other_players))
        self.assertEqual([p.id for p in info.other_players], [1, 2])

    def test_unknown_counts_do_not_depend_on_hidden_arrangement(self):
        game = self.make_game()
        info = build_bot_info(game, game.players[0])
        self.assertEqual(sum(info.unknown_gems.values()), info.gem_deck_count + 10)
        pool = list(Counter(info.unknown_gems).elements())
        for cards in (pool, list(reversed(pool))):
            offset = 0
            for player in game.players[1:]:
                size = len(player.hidden_gem_hand)
                player.hidden_gem_hand[:] = cards[offset : offset + size]
                offset += size
            game.gem_deck = Deck(cards[offset:])
            self.assertEqual(build_bot_info(game, game.players[0]), info)

    def test_bot_calls_never_advance_game_randomness(self):
        game = self.make_game()
        game.current_auction = AuctionCard(AuctionType.AUCTION, 1)
        state = game.rng.getstate()
        player = game.players[0]
        info = build_bot_info(game, player)
        player.get_bid(info)
        player.choose_hidden_gem(info, FrozenMap({0: 0, 1: 0, 2: 0}))
        self.assertEqual(game.rng.getstate(), state)

    def test_bid_and_reveal_validation_at_player_boundary(self):
        game = self.make_game()
        player = game.players[0]
        game.current_auction = AuctionCard(AuctionType.INVEST, 5)
        info = build_bot_info(game, player)
        for value in (None, -1, 36, True, 1.5, "3"):
            with (
                self.subTest(value=value),
                patch.object(player.bot, "call", return_value=value),
            ):
                self.assertEqual(player.get_bid(info), 0)
        game.current_auction = AuctionCard(AuctionType.LOAN, 20)
        with patch.object(player.bot, "call", return_value=40):
            self.assertEqual(player.get_bid(build_bot_info(game, player)), 40)
        with patch.object(player.bot, "call", return_value=56):
            self.assertEqual(player.get_bid(build_bot_info(game, player)), 0)
        for value in (None, -1, len(player.hidden_gem_hand), True, 1.5, "0"):
            with (
                self.subTest(value=value),
                patch.object(player.bot, "call", return_value=value),
            ):
                index = player.choose_hidden_gem(info, FrozenMap())
                self.assertIs(type(index), int)
                self.assertIn(index, range(len(player.hidden_gem_hand)))

    def test_auction_counts_and_full_information_conservation(self):
        game = self.make_game()
        play_round(game)
        for player in game.players:
            info = build_bot_info(game, player)
            self.assertEqual(
                sum(info.auction_cards_remaining.values()), info.auction_deck_count
            )
            self.assertEqual(
                info.gems_remaining, info.gem_deck_count + len(info.auction_gems)
            )
            known = Counter(info.value_display)
            known.update(info.self_player.hidden_gems)
            known.update(info.auction_gems)
            known.update(info.self_player.won_gems)
            for other in info.other_players:
                known.update(other.won_gems)
            self.assertEqual(known + Counter(info.unknown_gems), Counter(GEM_CARDS))


class WorkerTests(unittest.TestCase):
    def setUp(self):
        # Building observations needs no live opponent workers after setup.
        self.game = create_game(3, rng=Random(0))
        self.addCleanup(self.game.close)
        self.info = build_bot_info(self.game, self.game.players[0])

    def runner(self, bot_class=Bot, **kwargs):
        runner = BotRunner(bot_class, **kwargs)
        self.addCleanup(runner.close)
        return runner

    def test_timeout_restores_memory_without_replaying_game_start(self):
        runner = self.runner(TimeoutBot, timeout=0.05)
        runner.call("on_game_start")
        self.assertEqual(runner.call("get_bid", self.info), 8)
        started = time.monotonic()
        with self.assertLogs("bot_runner", level="WARNING"):
            self.assertIsNone(
                runner.call("get_bid", replace(self.info, round_number=1))
            )
        self.assertLess(time.monotonic() - started, 2)
        self.assertIn("Timeout", runner.last_error)
        self.assertEqual(runner.call("get_bid", replace(self.info, round_number=2)), 8)
        self.assertIsNone(runner.last_error)

    def test_exceptions_roll_back_partial_memory(self):
        runner = self.runner(ExceptionBot)
        runner.call("on_game_start")
        with self.assertLogs("bot_runner", level="WARNING"):
            self.assertIsNone(
                runner.call("get_bid", replace(self.info, round_number=1))
            )
        self.assertIn("Intentional callback failure", runner.last_error)
        self.assertEqual(runner.call("get_bid", self.info), 8)

    def test_crashes_and_failed_checkpoints_keep_previous_memory(self):
        for bot_class, expected in ((CrashBot, 8), (FailedCheckpointBot, 2)):
            with self.subTest(bot=bot_class):
                runner = self.runner(bot_class)
                runner.call("on_game_start")
                runner.call("get_bid", self.info)
                with self.assertLogs("bot_runner", level="WARNING"):
                    self.assertIsNone(
                        runner.call("get_bid", replace(self.info, round_number=1))
                    )
                self.assertEqual(runner.call("get_bid", self.info), expected)

    def test_timeout_also_restores_private_random_state(self):
        runner = self.runner(RandomTimeoutBot, timeout=0.05, seed=19)
        control = self.runner(RandomTimeoutBot, seed=19)
        self.assertEqual(
            runner.call("get_bid", self.info), control.call("get_bid", self.info)
        )
        with self.assertLogs("bot_runner", level="WARNING"):
            runner.call("get_bid", replace(self.info, round_number=1))
        self.assertEqual(
            runner.call("get_bid", self.info), control.call("get_bid", self.info)
        )

    def test_every_callback_has_a_timeout(self):
        runner = self.runner(SlowBot, timeout=0.03)
        bids = FrozenMap({0: 0, 1: 0, 2: 0})
        card = AuctionCard(AuctionType.AUCTION, 1)
        result = RoundResult(card, bids, 0, 0, None)
        summary = GameSummary(FrozenMap({0: 1, 1: 0, 2: 0}), (0,), 1)
        for method, args in (
            ("on_game_start", ()),
            ("get_bid", (self.info,)),
            ("choose_hidden_gem", (self.info, bids)),
            ("on_round_end", (self.info, result)),
            ("on_game_end", (self.info, summary)),
        ):
            with (
                self.subTest(method=method),
                self.assertLogs("bot_runner", level="WARNING"),
            ):
                self.assertIsNone(runner.call(method, *args))
                self.assertIn("Timeout", runner.last_error)

    def test_no_timeout_allows_slow_calls(self):
        runner = self.runner(SlowBot, timeout=None)
        self.assertEqual(runner.call("get_bid", self.info), 0)
        self.assertIsNone(runner.last_error)

    def test_custom_save_restore_hooks_recreate_resources(self):
        runner = self.runner(ResourceBot)
        self.assertEqual(runner.call("get_bid", self.info), 1)
        runner.close()
        self.assertEqual(runner.call("get_bid", self.info), 2)

    def test_mutating_a_worker_snapshot_cannot_change_the_game(self):
        runner = self.runner(MutatingBot)
        self.game.current_auction = AuctionCard(AuctionType.LOAN, 10)
        info = build_bot_info(self.game, self.game.players[0])
        self.assertEqual(runner.call("get_bid", info), 1)
        self.assertEqual(self.game.players[0].coins, 35)
        self.assertEqual(self.game.current_auction.value, 10)
        self.assertEqual(info.self_player.coins, 35)

    def test_notifications_once_and_memory_survives_between_games(self):
        runners = [self.runner(AuditBot) for _ in range(3)]
        result = play_game(3, bots=runners, rng=Random(3))
        info = replace(
            build_bot_info(result.state, result.state.players[0]), round_number=999
        )
        expected = 100000 + 1000 + result.state.round_number
        self.assertEqual(runners[0].call("get_bid", info), expected)
        finish_game(result.state)
        self.assertEqual(runners[0].call("get_bid", info), expected)
        next_result = play_game(3, bots=runners, rng=Random(4))
        next_info = replace(
            build_bot_info(next_result.state, next_result.state.players[0]),
            round_number=999,
        )
        self.assertEqual(
            runners[0].call("get_bid", next_info),
            200000 + 2000 + next_result.state.round_number,
        )
        for runner in runners:
            self.assertIsNone(runner.last_error)

    def test_independent_seeds_make_random_bots_reproducible(self):
        first = play_game(3, bots=[RandomBot] * 3, rng=Random(7), bot_seed=19)
        second = play_game(3, bots=[RandomBot] * 3, rng=Random(7), bot_seed=19)
        self.assertEqual(first.scores, second.scores)
        self.assertEqual(first.winner_ids, second.winner_ids)
        self.assertTrue(all(p.bot._process is None for p in first.state.players))

    def test_bad_configuration(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                BotRunner(timeout=timeout)
        with self.assertRaises(ValueError):
            create_game(3, bots=[Bot])
        runner = self.runner()
        with self.assertRaises(ValueError):
            create_game(3, bots=[runner] * 3)
        with self.assertRaises(ValueError):
            runner.call("not_a_callback")


if __name__ == "__main__":
    unittest.main()
