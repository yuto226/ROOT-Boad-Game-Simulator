"""クラフト共通処理(4.1)。

フェーズ1では item 効果のみ実装(3.7)。immediate/persistent は
ホワイトリスト方式で、未実装効果のカードは合法手に含めない。
"""
from __future__ import annotations

import dataclasses
from typing import List, Optional, Tuple

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

    猫野侯国=工房(6.2.1)、鷲巣王朝=止まり木(7.2.1)。他はフェーズ2以降。
    """
    from .types import B_WORKSHOP
    if faction == FactionId.MARQUISE:
        suits = []
        for cs in state.clearings:
            for p in cs.buildings:
                if p.faction == FactionId.MARQUISE and p.kind == B_WORKSHOP:
                    suits.append(state.map.clearing(cs.cid).suit.value)
        return suits
    if faction == FactionId.EYRIE:
        return [suit for _, suit in eyrie_available_tools(state)]
    return []


def eyrie_available_tools(state: GameState) -> List[Tuple[int, str]]:
    """未起動の止まり木タイル(広場ID, 動物種)の一覧(7.2.1)。

    各止まり木は1ターン中1回しか起動できない(4.1.1)。起動済みは
    EyrieState.used_roost_clearings(広場ID単位)で追跡する。
    """
    from .types import B_ROOST
    es = state.eyrie()
    out: List[Tuple[int, str]] = []
    for cs in state.clearings:
        if cs.cid in es.used_roost_clearings:
            continue
        if any(p.faction == FactionId.EYRIE and p.kind == B_ROOST
               for p in cs.buildings):
            out.append((cs.cid, state.map.clearing(cs.cid).suit.value))
    return out


def eyrie_payment(state: GameState, cost) -> Optional[List[int]]:
    """コスト(4.1.1)を未起動の止まり木で支払う割当(広場IDの列)。

    支払えなければ None。具体的な動物種を先に、ワイルド("any"/"?")を
    後に割り当てる決定的アルゴリズム(legal と apply で同一の結果)。
    """
    tools = eyrie_available_tools(state)
    used: List[int] = []
    specific = [sym for sym in cost if sym not in ("any", "?")]
    wilds = len(cost) - len(specific)
    for sym in specific:
        found = None
        for i, (cid, suit) in enumerate(tools):
            if suit == sym:
                found = i
                break
        if found is None:
            return None  # 鳥コスト等、一致ツールなし(広場に鳥はない, 2.2.2)
        used.append(tools.pop(found)[0])
    for _ in range(wilds):
        if not tools:
            return None
        used.append(tools.pop(0)[0])
    return used


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
        if faction == FactionId.EYRIE:
            # 鷲巣: 止まり木ごとに1ターン1回の厳密な割当(7.2.1, 4.1.1)
            if eyrie_payment(state, cdef.cost) is None:
                continue
        elif not _can_pay(cdef.cost, suits):
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
    cdef = state.cards.get(action.card_id)
    item = ItemKind(cdef.effect["item"])
    vp = int(cdef.effect.get("vp", 0))
    if faction == FactionId.EYRIE:
        # ツール起動の記録(止まり木の広場ID単位で1ターン1回, 4.1.1)
        pay = eyrie_payment(state, cdef.cost)
        assert pay is not None, "eyrie craft without payable roosts"
        es = state.eyrie()
        state = state.with_faction_state(dataclasses.replace(
            es, used_roost_clearings=es.used_roost_clearings + tuple(pay)))
        # 商業軽視(7.2.3): itemクラフトのVPは常に1。君主が建設者なら
        # 無効=カード記載値(7.8.1)
        if state.eyrie().leader != "builder":
            vp = 1
    state = state.take_item(item)
    fs = state.fs(faction)
    new_fs = dataclasses.replace(fs, items=fs.items + (item,), vp=fs.vp + vp)
    state = state.with_faction_state(new_fs)
    if faction == FactionId.MARQUISE:
        ms = state.marquise()
        state = state.with_faction_state(dataclasses.replace(ms, workshop_used=True))
    state = discard_card(state, faction, action.card_id)
    return state
