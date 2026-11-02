"""Regression checks for ownership, auction rules, and complete-game invariants."""

import unittest
from collections import Counter, deque
from dataclasses import FrozenInstanceError
from random import Random
from unittest.mock import patch

from constants import (
    CARDS_PER_PLAYER,
    COINS_PER_PLAYER,
    STANDARD_GEMS,
    AuctionType,
    GemType,
)
from constants import WildCardRequirement as Pattern
from decks import AUCTION_CARDS, GEM_CARDS, MISSION_CARDS, VALUE_CHARTS
from harness import (
    GameState,
    _select_winner,
    create_game,
    finish_game,
    play_game,
    play_round,
)
from lib import AuctionCard, Deck, MissionCard, Player, ValueChart

BLUE, GREEN, PURPLE, YELLOW, PINK = STANDARD_GEMS


class CardTests(unittest.TestCase):
    def test_deck_owns_its_list_and_handles_exhaustion(self):
        card = AuctionCard(AuctionType.LOAN, 10)
        source = [card]
        deck = Deck(source)
        source.clear()
        self.assertEqual(len(deck), 1)
        self.assertIs(deck.draw(), card)
        self.assertFalse(deck)
        self.assertIsNone(deck.draw())

    def test_card_definitions_are_immutable_and_copy_requirements(self):
        gem_requirements = {BLUE: 2}
        mission = MissionCard(value=5, gem_requirements=gem_requirements)
        gem_requirements[BLUE] = 99
        self.assertEqual(mission.gem_requirements[BLUE], 2)
        with self.assertRaises(TypeError):
            mission.gem_requirements[BLUE] = 3
        with self.assertRaises(FrozenInstanceError):
            mission.value = 99
        with self.assertRaises(FrozenInstanceError):
            AUCTION_CARDS[0].value = 99

    def test_mission_matching(self):
        cases = (
            (MissionCard(5, {BLUE: 1, GREEN: 1}), [BLUE, GREEN], True),
            (MissionCard(5, {BLUE: 1, GREEN: 1}), [BLUE, BLUE], False),
            (MissionCard(5, {BLUE: 1, GemType.WILD_CARD: 2}), [BLUE, GREEN], False),
            (MissionCard(5, {BLUE: 1, GemType.WILD_CARD: 2}), [BLUE] * 3, True),
            (MissionCard(10, {GemType.WILD_CARD: 3}, Pattern.SAME), [BLUE] * 3, True),
            (
                MissionCard(10, {GemType.WILD_CARD: 3}, Pattern.SAME),
                [BLUE, BLUE, GREEN],
                False,
            ),
            (
                MissionCard(10, {GemType.WILD_CARD: 4}, Pattern.DIFFERENT),
                [BLUE, GREEN, PURPLE, YELLOW],
                True,
            ),
            (
                MissionCard(10, {GemType.WILD_CARD: 4}, Pattern.DIFFERENT),
                [BLUE, BLUE, GREEN, PURPLE],
                False,
            ),
            (
                MissionCard(15, {GemType.WILD_CARD: 4}, Pattern.PAIRS),
                [BLUE, BLUE, GREEN, GREEN],
                True,
            ),
            (
                MissionCard(15, {GemType.WILD_CARD: 4}, Pattern.PAIRS),
                [BLUE, BLUE, GREEN, PURPLE],
                False,
            ),
        )
        for mission, gems, expected in cases:
            with self.subTest(mission=mission, gems=gems):
                self.assertEqual(mission.is_satisfied(Counter(gems)), expected)

    def test_value_chart_boundaries(self):
        chart = ValueChart("test", (0, 4, 8, 12, 16, 20))
        self.assertEqual(chart.name, "test")
        self.assertEqual(chart.get_value(0), 0)
        self.assertEqual(chart.get_value(6), 20)
        for count in (-1, 7):
            with self.subTest(count=count), self.assertRaises(ValueError):
                chart.get_value(count)
        with self.assertRaises(ValueError):
            ValueChart("bad", (1, 2))

    def test_catalog_counts_and_unique_missions(self):
        self.assertEqual(Counter(GEM_CARDS), Counter(dict.fromkeys(STANDARD_GEMS, 6)))
        self.assertEqual(len(MISSION_CARDS), 30)
        self.assertEqual(len(AUCTION_CARDS), 25)
        self.assertEqual(
            sum(c.value for c in AUCTION_CARDS if c.type is AuctionType.AUCTION), 22
        )
        definitions = {
            (m.value, frozenset(m.gem_requirements.items()), m.wild_card_requirement)
            for m in MISSION_CARDS
        }
        self.assertEqual(len(definitions), 30)


