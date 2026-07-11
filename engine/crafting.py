"""クラフト共通処理(4.1)。

item 効果に加え、immediate/persistent はホワイトリスト方式(3.7/18.2)で
実装対象13種のみ合法手に含める。未実装効果(Codebreakers 等)は除外する。
"""
from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional, Tuple

from .actions import (
    Action,
    CobblerMoveDecision,
    CommandWarrenDecision,
    CraftCard,
    DeclareBattle,
    MarquiseMarch,
    UseCraftedEffect,
    VagabondMove,
)
from .state import GameState
from .types import FactionId, ItemKind, Phase, Suit

#: immediate/persistent 効果のホワイトリスト(3.7 拡張, 18.2)。base_id で判定する。
#: favor 三種のみ immediate、残り10種は persistent。Codebreakers は対象外
#: (完全情報エンジンでは情報価値ゼロ=クラフトが厳密劣位になるだけ, 18章冒頭)。
_EFFECT_WHITELIST = frozenset({
    "armorers", "sappers", "brutal-tactics", "scouting-party",
    "royal-claim", "better-burrow-bank", "cobbler", "command-warren",
    "stand-and-deliver", "tax-collector",
    "favor-of-the-mice", "favor-of-the-foxes", "favor-of-the-rabbits",
})


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

    猫野侯国=工房(6.2.1)、鷲巣王朝=止まり木(7.2.1)、
    森林連合=支持トークン(8.2.1)、放浪部族=H(9.2.1)。
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
    if faction == FactionId.ALLIANCE:
        return [suit for _, suit in alliance_available_tools(state)]
    if faction == FactionId.VAGABOND:
        # 全Hの動物種=放浪者コマの現在広場(9.2.1)。樹林ではクラフト不可
        # (広場の動物種がないため, DESIGN.md 8.3)。使用可能な H は
        # 未使用(表向き)・非損傷のもの(exhaust が 1ターン1回制限 4.1.1 を兼ねる)。
        from .factions.vagabond import HAMMER, _count_payable
        vs = state.vagabond()
        if vs.pawn_clearing is None:
            return []
        n = _count_payable(vs.items, HAMMER)
        return [state.map.clearing(vs.pawn_clearing).suit.value] * n
    return []


def assign_tools(tools: List[Tuple[int, str]], cost) -> Optional[List[int]]:
    """クラフトツール(広場ID, 動物種)の一覧でコスト(4.1.1)を支払う割当。

    支払えなければ None。具体的な動物種を先に、ワイルド("any"/"?")を
    後に割り当てる決定的アルゴリズム(legal と apply で同一の結果)。
    鷲巣の止まり木・森林連合の支持トークン双方から共用する。
    """
    tools = list(tools)
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
    """コスト(4.1.1)を未起動の止まり木で支払う割当(広場IDの列)。"""
    return assign_tools(eyrie_available_tools(state), cost)


def alliance_available_tools(state: GameState) -> List[Tuple[int, str]]:
    """未起動の支持トークン(広場ID, 動物種)の一覧(8.2.1)。

    森林連合のクラフトツールはマップ上の支持トークンで、動物種はその
    広場のもの。各トークンは1ターン中1回しか起動できない(4.1.1)。
    起動済みは AllianceState.used_sympathy_clearings(広場ID単位)で追跡。
    """
    from .types import T_SYMPATHY
    als = state.alliance()
    out: List[Tuple[int, str]] = []
    for cs in state.clearings:
        if cs.cid in als.used_sympathy_clearings:
            continue
        if cs.has_token(FactionId.ALLIANCE, T_SYMPATHY):
            out.append((cs.cid, state.map.clearing(cs.cid).suit.value))
    return out


def alliance_payment(state: GameState, cost) -> Optional[List[int]]:
    """コスト(4.1.1)を未起動の支持トークンで支払う割当(広場IDの列)。"""
    return assign_tools(alliance_available_tools(state), cost)


