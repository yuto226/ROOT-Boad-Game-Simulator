"""アクション適用 apply(state, action, rng) -> GameState(3.1 / 3.3)。

入力 state は変更しない。適用前の合法性再検証は行わない(assert に
よる安価な防御のみ, DESIGN.md 3.3)。
"""
from __future__ import annotations

import dataclasses
from typing import Optional, Set

from . import battle as battle_mod
from .actions import (
    Action,
    ActivateDominance,
    AllianceDiscardSupporter,
    AllianceEndOps,
    AllianceMobilize,
    AllianceOpBattle,
    AllianceOpMove,
    AllianceOpOrganize,
    AllianceOpRecruit,
    AllianceRevolt,
    AllianceSpreadSympathy,
    AllianceTrain,
    AllocateHit,
    AmbushAttackerDecision,
    AmbushChoice,
    AmbushDefenderDecision,
    BattleEffectsDecision,
    CobblerMoveDecision,
    CommandWarrenDecision,
    CraftCard,
    DeclareBattle,
    DiscardCard,
    DiscardDecision,
    EndPhase,
    FieldHospitalDecision,
    EyrieAddToDecree,
    EyrieChooseCorner,
    EyrieChooseLeader,
    EyrieDecreeBattle,
    EyrieDecreeBuild,
    EyrieDecreeMove,
    EyriePlaceRoost,
    EyrieRecruit,
    EyrieSkipDecree,
    EyrieTurmoil,
    MarquiseBuild,
    MarquiseFieldHospital,
    MarquiseLabor,
    MarquiseMarch,
    MarquiseMarchDecision,
    MarquisePlayBirdCard,
    MarquiseRecruit,
    MarquiseSkipMove,
    ItemDamageDecision,
    ItemLimitDecision,
    OutragePay,
    RefreshDecision,
    SetupChooseKeep,
    SkipBattleEffects,
    TakeDominance,
    UseCraftedEffect,
    VagabondAid,
    VagabondBattle,
    VagabondCoalition,
    VagabondChooseCharacter,
    VagabondChooseForest,
    VagabondExplore,
    VagabondItemChoice,
    VagabondMove,
    VagabondQuest,
    VagabondRepair,
    VagabondSlip,
    VagabondSpecial,
    VagabondStrike,
)
from .crafting import apply_craft
from .factions import alliance as alliance_mod
from .factions import eyrie as eyrie_mod
from .factions import vagabond as vagabond_mod
from .mechanics import discard_card
from .state import GameState, MarquiseState
from .types import (
    B_RECRUITER,
    Corner,
    FactionId,
    OPPOSITE_CORNER,
    Phase,
    Piece,
    T_KEEP,
    T_WOOD,
)


def apply(state: GameState, action: Action, rng) -> GameState:
    """アクションを適用し新しい状態を返す。"""
    handler = _HANDLERS.get(type(action))
    if handler is None:
        raise NotImplementedError("no handler for %r" % (action,))
    state = handler(state, action, rng)
    return _check_victory(state)


# ---------------- 勝利判定(3.1) ----------------
def _check_victory(state: GameState) -> GameState:
    if state.finished:
        return state
    # 同時到達はターンプレイヤー優先(3.1)
    order = [state.current_faction()] + [
        f for f in state.factions if f != state.current_faction()]
    for f in order:
        # 圧倒カード発動済み派閥はVP凍結(3.3.1)。30VP勝利の対象外(14.5)。
        if state.fs(f).dominance_card is not None:
            continue
        if state.fs(f).vp >= 30:
            return state.replace(winner=f, finished=True)
    return state


