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


# Returns a PlayerInfo object with all information about a player that has been made public
# Notably, does not include the hidden_gem_hand, as this is private information for a player
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


# Creates a BotInfo object based on the game state, given the player that the bot acts for
# The bot receives the game state/public information for all players, plut the private information
# for the player that it represents (hidden gem hand)
def build_bot_info(game: "GameState", player: Player) -> BotInfo:
    # Publicly available information about the player the bot represents
    public = _public_player(player)
    # Combines public information with the hidden gem hand to create the information
    # about the player known only by its bot
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
    # Calculates the number of gem cards that have not been revealed to this player,
    # meaning that they either have yet to be revealed in auction, or are one of the
    # hidden gems of another player 
    unknown = Counter(GEM_CARDS)
    unknown.subtract(game.value_display)
    unknown.subtract(player.hidden_gem_hand)
    unknown.subtract(game.auction_gems)
    for other in game.players:
        unknown.subtract(other.gem_collection)
    # Calculates which auction cards have yet to appear
    auctions = Counter(AUCTION_CARDS)
    auctions.subtract(game.auction_history)
    # Combines all information into a BotInfo object, to be sent to the bot
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
        auction_cards_remaining=FrozenMap(+auctions), # Only includes auction cards with a positive count remaining
    )