def legal_crafts(state: GameState, faction: FactionId) -> List[CraftCard]:
    """クラフト可能なカード(item + ホワイトリストの immediate/persistent, 18.2)。"""
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
        etype = cdef.effect.get("type")
        key = state.cards.base_id(cid)
        if etype == "item":
            pass
        elif etype in ("immediate", "persistent"):
            if key not in _EFFECT_WHITELIST:
                continue  # 未実装効果(3.7)。Codebreakers 等はここで除外される
            if etype == "persistent" and key in fs.crafted_effects:
                continue  # 重複禁止(4.1.4)
        else:
            continue
        if faction == FactionId.EYRIE:
            # 鷲巣: 止まり木ごとに1ターン1回の厳密な割当(7.2.1, 4.1.1)
            if eyrie_payment(state, cdef.cost) is None:
                continue
        elif faction == FactionId.ALLIANCE:
            # 連合: 支持トークンごとに1ターン1回の厳密な割当(8.2.1, 4.1.1)
            if alliance_payment(state, cdef.cost) is None:
                continue
        elif not _can_pay(cdef.cost, suits):
            continue
        if etype == "item":
            try:
                item = ItemKind(cdef.effect["item"])
            except (KeyError, ValueError):
                continue
            if not state.item_available(item):
                continue  # サプライにアイテムなし(4.1.2)
        if key in seen:
            continue
        seen.add(key)
        out.append(CraftCard(player=faction, card_id=cid))
    return out


def apply_craft(state: GameState, action: CraftCard, rng) -> GameState:
    """クラフトアクションの適用(4.1)。type ごとに分岐(18.2)。"""
    from .mechanics import award_vp, discard_card
    faction = action.player
    cdef = state.cards.get(action.card_id)
    etype = cdef.effect.get("type")

    # --- クラフトツール起動の記録(4.1.1、type 共通) ---
    if faction == FactionId.EYRIE:
        # ツール起動の記録(止まり木の広場ID単位で1ターン1回, 4.1.1)
        pay = eyrie_payment(state, cdef.cost)
        assert pay is not None, "eyrie craft without payable roosts"
        es = state.eyrie()
        state = state.with_faction_state(dataclasses.replace(
            es, used_roost_clearings=es.used_roost_clearings + tuple(pay)))
    elif faction == FactionId.ALLIANCE:
        # ツール起動の記録(支持トークンの広場ID単位で1ターン1回, 8.2.1)
        pay = alliance_payment(state, cdef.cost)
        assert pay is not None, "alliance craft without payable sympathy tokens"
        als = state.alliance()
        state = state.with_faction_state(dataclasses.replace(
            als, used_sympathy_clearings=als.used_sympathy_clearings + tuple(pay)))
    if faction == FactionId.MARQUISE:
        state = state.with_faction_state(dataclasses.replace(
            state.marquise(), workshop_used=True))

    if etype == "item":
        item = ItemKind(cdef.effect["item"])
        vp = int(cdef.effect.get("vp", 0))
        # 商業軽視(7.2.3): itemクラフトのVPは常に1。君主が建設者なら
        # 無効=カード記載値(7.8.1)
        if faction == FactionId.EYRIE and state.eyrie().leader != "builder":
            vp = 1
        state = state.take_item(item)
        fs = state.fs(faction)
        state = state.with_faction_state(dataclasses.replace(fs, items=fs.items + (item,)))
        # クラフトVP(3.2.2)は中央ヘルパ経由(VP凍結・非負クランプ, 14.2)
        state = award_vp(state, faction, vp)
        return discard_card(state, faction, action.card_id)

    if etype == "persistent":
        # 継続効果: 手札から手元へ(捨て山に行かない, 4.1.3)。VPなし(18.2)。
        fs = state.fs(faction)
        hand = list(fs.hand)
        hand.remove(action.card_id)
        base = state.cards.base_id(action.card_id)
        return state.with_faction_state(dataclasses.replace(
            fs, hand=tuple(hand), crafted_effects=fs.crafted_effects + (base,)))

    if etype == "immediate":
        # Favor 三種(18.2): 動物種一致の全広場から敵の全コマを除去→捨て札
        state = apply_favor_effect(state, faction, cdef, rng)
        return discard_card(state, faction, action.card_id)

    raise NotImplementedError("unknown craft effect type %r" % (etype,))