# ---------------- フェイズ遷移(1.4.1 / 3.8) ----------------
def _apply_end_phase(state: GameState, action: EndPhase, rng) -> GameState:
    from .factions import get_logic
    assert not state.pending, "cannot end phase with pending decisions"
    if state.phase == Phase.BIRDSONG:
        state = state.replace(phase=Phase.DAYLIGHT)
    elif state.phase == Phase.DAYLIGHT:
        state = state.replace(phase=Phase.EVENING)
    else:  # 夕闇終了 → 次プレイヤーへ(1.4.1)
        nxt = (state.turn_index + 1) % len(state.factions)
        state = state.replace(phase=Phase.BIRDSONG, turn_index=nxt,
                              turn_count=state.turn_count + 1)
        # 3.3.1: 新手番の鳥歌開始時に圧倒勝利判定(begin_phase の前, 14.5)
        from .game import check_dominance_victory
        state = check_dominance_victory(state)
        if state.finished:
            return state
    return get_logic(state.current_faction()).begin_phase(state, rng)


# ---------------- セットアップ(6.3) ----------------
def _apply_choose_keep(state: GameState, action: SetupChooseKeep, rng) -> GameState:
    """城砦配置(6.3.2)+駐留部隊(6.3.3)+開始時建物(6.3.4)。"""
    state = state.pop_pending()
    corner = Corner(action.corner)
    keep_cid = state.map.corner_clearing(corner)
    assert keep_cid is not None
    opposite = state.map.corner_clearing(OPPOSITE_CORNER[corner])

    # 6.3.2 城砦トークン
    cs = state.clearing(keep_cid).add_token(Piece(FactionId.MARQUISE, T_KEEP))
    state = state.with_clearing(cs)

    # 6.3.3 対角の隅以外の全広場に兵士1(サプライから)
    ms = state.marquise()
    placed = 0
    for c in state.clearings:
        if c.cid == opposite:
            continue
        if placed >= ms.soldiers_supply:
            break  # 1.5.4: 可能な限り
        state = state.with_clearing(state.clearing(c.cid).add_soldiers(FactionId.MARQUISE, 1))
        placed += 1
    ms = state.marquise()
    state = state.with_faction_state(dataclasses.replace(
        ms, soldiers_supply=ms.soldiers_supply - placed, keep_corner=corner.value))

    # 6.3.4 開始時建物: 城砦広場+隣接広場の空き枠に製材所/工房/募兵所を各1
    kinds = ["sawmill", "workshop", "recruiter"]
    candidates = [keep_cid] + list(state.map.clearing(keep_cid).adjacent)
    for cid in candidates:
        if not kinds:
            break
        cs = state.clearing(cid)
        cl = state.map.clearing(cid)
        while kinds and cs.occupied_slots() < cl.slots:
            kind = kinds.pop(0)
            cs = cs.add_building(Piece(FactionId.MARQUISE, kind))
        state = state.with_clearing(cs)
    assert not kinds, "could not place all starting buildings"
    ms = state.marquise()
    state = state.with_faction_state(dataclasses.replace(
        ms, built_sawmill=1, built_workshop=1, built_recruiter=1))
    return state


# ---------------- 猫野侯国(第6章) ----------------
def _spend_action(state: GameState) -> GameState:
    ms = state.marquise()
    return state.with_faction_state(dataclasses.replace(ms, actions_left=ms.actions_left - 1))


