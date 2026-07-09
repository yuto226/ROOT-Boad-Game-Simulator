"""クラフト共通処理(4.1)。

フェーズ1では item 効果のみ実装(3.7)。immediate/persistent は
ホワイトリスト方式で、未実装効果のカードは合法手に含めない。
"""
from __future__ import annotations

import dataclasses
from typing import List

from .actions import CraftCard
from .state import GameState
from .types import FactionId, ItemKind, Suit


def _can_pay(cost, available_suits: List[str]) -> bool:
    """コスト(4.1.1)を利用可能なクラフトツールの動物種で支払えるか。"""
    pool = list(available_suits)
    for sym in cost:
        if sym in ("any", "?"):
            if not pool:
                return False
            pool.pop()
            continue
        if sym in pool:
            pool.remove(sym)
        elif "bird" in pool:  # 到達しない想定: 広場に鳥の動物種は存在しない(2.2.2)。
            # 注意: 2.1.1のワイルドは鳥「カード」の規定でありツールには適用されない。
            pool.remove("bird")
        else:
            return False
    return True


def craft_tool_suits(state: GameState, faction: FactionId) -> List[str]:
    """派閥のクラフトツールが提供する動物種の一覧。

    猫野侯国=工房(6.2.1)。他派閥はフェーズ2で拡張。
    """
    from .types import B_WORKSHOP
    if faction != FactionId.MARQUISE:
        return []
    suits = []
    for cs in state.clearings:
        for p in cs.buildings:
            if p.faction == FactionId.MARQUISE and p.kind == B_WORKSHOP:
                suits.append(state.map.clearing(cs.cid).suit.value)
    return suits


def legal_crafts(state: GameState, faction: FactionId) -> List[CraftCard]:
    """クラフト可能なカード(item 効果のみ)。"""
    fs = state.fs(faction)
    # 猫: 工房は1ターン1回起動の簡略化(全工房を1プール, 1クラフト/ターン)
    ms = state.marquise() if faction == FactionId.MARQUISE else None
    if ms is not None and ms.workshop_used:
        return []
    suits = craft_tool_suits(state, faction)
    if not suits:
        return []
    out: List[CraftCard] = []
    seen = set()
    for cid in fs.hand:
        cdef = state.cards.get(cid)
        if not cdef.is_craftable or cdef.effect is None:
            continue
        if cdef.effect.get("type") != "item":
            continue  # immediate/persistent は未実装(3.7)
        if not _can_pay(cdef.cost, suits):
            continue
        try:
            item = ItemKind(cdef.effect["item"])
        except (KeyError, ValueError):
            continue
        if not state.item_available(item):
            continue  # サプライにアイテムなし(4.1.2)
        key = state.cards.base_id(cid)
        if key in seen:
            continue
        seen.add(key)
        out.append(CraftCard(player=faction, card_id=cid))
    return out


def apply_craft(state: GameState, action: CraftCard, rng) -> GameState:
    """クラフトアクションの適用(4.1.2 item 効果)。"""
    from .mechanics import discard_card
    faction = action.player
    fs = state.fs(faction)
    cdef = state.cards.get(action.card_id)
    item = ItemKind(cdef.effect["item"])
    vp = int(cdef.effect.get("vp", 0))
    state = state.take_item(item)
    new_fs = dataclasses.replace(fs, items=fs.items + (item,), vp=fs.vp + vp)
    state = state.with_faction_state(new_fs)
    if faction == FactionId.MARQUISE:
        ms = state.marquise()
        state = state.with_faction_state(dataclasses.replace(ms, workshop_used=True))
    state = discard_card(state, faction, action.card_id)
    return state
