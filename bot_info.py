"""Build each bot's view using only public information and its own hidden hand."""

from collections import Counter
from typing import TYPE_CHECKING

from bots import BotInfo, PlayerInfo, SelfInfo
from constants import STANDARD_GEMS
from decks import AUCTION_CARDS, GEM_CARDS
from immutable import FrozenMap
from player import Player

if TYPE_CHECKING:
    from harness import GameState


# Return public player information, including hand size but not hidden gems.
def _public_player(player: Player) -> PlayerInfo:
    return PlayerInfo(
        id=player.id,
        coins=player.coins,
        hidden_gem_count=len(player.hidden_gem_hand),
        revealed_gems=tuple(player.public_gem_hand),
        won_gems=FrozenMap({gem: player.gem_collection[gem] for gem in STANDARD_GEMS}),
        auction_cards=tuple(player.auction_cards),
        mission_cards=tuple(player.mission_cards),
        invested_coins=player.invested_coins,
    )


# Build a snapshot containing public information and this player's hidden hand.
# The bot receives no live GameState, Player, or game random generator.
def build_bot_info(game: "GameState", player: Player) -> BotInfo:
    # Collect the public information for this player.
    public = _public_player(player)
    # Add this player's private hand to its public information.
    self_player = SelfInfo(
        id=public.id,
        coins=public.coins,
        hidden_gem_count=public.hidden_gem_count,
        revealed_gems=public.revealed_gems,
        won_gems=public.won_gems,
        auction_cards=public.auction_cards,
        mission_cards=public.mission_cards,
        invested_coins=public.invested_coins,
        hidden_gems=tuple(player.hidden_gem_hand),
    )
    # Infer unknown gem counts from the catalog and this player's observations.
    # These gems are in opponents' hidden hands or the hidden draw pile; their
    # actual locations are not exposed.
    unknown = Counter(GEM_CARDS)
    unknown.subtract(game.value_display)
    unknown.subtract(player.hidden_gem_hand)
    unknown.subtract(game.auction_gems)
    for other in game.players:
        unknown.subtract(other.gem_collection)
    # Infer undrawn auction-card counts from the public auction history.
    auctions = Counter(AUCTION_CARDS)
    auctions.subtract(game.auction_history)
    # Combine these observations into the snapshot sent to the bot.
    return BotInfo(
        self_player=self_player,
        other_players=tuple(_public_player(p) for p in game.players if p is not player),
        num_players=len(game.players),
        round_number=game.round_number,
        current_auction=game.current_auction,
        gem_deck_count=len(game.gem_deck),
        gems_remaining=len(game.gem_deck) + len(game.auction_gems),
        unknown_gems=FrozenMap({gem: unknown[gem] for gem in STANDARD_GEMS}),
        auction_gems=tuple(game.auction_gems),
        value_display=FrozenMap(game.value_display),
        previous_winner_id=game.previous_winner_id,
        value_chart=game.value_chart,
        available_missions=tuple(game.available_missions),
        auction_deck_count=len(game.auction_deck),
        # Include only auction cards with positive remaining counts.
        auction_cards_remaining=FrozenMap(+auctions),
    )