def _apply_build(state: GameState, action: MarquiseBuild, rng) -> GameState:
    """建設(6.5.4)。木材は連結支配広場から自動選択で支払う(簡略化)。"""
    ms = state.marquise()
    n = ms.built_count(action.kind)
    cost = state.board_defs["marquise"]["building_costs"][n]
    vp = state.board_defs["marquise"]["building_vp"][action.kind][n]

    # 6.5.4.II 木材の支払い: 建設広場から連結の支配下広場を BFS で回収
    remaining = cost
    visited: Set[int] = {action.clearing}
    queue = [action.clearing]
    order = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nb in state.map.clearing(cur).adjacent:
            if nb not in visited and state.controls(FactionId.MARQUISE, nb):
                visited.add(nb)
                queue.append(nb)
    for cid in order:
        while remaining > 0 and state.clearing(cid).wood_count(FactionId.MARQUISE) > 0:
            state = state.with_clearing(
                state.clearing(cid).remove_one_token(FactionId.MARQUISE, T_WOOD))
            remaining -= 1
    assert remaining == 0, "insufficient wood for build"
    # 除去した木材はサプライへ(3.5)
    ms = state.marquise()
    ms = dataclasses.replace(ms, wood_supply=ms.wood_supply + cost)

    # 6.5.4.III タイル配置と得点
    state = state.with_faction_state(ms)
    cs = state.clearing(action.clearing).add_building(Piece(FactionId.MARQUISE, action.kind))
    state = state.with_clearing(cs)
    ms = state.marquise()
    field = {"sawmill": "built_sawmill", "workshop": "built_workshop",
             "recruiter": "built_recruiter"}[action.kind]
    ms = dataclasses.replace(ms, **{field: getattr(ms, field) + 1})
    state = state.with_faction_state(ms)
    # 建設VP(6.5.4.III)は中央ヘルパ経由(VP凍結・非負クランプ, 14.2)
    from .mechanics import award_vp
    state = award_vp(state, FactionId.MARQUISE, vp)
    return _spend_action(state)


def _apply_recruit(state: GameState, action: MarquiseRecruit, rng) -> GameState:
    """募兵(6.5.3)。募兵所タイル1枚ごとに兵士1。サプライ不足は可能な限り(1.5.4)。"""
    ms = state.marquise()
    supply = ms.soldiers_supply
    for cs in state.clearings:
        for p in cs.buildings:
            if p.faction == FactionId.MARQUISE and p.kind == B_RECRUITER:
                if supply <= 0:
                    break
                state = state.with_clearing(
                    state.clearing(cs.cid).add_soldiers(FactionId.MARQUISE, 1))
                supply -= 1
    ms = state.marquise()
    state = state.with_faction_state(dataclasses.replace(
        ms, soldiers_supply=supply, recruited_this_turn=True))
    return _spend_action(state)


def _apply_march(state: GameState, action: MarquiseMarch, rng) -> GameState:
    """行軍の1移動(6.5.2, 4.2)。1行軍アクションで最大2移動。

    pending 先頭が ``MarquiseMarchDecision`` なら2移動目(応答)としてアクションを
    消費せず pop する。そうでなければ1移動目としてアクション1を消費し、先に
    ``MarquiseMarchDecision`` を積んでから移動を実行する(移動が蜂起 8.2.6 の
    ``OutrageDecision`` を積む場合、それがスタック上に載り先に解決される。push順が
    重要, 15.2)。

    pending 先頭が ``CobblerMoveDecision`` なら cobbler(18.3)の無消費の1回移動
    として応答する。MarquiseMarch を全派閥共通の「1回移動」アクションとして
    流用する(action_key は player を見ないため rl/catalog.py の変更は不要)。
    """
    if state.pending and isinstance(state.pending[-1], CobblerMoveDecision):
        state = state.pop_pending()
        return _execute_soldier_move(
            state, action.player, action.src, action.dst, action.count, rng)
    if state.pending and isinstance(state.pending[-1], MarquiseMarchDecision):
        state = state.pop_pending()  # 2移動目: アクション消費なし
    else:
        state = _spend_action(state)  # 1移動目: アクション1消費
        state = state.push_pending(MarquiseMarchDecision(actor=FactionId.MARQUISE))
    return _execute_soldier_move(
        state, FactionId.MARQUISE, action.src, action.dst, action.count, rng)


def _execute_soldier_move(state: GameState, faction: FactionId, src_cid: int,
                          dst_cid: int, count: int, rng) -> GameState:
    """兵士移動の実行(4.2)+支持広場移動での蜂起判定(8.2.6)。

    猫の行軍・cobbler(18.3)の無消費移動から呼ばれる汎用ヘルパ。
    """
    src = state.clearing(src_cid)
    assert src.soldier_count(faction) >= count
    state = state.with_clearing(src.add_soldiers(faction, -count))
    dst = state.clearing(dst_cid).add_soldiers(faction, count)
    state = state.with_clearing(dst)
    # 支持広場への兵士移動 → 蜂起(8.2.6)。連合不参加/非支持広場/移動元が連合
    # 自身なら outrage_on_move 内部で no-op(alliance.outrage_on_move の実装参照)。
    return alliance_mod.outrage_on_move(state, faction, dst_cid, rng)


