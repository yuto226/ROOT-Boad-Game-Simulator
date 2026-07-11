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


def award_vp(state: GameState, faction: FactionId, delta: int) -> GameState:
    """VP を加減算する中央ヘルパ(3.2 / 14.2)。

    圧倒カードの発動(3.3.1)・共闘軍の結成(9.2.8)による「以後VPを
    獲得できない」を一点で強制する:

    - ``fs.dominance_card is not None`` → no-op(発動済みは得点表から
      マーカーが除かれる。VP凍結)。
    - 放浪部族で ``coalition_with is not None`` → no-op(9.2.8 の凍結)。
    - それ以外 → ``vp = max(0, vp + delta)``(VP非負クランプを共通化,
      鷲巣の恥辱 7.7.1 のクランプもこれで表現する)。

    直接 ``vp=fs.vp+n`` を書く代わりに必ずこれを経由すること(14.2)。
    """
    fs = state.fs(faction)
    if fs.dominance_card is not None:
        return state
    if getattr(fs, "coalition_with", None) is not None:
        return state
    new_vp = max(0, fs.vp + delta)
    return state.with_faction_state(dataclasses.replace(fs, vp=new_vp))


def to_discard(state: GameState, card_id: str) -> GameState:
    """カード1枚を「捨て山に置く」処理(3.3.3 の一般化, 14.3)。

    公式法典(英語版 Law)3.3.3 に従い、圧倒カードが捨て山に置かれるときは
    常にゲーム盤の横(``dominance_aside``)へ回す。それ以外は捨て山へ。

    山札切れの再シャッフル(discard→deck)はこの経路を通らない(対象外)。
    """
    if state.cards.get(card_id).is_dominance:
        return state.replace(dominance_aside=state.dominance_aside + (card_id,))
    return state.replace(discard=state.discard + (card_id,))


def discard_card(state: GameState, faction: FactionId, card_id: str) -> GameState:
    """手札から1枚を捨て山へ(圧倒カードは盤脇へリダイレクト, 3.3.3/14.3)。"""
    fs = state.fs(faction)
    hand = list(fs.hand)
    hand.remove(card_id)
    new_fs = dataclasses.replace(fs, hand=tuple(hand))
    return to_discard(state.with_faction_state(new_fs), card_id)