def apply_favor_effect(state: GameState, faction: FactionId, cdef, rng) -> GameState:
    """Favor 三種の即時効果(4.1.2, 18.2): 動物種一致の全広場から敵の全コマを除去。

    除去は既存 battle.remove_piece(source=クラフター)を1個ずつ呼び、建物/
    トークンのVP・専制者VP・放浪部族の関係悪化・城砦返却等のフックを共通経路
    で通す(敵=クラフター以外の全派閥、ダミー含む)。猫兵士の除去は広場ごとに
    1イベントとして集計し、野戦病院(6.2.3)を発火させる(複数広場なら複数回、
    15.3 と同じ仕組み)。
    """
    from . import battle as battle_mod
    from .factions import marquise as marquise_mod
    suit = cdef.suit
    for cs in state.clearings:
        if state.map.clearing(cs.cid).suit != suit:
            continue
        cur = state.clearing(cs.cid)
        victims = sorted(
            {f for f, n in cur.soldiers if f != faction and n > 0}
            | {p.faction for p in cur.buildings if p.faction != faction}
            | {p.faction for p in cur.tokens if p.faction != faction},
            key=lambda f: f.value)
        removed_soldiers = 0
        for victim in victims:
            # battle=False: クラフト効果による除去は戦闘除去ではない
            # (悪名 9.2.9.III.a は戦闘除去のみが対象。敵対化・除去VPは共通に発火)
            n = state.clearing(cs.cid).soldier_count(victim)
            for _ in range(n):
                state = battle_mod.remove_piece(
                    state, cs.cid, victim, ("soldier",), source=faction, battle=False)
                if victim == FactionId.MARQUISE:
                    removed_soldiers += 1
            for p in list(state.clearing(cs.cid).buildings_of(victim)):
                state = battle_mod.remove_piece(
                    state, cs.cid, victim, ("building", p.kind), source=faction,
                    battle=False)
            for p in list(state.clearing(cs.cid).tokens_of(victim)):
                state = battle_mod.remove_piece(
                    state, cs.cid, victim, ("token", p.kind), source=faction,
                    battle=False)
        if removed_soldiers > 0:
            pushed = marquise_mod.maybe_field_hospital(state, cs.cid, removed_soldiers)
            if pushed is not None:
                state = pushed
    return state


# ================================================================
#  フェイズ効果(18.3): 鳥歌/昼光/夕闇の継続効果カード
#  戦闘効果(armorers/sappers/brutal-tactics)は battle.py 側(18.4)。
# ================================================================
#: フェイズごとの対象効果(base_id)。タイミングの簡略化(18.3明記): カード文言の
#: 「フェイズ開始時」(Better Burrow Bank/Command Warren/Cobbler)は
#: 「そのフェイズ中いつでも・1ターン1回」に緩和する。
_PHASE_EFFECTS: Dict[Phase, Tuple[str, ...]] = {
    Phase.BIRDSONG: ("royal-claim", "stand-and-deliver", "better-burrow-bank"),
    Phase.DAYLIGHT: ("tax-collector", "command-warren"),
    Phase.EVENING: ("cobbler",),
}


def _command_warren_candidates(state: GameState, faction: FactionId) -> List[DeclareBattle]:
    """command-warren(18.3)の戦闘候補。カード動物種・アイテムコスト等の制約は
    課さない素の宣言条件(4.3)のみ: 自分の配置物(放浪部族は放浪者コマ)がある
    広場から、そこに配置物を持つ他派閥を防御側として宣言できる。
    """
    from .factions.vagabond import vagabond_in_clearing
    out: List[DeclareBattle] = []
    for cs in state.clearings:
        if faction == FactionId.VAGABOND:
            if state.vagabond().pawn_clearing != cs.cid:
                continue
        elif cs.soldier_count(faction) <= 0:
            continue
        defenders = set()
        for f, n in cs.soldiers:
            if f != faction and n > 0:
                defenders.add(f)
        for p in cs.buildings + cs.tokens:
            if p.faction != faction:
                defenders.add(p.faction)
        if faction != FactionId.VAGABOND and vagabond_in_clearing(state, cs.cid):
            defenders.add(FactionId.VAGABOND)
        for d in sorted(defenders, key=lambda f: f.value):
            out.append(DeclareBattle(player=faction, clearing=cs.cid, defender=d))
    return out


def command_warren_options(state: GameState, dec: CommandWarrenDecision) -> List[Action]:
    """CommandWarrenDecision の選択肢(候補は必ず1つ以上ある前提, キャンセル肢なし)。"""
    return _command_warren_candidates(state, dec.actor)


def cobbler_move_options(state: GameState, faction: FactionId) -> List[Action]:
    """cobbler(18.3)の移動候補。4.2 の素の移動条件のみ(コスト制約なし)。

    放浪部族は放浪者コマの移動(VagabondMove、9.2.2)。他派閥は兵士移動を
    MarquiseMarch で表す(全派閥で共用する汎用の「1回移動」。action_key は
    player を見ないため rl/catalog.py の変更は不要)。
    """
    if faction == FactionId.VAGABOND:
        vs = state.vagabond()
        out: List[Action] = []
        if vs.pawn_clearing is not None:
            neighbors = state.map.clearing(vs.pawn_clearing).adjacent
        elif vs.pawn_forest is not None:
            neighbors = state.map.forest(vs.pawn_forest).adjacent_clearings
        else:
            return out
        for dst in neighbors:
            out.append(VagabondMove(player=faction, dst=dst))
        return out
    out = []
    for cs in state.clearings:
        n = cs.soldier_count(faction)
        if n <= 0:
            continue
        for dst in state.map.clearing(cs.cid).adjacent:
            if not (state.controls(faction, cs.cid) or state.controls(faction, dst)):
                continue
            for count in range(1, n + 1):
                out.append(MarquiseMarch(player=faction, src=cs.cid, dst=dst, count=count))
    return out