def _apply_skip_move(state: GameState, action: MarquiseSkipMove, rng) -> GameState:
    """行軍の2移動目を行わない(6.5.2)。MarquiseMarchDecision を pop するのみ。"""
    assert state.pending and isinstance(state.pending[-1], MarquiseMarchDecision)
    return state.pop_pending()


def _apply_field_hospital(state: GameState, action: MarquiseFieldHospital,
                          rng) -> GameState:
    """野戦病院(6.2.3)の応答。一致カード消費で除去兵士を城砦広場へ、None は不使用。

    どちらの場合も奇襲2ヒット後のロール継続(4.3.1.II)を後処理する(15.3)。
    """
    dec = state.pending[-1]
    assert isinstance(dec, FieldHospitalDecision)
    state = state.pop_pending()
    if action.card_id is not None:
        from .factions.marquise import _keep_clearing
        state = discard_card(state, FactionId.MARQUISE, action.card_id)
        keep_cid = _keep_clearing(state)
        assert keep_cid >= 0, "field hospital without keep on map"
        # remove_piece で既にサプライへ戻っている兵士を城砦広場へ取り出す(6.2.3)
        ms = state.marquise()
        take = min(dec.count, ms.soldiers_supply)
        state = state.with_clearing(
            state.clearing(keep_cid).add_soldiers(FactionId.MARQUISE, take))
        state = state.with_faction_state(dataclasses.replace(
            state.marquise(), soldiers_supply=state.marquise().soldiers_supply - take))
    return battle_mod._continue_roll_after(state, dec.ctx, dec.roll_after, rng)


def _apply_labor(state: GameState, action: MarquiseLabor, rng) -> GameState:
    """労働(6.5.5)。一致カード消費で製材所広場に木材1。"""
    state = discard_card(state, FactionId.MARQUISE, action.card_id)
    ms = state.marquise()
    assert ms.wood_supply > 0
    state = state.with_faction_state(dataclasses.replace(ms, wood_supply=ms.wood_supply - 1))
    cs = state.clearing(action.clearing).add_token(Piece(FactionId.MARQUISE, T_WOOD))
    state = state.with_clearing(cs)
    return _spend_action(state)


def _apply_play_bird(state: GameState, action: MarquisePlayBirdCard, rng) -> GameState:
    """鳥カード消費で追加アクション1回(6.5)。消費自体はアクションに含めない。"""
    state = discard_card(state, FactionId.MARQUISE, action.card_id)
    ms = state.marquise()
    return state.with_faction_state(dataclasses.replace(ms, actions_left=ms.actions_left + 1))


# ---------------- 戦闘(4.3)/デシジョン応答 ----------------
def _apply_declare_battle(state: GameState, action: DeclareBattle, rng) -> GameState:
    """戦闘宣言(4.3)。command-warren(18.3)の応答時はアクションを消費しない。"""
    is_command_warren = bool(state.pending) and isinstance(
        state.pending[-1], CommandWarrenDecision)
    if is_command_warren:
        state = state.pop_pending()
    state = battle_mod.declare_battle(state, action, rng)
    if not is_command_warren and action.player == FactionId.MARQUISE:
        state = _spend_action(state)  # 6.5.1 戦闘アクション
    return state


def _apply_ambush_choice(state: GameState, action: AmbushChoice, rng) -> GameState:
    dec = state.pending[-1]
    if isinstance(dec, AmbushDefenderDecision):
        return battle_mod.resolve_ambush_defender(state, action.card_id, rng)
    if isinstance(dec, AmbushAttackerDecision):
        return battle_mod.resolve_ambush_attacker(state, action.card_id, rng)
    raise AssertionError("AmbushChoice without ambush decision")


