"""派閥非依存の共通メカニクス(ドロー/シャッフル等)。

循環 import を避けるため faction を import しない。
"""
from __future__ import annotations

import dataclasses
from typing import List

from .state import GameState
from .types import FactionId


def draw_cards(state: GameState, faction: FactionId, n: int, rng) -> GameState:
    """山札上から n 枚引く(2.1)。山札切れ時は捨て山をシャッフルして継続。"""
    deck = list(state.deck)
    discard = list(state.discard)
    fs = state.fs(faction)
    hand = list(fs.hand)
    for _ in range(n):
        if not deck:
            if not discard:
                break
            deck = discard
            discard = []
            rng.shuffle(deck)
        hand.append(deck.pop())  # 末尾=山札の一番上
    new_fs = dataclasses.replace(fs, hand=tuple(hand))
    return state.replace(deck=tuple(deck), discard=tuple(discard)).with_faction_state(new_fs)


def discard_card(state: GameState, faction: FactionId, card_id: str) -> GameState:
    """手札から1枚を捨て山へ。"""
    fs = state.fs(faction)
    hand = list(fs.hand)
    hand.remove(card_id)
    new_fs = dataclasses.replace(fs, hand=tuple(hand))
    return (state.replace(discard=state.discard + (card_id,))
            .with_faction_state(new_fs))
