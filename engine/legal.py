"""合法手の列挙(3.2 / 3.3)。

pending スタックが空でなければスタック先頭(末尾要素)の Decision に
対する選択肢のみを返す。空ならターンプレイヤーの派閥ロジックへ
ディスパッチする(DESIGN.md 3.2)。
"""
from __future__ import annotations

from typing import List

from .actions import (
    Action,
    AllocateHitsDecision,
    AmbushAttackerDecision,
    AmbushChoice,
    AmbushDefenderDecision,
    DiscardCard,
    DiscardDecision,
    EyrieDecreeDecision,
    EyrieLeaderDecision,
    EyrieRoostDecision,
    EyrieSetupCornerDecision,
    OutrageDecision,
    SetupChooseKeep,
    SetupKeepDecision,
    SupportersLimitDecision,
)
from .battle import _matching_ambush, allocate_options
from .state import GameState
from .types import Corner


def legal_actions(state: GameState) -> List[Action]:
    """現状態で選択可能な全アクション。"""
    if state.finished:
        return []
    if state.pending:
        return _decision_options(state)
    from .factions import get_logic
    return get_logic(state.current_faction()).legal_actions(state)


def _decision_options(state: GameState) -> List[Action]:
    dec = state.pending[-1]

    if isinstance(dec, SetupKeepDecision):
        # 城砦の隅選択(6.3.2)。フェーズ1は他派閥と競合しないため全隅可。
        return [SetupChooseKeep(player=dec.actor, corner=c.value) for c in Corner
                if state.map.corner_clearing(c) is not None]

    if isinstance(dec, AmbushDefenderDecision):
        # 奇襲する/しない(4.3.1)
        opts = [AmbushChoice(player=dec.actor, card_id=None)]
        card = _matching_ambush(state, dec.actor, dec.ctx.clearing)
        if card is not None:
            opts.append(AmbushChoice(player=dec.actor, card_id=card))
        return opts

    if isinstance(dec, AmbushAttackerDecision):
        # 奇襲の妨害(4.3.1.I)
        opts = [AmbushChoice(player=dec.actor, card_id=None)]
        card = _matching_ambush(state, dec.actor, dec.ctx.clearing)
        if card is not None:
            opts.append(AmbushChoice(player=dec.actor, card_id=card))
        return opts

    if isinstance(dec, AllocateHitsDecision):
        # ヒット割り振り(4.3.4)
        return allocate_options(state, dec)

    if isinstance(dec, EyrieSetupCornerDecision):
        # 開始時広場の隅(7.3.2)
        from .factions import eyrie
        return eyrie.corner_options(state)

    if isinstance(dec, EyrieLeaderDecision):
        # 君主選択(7.3.3 / 7.7.3)
        from .factions import eyrie
        return eyrie.leader_options(state)

    if isinstance(dec, EyrieDecreeDecision):
        # 勅令追加(7.4.2)
        from .factions import eyrie
        return eyrie.decree_add_options(state, dec)

    if isinstance(dec, EyrieRoostDecision):
        # 止まり木確保(7.4.3)
        from .factions import eyrie
        return eyrie.roost_options(state)

    if isinstance(dec, OutrageDecision):
        # 蜂起の支払い(8.2.6)
        from .factions import alliance
        return alliance.outrage_options(state, dec)

    if isinstance(dec, SupportersLimitDecision):
        # 全拠点喪失時の支援者5枚調整(8.2.4)
        from .factions import alliance
        return alliance.supporters_limit_options(state, dec)

    if isinstance(dec, DiscardDecision):
        # 手札を5枚へ(6.6)
        hand = state.fs(dec.actor).hand
        seen = set()
        out: List[Action] = []
        for cid in hand:
            base = state.cards.base_id(cid)
            if base in seen:
                continue
            seen.add(base)
            out.append(DiscardCard(player=dec.actor, card_id=cid))
        return out

    raise NotImplementedError("unknown decision %r" % (dec,))