def _apply_allocate_hit(state: GameState, action: AllocateHit, rng) -> GameState:
    return battle_mod.allocate_hit(state, action, rng)


def _apply_discard(state: GameState, action: DiscardCard, rng) -> GameState:
    """手札調整(6.6)。5枚以下になったらデシジョンを解消。"""
    dec = state.pending[-1]
    assert isinstance(dec, DiscardDecision)
    state = discard_card(state, action.player, action.card_id)
    if len(state.fs(action.player).hand) <= 5:
        state = state.pop_pending()
    return state


def _apply_craft(state: GameState, action: CraftCard, rng) -> GameState:
    # 放浪部族(9.5.8)はHの exhaust を伴う専用処理(factions/vagabond.py)
    if action.player == FactionId.VAGABOND:
        return vagabond_mod.apply_craft_vagabond(state, action, rng)
    return apply_craft(state, action, rng)


# ---------------- immediate/persistent クラフト効果(18.3 / 18.4) ----------------
def _apply_use_crafted_effect(state: GameState, action: UseCraftedEffect,
                              rng) -> GameState:
    """UseCraftedEffect のディスパッチ: 戦闘効果ステージ中か否かで振り分ける。"""
    if state.pending and isinstance(state.pending[-1], BattleEffectsDecision):
        return battle_mod.apply_battle_effect(state, action, rng)
    from .crafting import apply_phase_effect
    return apply_phase_effect(state, action, rng)


def _apply_skip_battle_effects(state: GameState, action: SkipBattleEffects,
                               rng) -> GameState:
    return battle_mod.apply_skip_battle_effects(state, action, rng)


def _apply_vagabond_item_choice(state: GameState, action: VagabondItemChoice,
                                rng) -> GameState:
    """アイテム選択(回復 9.4.1 / 損傷 9.2.7 / 上限除外 9.6.4)のディスパッチ。"""
    dec = state.pending[-1]
    if isinstance(dec, RefreshDecision):
        return vagabond_mod.apply_refresh_choice(state, action, rng)
    if isinstance(dec, ItemDamageDecision):
        return vagabond_mod.apply_damage_choice(state, action, rng)
    if isinstance(dec, ItemLimitDecision):
        return vagabond_mod.apply_limit_choice(state, action, rng)
    raise AssertionError("VagabondItemChoice without item decision")


# ---------------- 圧倒カード / 共闘軍(3.3 / 9.2.8) ----------------
def _apply_activate_dominance(state: GameState, action: ActivateDominance,
                              rng) -> GameState:
    """圧倒カードの発動(3.3.1)。手札→公開(fs.dominance_card)。以後VP凍結。"""
    fs = state.fs(action.player)
    hand = list(fs.hand)
    hand.remove(action.card_id)
    # 得点マーカーを得点表から取り除く=以後 award_vp が no-op(14.2)。VPは据え置く。
    return state.with_faction_state(
        dataclasses.replace(fs, hand=tuple(hand), dominance_card=action.card_id))


def _apply_take_dominance(state: GameState, action: TakeDominance,
                          rng) -> GameState:
    """盤脇の圧倒カードの回収(3.3.4)。一致動物種カードを消費し圧倒を手札へ。"""
    # 支払カードは捨て山へ(圧倒カードなら盤脇へ, discard_card→to_discard 経由)
    state = discard_card(state, action.player, action.spend_card_id)
    aside = list(state.dominance_aside)
    aside.remove(action.dominance_id)
    state = state.replace(dominance_aside=tuple(aside))
    fs = state.fs(action.player)
    return state.with_faction_state(
        dataclasses.replace(fs, hand=fs.hand + (action.dominance_id,)))