def phase_effect_actions(state: GameState, faction: FactionId, phase: Phase) -> List[Action]:
    """所有+未使用+フェイズ一致の継続効果カードの合法手(18.3)。

    通常の合法手に追加する共通フック(legal.py から全フェイズで呼ばれる)。
    """
    fs = state.fs(faction)
    out: List[Action] = []
    for key in _PHASE_EFFECTS.get(phase, ()):
        if key not in fs.crafted_effects:
            continue
        if key != "royal-claim" and key in fs.effects_used:
            continue
        if key == "royal-claim":
            out.append(UseCraftedEffect(player=faction, card_key=key))
        elif key == "stand-and-deliver":
            for target in state.factions:
                if target == faction:
                    continue
                if state.fs(target).hand:
                    out.append(UseCraftedEffect(
                        player=faction, card_key=key, target_faction=target))
        elif key == "better-burrow-bank":
            for target in state.factions:
                if target == faction:
                    continue
                out.append(UseCraftedEffect(
                    player=faction, card_key=key, target_faction=target))
        elif key == "tax-collector":
            for cs in state.clearings:
                if cs.soldier_count(faction) > 0:
                    out.append(UseCraftedEffect(
                        player=faction, card_key=key, target_clearing=cs.cid))
        elif key == "command-warren":
            if _command_warren_candidates(state, faction):
                out.append(UseCraftedEffect(player=faction, card_key=key))
        elif key == "cobbler":
            if cobbler_move_options(state, faction):
                out.append(UseCraftedEffect(player=faction, card_key=key))
    return out


def _mark_used(state: GameState, faction: FactionId, key: str) -> GameState:
    """1ターン1回系の使用済み記録(18.1/18.3)。"""
    fs = state.fs(faction)
    return state.with_faction_state(dataclasses.replace(
        fs, effects_used=fs.effects_used + (key,)))


def apply_phase_effect(state: GameState, action: UseCraftedEffect, rng) -> GameState:
    """フェイズ効果(鳥歌/昼光/夕闇)の適用(18.3)。戦闘効果は battle.py 側(18.4)。"""
    from .mechanics import award_vp, discard_crafted_effect, draw_cards
    faction = action.player
    key = action.card_key

    if key == "royal-claim":
        ruled = sum(1 for cs in state.clearings if state.controls(faction, cs.cid))
        state = award_vp(state, faction, ruled)
        return discard_crafted_effect(state, faction, key)

    if key == "stand-and-deliver":
        target = action.target_faction
        tfs = state.fs(target)
        hand = list(tfs.hand)
        card = hand.pop(rng.randrange(len(hand)))
        state = state.with_faction_state(dataclasses.replace(tfs, hand=tuple(hand)))
        fs = state.fs(faction)
        state = state.with_faction_state(dataclasses.replace(fs, hand=fs.hand + (card,)))
        state = award_vp(state, target, 1)
        return _mark_used(state, faction, key)

    if key == "better-burrow-bank":
        state = draw_cards(state, faction, 1, rng)
        state = draw_cards(state, action.target_faction, 1, rng)
        return _mark_used(state, faction, key)

    if key == "tax-collector":
        from . import battle as battle_mod
        from .factions import marquise as marquise_mod
        clearing = action.target_clearing
        state = battle_mod.remove_piece(
            state, clearing, faction, ("soldier",), source=None, battle=False)
        # 猫自身の兵士除去イベント → 野戦病院(6.2.3)。除去イベント時点で判定
        # (18.3 の順: 除去→ドロー。選択肢の生成はデシジョン解決時=ドロー後)
        if faction == FactionId.MARQUISE:
            pushed = marquise_mod.maybe_field_hospital(state, clearing, 1)
            if pushed is not None:
                state = pushed
        state = draw_cards(state, faction, 1, rng)
        return _mark_used(state, faction, key)

    if key == "command-warren":
        state = _mark_used(state, faction, key)
        return state.push_pending(CommandWarrenDecision(actor=faction))

    if key == "cobbler":
        state = _mark_used(state, faction, key)
        return state.push_pending(CobblerMoveDecision(actor=faction))

    raise NotImplementedError("unknown phase effect %r" % (key,))