class GameTests(unittest.TestCase):
    def test_setup_keeps_information_out_of_scoring_collections(self):
        for count in (3, 4, 5):
            with self.subTest(players=count):
                game = create_game(count, rng=Random(0))
                self.assertEqual(sum(game.value_display.values()), 0)
                self.assertEqual(len(game.available_missions), 4)
                self.assertEqual(len(game.auction_gems), 2)
                for player in game.players:
                    self.assertEqual(player.coins, COINS_PER_PLAYER[count])
                    self.assertEqual(
                        len(player.hidden_gem_hand), CARDS_PER_PLAYER[count]
                    )
                    self.assertFalse(player.gem_collection)
                total = sum(len(p.hidden_gem_hand) for p in game.players)
                self.assertEqual(
                    total + len(game.gem_deck) + len(game.auction_gems), 30
                )
        for count in (0, 2, 6):
            with self.subTest(players=count), self.assertRaises(ValueError):
                create_game(count)

    def test_player_owns_hand_and_reveals_only_once(self):
        hand = [BLUE, GREEN]
        player = Player(0, 35, hand)
        hand.clear()
        self.assertEqual(player.reveal_remaining_gems(), (BLUE, GREEN))
        self.assertEqual(player.reveal_remaining_gems(), ())
        self.assertEqual(player.public_gem_hand, [BLUE, GREEN])
        self.assertFalse(player.gem_collection)
        self.assertIsNone(player.reveal_gem())

    def test_tie_priority_starts_after_previous_winner_and_wraps(self):
        self.assertEqual(_select_winner([0, 4, 4], 1, Random(0)), 2)
        self.assertEqual(_select_winner([4, 0, 4], 2, Random(0)), 0)
        self.assertEqual(_select_winner([0, 4, 0], 1, Random(0)), 1)
        rng = Random(0)
        with patch.object(rng, "choice", return_value=4) as choose:
            self.assertEqual(_select_winner([5, 5, 0, 0, 5], None, rng), 4)
            choose.assert_called_once_with([0, 1, 4])

    def test_all_zero_bids_rotate_and_finish(self):
        game = create_game(3, rng=Random(0))
        with patch.object(Player, "get_bid", return_value=0):
            while game.auction_gems:
                previous = game.previous_winner_id
                play_round(game)
                if previous is not None:
                    self.assertEqual(game.previous_winner_id, (previous + 1) % 3)
        result = finish_game(game)
        self.assertEqual(sum(sum(p.gem_collection.values()) for p in game.players), 15)
        self.assertTrue(result.winner_ids)

    def test_loan_funding_investment_return_and_last_single_gem(self):
        rng = Random(0)
        players = [Player(i, 35, [], rng=rng) for i in range(3)]
        cards = (
            AuctionCard(AuctionType.LOAN, 20),
            AuctionCard(AuctionType.INVEST, 5),
            AuctionCard(AuctionType.AUCTION, 2),
        )
        game = GameState(
            players,
            Deck(),
            Deck(reversed(cards)),
            [],
            VALUE_CHARTS[0],
            rng,
            auction_gems=deque([BLUE]),
        )
        with (
            patch.object(players[0], "get_bid", side_effect=[40, 10, 1]),
            patch.object(players[1], "get_bid", return_value=0),
            patch.object(players[2], "get_bid", return_value=0),
        ):
            for _ in cards:
                play_round(game)
        self.assertEqual(players[0].coins, 4)
        self.assertEqual(players[0].gem_collection, Counter([BLUE]))
        self.assertEqual(players[0].invested_coins, 10)
        self.assertEqual(cards[1].value, 5)
        self.assertEqual(finish_game(game).scores[0], -1)

    def test_unaffordable_bids_become_zero(self):
        game = create_game(3, rng=Random(0))
        game.auction_deck = Deck([AuctionCard(AuctionType.INVEST, 5)])
        with (
            patch.object(game.players[0], "get_bid", return_value=100),
            patch.object(game.players[1], "get_bid", return_value=-1),
            patch.object(game.players[2], "get_bid", return_value=1),
        ):
            play_round(game)
        self.assertEqual(game.previous_winner_id, 2)
        self.assertEqual([p.coins for p in game.players], [35, 35, 34])

    def test_one_collection_can_claim_multiple_missions_without_replenishment(self):
        game = create_game(3, rng=Random(0))
        game.auction_gems = deque([BLUE, GREEN])
        game.gem_deck = Deck()
        game.auction_deck = Deck([AuctionCard(AuctionType.AUCTION, 2)])
        first = MissionCard(5, {BLUE: 1})
        second = MissionCard(10, {BLUE: 1, GREEN: 1})
        unavailable = MissionCard(10, {PINK: 1})
        game.available_missions = [first, second, unavailable]
        with (
            patch.object(game.players[0], "get_bid", return_value=1),
            patch.object(game.players[1], "get_bid", return_value=0),
            patch.object(game.players[2], "get_bid", return_value=0),
        ):
            play_round(game)
        self.assertEqual(game.players[0].mission_cards, [first, second])
        self.assertEqual(game.players[0].gem_collection, Counter([BLUE, GREEN]))
        self.assertEqual(game.available_missions, [unavailable])

    def test_cannot_score_or_play_at_the_wrong_stage(self):
        game = create_game(3, rng=Random(0))
        with self.assertRaises(ValueError):
            finish_game(game)
        game.auction_deck = Deck()
        with self.assertRaises(RuntimeError):
            play_round(game)
        game.auction_gems.clear()
        with self.assertRaises(ValueError):
            play_round(game)

    def test_reproducible_games_without_global_card_mutation(self):
        first = play_game(3, rng=Random(17))
        second = play_game(3, rng=Random(17))
        self.assertEqual(first.scores, second.scores)
        self.assertEqual(first.winner_ids, second.winner_ids)
        self.assertEqual(
            [c.value for c in AUCTION_CARDS if c.type is AuctionType.INVEST],
            [5, 5, 10, 10],
        )

    def test_complete_games_conserve_cards_and_finalize_once(self):
        for chart in VALUE_CHARTS:
            for count in (3, 4, 5):
                for seed in range(20):
                    with self.subTest(chart=chart.name, players=count, seed=seed):
                        result = play_game(count, value_chart=chart, rng=Random(seed))
                        game = result.state
                        starting_cards = count * CARDS_PER_PLAYER[count]
                        acquired = Counter()
                        revealed = Counter()
                        for player in game.players:
                            self.assertGreaterEqual(player.coins, 0)
                            self.assertFalse(player.hidden_gem_hand)
                            acquired.update(player.gem_collection)
                            revealed.update(player.public_gem_hand)
                        self.assertEqual(acquired + revealed, Counter(GEM_CARDS))
                        self.assertEqual(sum(acquired.values()), 30 - starting_cards)
                        self.assertEqual(revealed, game.value_display)
                        self.assertEqual(
                            len(game.available_missions)
                            + sum(len(p.mission_cards) for p in game.players),
                            4,
                        )
                        self.assertEqual(result.winning_score, max(result.scores))
                        self.assertEqual(
                            result.winner_ids,
                            tuple(
                                i
                                for i, score in enumerate(result.scores)
                                if score == max(result.scores)
                            ),
                        )
                        self.assertEqual(finish_game(game).scores, result.scores)
                        self.assertEqual(game.value_display, revealed)


if __name__ == "__main__":
    unittest.main()