def _apply_vagabond_coalition(state: GameState, action: VagabondCoalition,
                              rng) -> GameState:
    """共闘軍の結成(9.2.8)。圧倒カードを公開扱いで保持し partner と共闘。"""
    from .factions.vagabond import _rel_get, _rel_set
    vs = state.vagabond()
    hand = list(vs.hand)
    hand.remove(action.card_id)
    # カードは公開扱い(保存則の勘定用に dominance_card に保持)。以後VP凍結。
    vs = dataclasses.replace(vs, hand=tuple(hand), dominance_card=action.card_id,
                             coalition_with=action.partner)
    # 敵対派閥と共闘するなら関係マーカーを無関心へ戻す(9.2.9.III.d)
    if _rel_get(vs, action.partner) == -1:
        vs = dataclasses.replace(vs, relationships=_rel_set(vs, action.partner, 0))
    return state.with_faction_state(vs)


_HANDLERS = {
    EndPhase: _apply_end_phase,
    ActivateDominance: _apply_activate_dominance,
    TakeDominance: _apply_take_dominance,
    VagabondCoalition: _apply_vagabond_coalition,
    SetupChooseKeep: _apply_choose_keep,
    MarquiseBuild: _apply_build,
    MarquiseRecruit: _apply_recruit,
    MarquiseMarch: _apply_march,
    MarquiseSkipMove: _apply_skip_move,
    MarquiseFieldHospital: _apply_field_hospital,
    MarquiseLabor: _apply_labor,
    MarquisePlayBirdCard: _apply_play_bird,
    DeclareBattle: _apply_declare_battle,
    AmbushChoice: _apply_ambush_choice,
    AllocateHit: _apply_allocate_hit,
    DiscardCard: _apply_discard,
    CraftCard: _apply_craft,
    UseCraftedEffect: _apply_use_crafted_effect,
    SkipBattleEffects: _apply_skip_battle_effects,
    # 鷲巣王朝(第7章)。本体は factions/eyrie.py
    EyrieChooseCorner: eyrie_mod.apply_choose_corner,
    EyrieChooseLeader: eyrie_mod.apply_choose_leader,
    EyrieAddToDecree: eyrie_mod.apply_add_to_decree,
    EyrieSkipDecree: eyrie_mod.apply_skip_decree,
    EyriePlaceRoost: eyrie_mod.apply_place_roost,
    EyrieRecruit: eyrie_mod.apply_decree_recruit,
    EyrieDecreeMove: eyrie_mod.apply_decree_move,
    EyrieDecreeBattle: eyrie_mod.apply_decree_battle,
    EyrieDecreeBuild: eyrie_mod.apply_decree_build,
    EyrieTurmoil: eyrie_mod.apply_turmoil,
    # 森林連合(第8章)。本体は factions/alliance.py
    AllianceRevolt: alliance_mod.apply_revolt,
    AllianceSpreadSympathy: alliance_mod.apply_spread,
    AllianceMobilize: alliance_mod.apply_mobilize,
    AllianceTrain: alliance_mod.apply_train,
    AllianceOpMove: alliance_mod.apply_op_move,
    AllianceOpBattle: alliance_mod.apply_op_battle,
    AllianceOpRecruit: alliance_mod.apply_op_recruit,
    AllianceOpOrganize: alliance_mod.apply_op_organize,
    AllianceEndOps: alliance_mod.apply_end_ops,
    OutragePay: alliance_mod.apply_outrage_pay,
    AllianceDiscardSupporter: alliance_mod.apply_discard_supporter,
    # 放浪部族(第9章)。本体は factions/vagabond.py
    VagabondChooseCharacter: vagabond_mod.apply_choose_character,
    VagabondChooseForest: vagabond_mod.apply_choose_forest,
    VagabondSlip: vagabond_mod.apply_slip,
    VagabondMove: vagabond_mod.apply_move,
    VagabondBattle: vagabond_mod.apply_battle,
    VagabondExplore: vagabond_mod.apply_explore,
    VagabondAid: vagabond_mod.apply_aid,
    VagabondQuest: vagabond_mod.apply_quest,
    VagabondStrike: vagabond_mod.apply_strike,
    VagabondRepair: vagabond_mod.apply_repair,
    VagabondSpecial: vagabond_mod.apply_special,
    VagabondItemChoice: _apply_vagabond_item_choice,
}
