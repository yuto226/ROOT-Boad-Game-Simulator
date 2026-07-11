"""戦闘サブシステム(4.3 の4ステップ)。

保留デシジョンスタック(3.2)で表現する。ステップ:
1. 防御側の奇襲(4.3.1) → AmbushDefenderDecision
2. 攻撃側の妨害(4.3.1.I) → AmbushAttackerDecision
3. ダイス(4.3.2, rng) → 無防備+1(4.3.3.II)
4. ヒットの割り振り(4.3.4) → AllocateHitsDecision(受け手ごと)

除去の行き先(3.5): 兵士=サプライ, 建物=派閥ボードトラック, 木材=サプライ,
城砦=ゲーム除外。建物/トークン除去で除去側に1VP(3.2.1)。
"""
from __future__ import annotations

import dataclasses
from typing import List, Optional, Tuple

from .actions import (
    AllocateHit,
    AllocateHitsDecision,
    AmbushAttackerDecision,
    AmbushDefenderDecision,
    BattleCtx,
    BattleEffectsDecision,
    DeclareBattle,
    ItemDamageDecision,
    SkipBattleEffects,
    UseCraftedEffect,
)
from .state import GameState
from .types import (
    B_BASE,
    B_ROOST,
    FactionId,
    MARQUISE_BUILDINGS,
    Piece,
    Suit,
    T_KEEP,
    T_SYMPATHY,
    T_WOOD,
)


def _eyrie_leader(state: GameState) -> Optional[str]:
    """鷲巣王朝の現君主(不参加なら None)。"""
    if FactionId.EYRIE not in state.factions:
        return None
    return state.eyrie().leader


def _is_vagabond(state: GameState, faction: FactionId) -> bool:
    """放浪部族の読み替えフック(9.2.4/9.2.6/9.2.7)の作動条件。

    放浪部族参戦時のみ True(既存3派閥の挙動を変えない, DESIGN.md 8.4)。
    """
    return faction == FactionId.VAGABOND and FactionId.VAGABOND in state.factions


def _vagabond_swords(state: GameState) -> int:
    """非損傷Sの枚数(出目上限 9.2.6・無防備判定 9.2.4)。"""
    from .factions.vagabond import _nondamaged_sword
    return _nondamaged_sword(state.vagabond().items)


def _vagabond_can_take_hits(state: GameState) -> bool:
    """継続判定(9.2.7): 非損傷アイテムが残っているか。"""
    from .factions.vagabond import _has_nondamaged
    return _has_nondamaged(state.vagabond().items)


# ---------------- 除去(3.5) ----------------
def _award_vp(state: GameState, faction: FactionId, vp: int) -> GameState:
    # VP凍結(圧倒/共闘, 14.2)と非負クランプを中央ヘルパへ集約する。
    from .mechanics import award_vp
    return award_vp(state, faction, vp)


def _return_building_to_board(state: GameState, victim: FactionId, kind: str) -> GameState:
    """建物タイルを派閥ボードの最右空き枠へ(3.5)。猫は built_count を減らす。

    鷲巣の止まり木は built_roosts を減らす(7.6.1 のVP計算と連動)。
    """
    if victim == FactionId.MARQUISE and kind in MARQUISE_BUILDINGS:
        ms = state.marquise()
        field = {"sawmill": "built_sawmill", "workshop": "built_workshop",
                 "recruiter": "built_recruiter"}[kind]
        cur = getattr(ms, field)
        return state.with_faction_state(dataclasses.replace(ms, **{field: max(0, cur - 1)}))
    if victim == FactionId.EYRIE and kind == B_ROOST:
        es = state.eyrie()
        return state.with_faction_state(dataclasses.replace(
            es, built_roosts=max(0, es.built_roosts - 1)))
    return state


def _maybe_despot_vp(state: GameState, source: Optional[FactionId]) -> GameState:
    """独裁者(7.8.4): 鷲巣が敵の建物/専用トークンを1個以上除去した戦闘で
    追加1VP(1戦闘につき1回まで)。フラグは declare_battle でリセットされる。
    """
    if source != FactionId.EYRIE or _eyrie_leader(state) != "despot":
        return state
    es = state.eyrie()
    if es.despot_awarded:
        return state
    state = _award_vp(state, FactionId.EYRIE, 1)
    return state.with_faction_state(
        dataclasses.replace(state.eyrie(), despot_awarded=True))


def _return_token_to_supply(state: GameState, victim: FactionId, kind: str) -> GameState:
    """トークンを行き先へ(3.5)。木材=サプライ, 城砦=ゲーム除外。"""
    if kind == T_WOOD and victim == FactionId.MARQUISE:
        ms = state.marquise()
        return state.with_faction_state(dataclasses.replace(ms, wood_supply=ms.wood_supply + 1))
    # 城砦(keep)は再配置不可のためゲームから除外(6.2.2) → 何もしない
    return state


def _vagabond_relation_hook(state: GameState, victim: FactionId,
                            source: Optional[FactionId], is_soldier: bool,
                            battle: bool) -> GameState:
    """放浪部族が除去者のときの敵対化(9.2.9.III)・悪名(III.a)フック。"""
    if (source == FactionId.VAGABOND and FactionId.VAGABOND in state.factions
            and victim != FactionId.VAGABOND):
        from .factions.vagabond import on_vagabond_removes
        state = on_vagabond_removes(state, victim, is_soldier, battle)
    return state


def remove_piece(state: GameState, clearing: int, victim: FactionId,
                 target: Tuple, source: Optional[FactionId],
                 battle: bool = True) -> GameState:
    """戦場から victim の配置物1つを除去(4.3.4)。source に建物/トークンVP付与。

    ``battle=False`` は戦闘によらない除去(放浪部族の狙撃 9.5.6 等)。
    悪名(9.2.9.III.a)は戦闘除去のみが対象になる。
    """
    cs = state.clearing(clearing)
    kind = target[0]
    if kind == "soldier":
        cs = cs.add_soldiers(victim, -1)
        state = state.with_clearing(cs)
        fs = state.fs(victim)
        state = state.with_faction_state(
            dataclasses.replace(fs, soldiers_supply=fs.soldiers_supply + 1))
        state = _vagabond_relation_hook(state, victim, source, True, battle)
        return state
    if kind == "building":
        piece = Piece(victim, target[1])
        cs = cs.remove_building(piece)
        state = state.with_clearing(cs)
        state = _return_building_to_board(state, victim, target[1])
        if source is not None:
            state = _award_vp(state, source, 1)  # 3.2.1
            state = _maybe_despot_vp(state, source)  # 7.8.4
        state = _vagabond_relation_hook(state, victim, source, False, battle)
        # 森林連合の拠点タイル除去の連鎖処理(8.2.4)
        if victim == FactionId.ALLIANCE and target[1] == B_BASE:
            from .factions import alliance as alliance_mod
            state = alliance_mod.on_base_removed(state, clearing)
        return state
    if kind == "token":
        cs = cs.remove_one_token(victim, target[1])
        state = state.with_clearing(cs)
        state = _return_token_to_supply(state, victim, target[1])
        if source is not None:
            state = _award_vp(state, source, 1)  # 3.2.1
            state = _maybe_despot_vp(state, source)  # 7.8.4
        state = _vagabond_relation_hook(state, victim, source, False, battle)
        # 支持トークン除去 → 支持数の減算 + 蜂起(8.2.6)
        if victim == FactionId.ALLIANCE and target[1] == T_SYMPATHY:
            from .factions import alliance as alliance_mod
            state = alliance_mod.on_sympathy_removed(state, source, clearing)
        return state
    raise ValueError("unknown removal target %r" % (target,))


def _has_pieces(state: GameState, clearing: int, faction: FactionId) -> bool:
    cs = state.clearing(clearing)
    if cs.soldier_count(faction) > 0:
        return True
    return any(p.faction == faction for p in cs.buildings + cs.tokens)


# ---------------- ダイスとヒット割り振り ----------------
def _hits_decision(state: GameState, ctx: BattleCtx, victim: FactionId,
                   source: FactionId, hits: int):
    """受け手ごとのヒット適用デシジョン(4.3.4)。

    受け手が放浪部族なら AllocateHitsDecision の代わりにアイテム損傷
    (ItemDamageDecision, 9.2.7)を積む。
    """
    if _is_vagabond(state, victim):
        return ItemDamageDecision(actor=victim, remaining=hits)
    return AllocateHitsDecision(
        actor=victim, victim=victim, hits=hits,
        source=source, clearing=ctx.clearing)


def _can_take_hits(state: GameState, ctx: BattleCtx, faction: FactionId) -> bool:
    """ヒットを適用できる配置物(放浪部族は非損傷アイテム, 9.2.7)が残るか。"""
    if _is_vagabond(state, faction):
        return _vagabond_can_take_hits(state)
    return _has_pieces(state, ctx.clearing, faction)


def _push_allocations(state: GameState, ctx: BattleCtx,
                      atk_hits: int, def_hits: int) -> GameState:
    """両者のヒット割り振りデシジョンを積む(4.3.4)。"""
    decisions = []
    if atk_hits > 0 and _can_take_hits(state, ctx, ctx.defender):
        decisions.append(_hits_decision(state, ctx, ctx.defender, ctx.attacker, atk_hits))
    if def_hits > 0 and _can_take_hits(state, ctx, ctx.attacker):
        decisions.append(_hits_decision(state, ctx, ctx.attacker, ctx.defender, def_hits))
    if not decisions:
        return state
    return state.push_pending(*decisions)


def _soldier_cap(state: GameState, ctx: BattleCtx, faction: FactionId) -> int:
    """出目上限の基準(4.3.2.I): 戦場の自兵士数。放浪部族は非損傷Sの枚数(9.2.6)。"""
    if _is_vagabond(state, faction):
        return _vagabond_swords(state)
    return state.clearing(ctx.clearing).soldier_count(faction)


def _roll_and_allocate(state: GameState, ctx: BattleCtx, rng) -> GameState:
    """第2ステップ(4.3.2)〜効果使用ステージ(4.3.3, 18.4)への導入。"""
    d1 = rng.randint(1, 6)
    d2 = rng.randint(1, 6)
    hi, lo = max(d1, d2), min(d1, d2)
    atk_sol = _soldier_cap(state, ctx, ctx.attacker)
    def_sol = _soldier_cap(state, ctx, ctx.defender)
    # 通常(4.3.2): 攻撃側=大きい方、防御側=小さい方。
    # ゲリラ戦(8.2.2): 防御側が森林連合なら攻守のダイス割当を反転する。
    if ctx.defender == FactionId.ALLIANCE:
        atk_roll, def_roll = lo, hi
    else:
        atk_roll, def_roll = hi, lo
    # ロール由来ヒット(4.3.2.I: 出目上限=戦場の自兵士数)。armorers(18.4)が
    # 軽減できるのはこの値のみ。無防備/司令官のボーナスおよび sappers/
    # brutal-tactics の追加ヒットは対象外(_finalize_battle_effects で加算)。
    roll_att = min(atk_roll, atk_sol)
    roll_def = min(def_roll, def_sol)
    return _start_battle_effects(state, ctx, roll_att, roll_def, rng)


def roll_battle(state: GameState, ctx: BattleCtx, rng) -> GameState:
    """ロール以降を実行する公開エントリ(奇襲損傷の後続 4.3.1.II 用)。"""
    return _roll_and_allocate(state, ctx, rng)


# ---------------- 戦闘効果使用ステージ(4.3.3, 18.4) ----------------
#: 攻撃側/防御側それぞれが使える戦闘効果 base_id(所有条件は crafted_effects)。
_ATTACKER_BATTLE_EFFECTS: Tuple[str, ...] = ("armorers", "brutal-tactics")
_DEFENDER_BATTLE_EFFECTS: Tuple[str, ...] = ("armorers", "sappers")


def _battle_effect_options(state: GameState, faction: FactionId, ctx: BattleCtx,
                           is_attacker: bool) -> List[str]:
    """この戦闘でまだ使える戦闘効果カード(18.4)の base_id 一覧。

    armorers/sappers はカード自体が使用時に手元(crafted_effects)から消えるため
    自然に1回きりになる。brutal-tactics は破棄されないため、``ctx.atk_extra_hits``
    (brutal-tactics のみが加算する値)で使用済みを判定する。
    """
    fs = state.fs(faction)
    keys = _ATTACKER_BATTLE_EFFECTS if is_attacker else _DEFENDER_BATTLE_EFFECTS
    out: List[str] = []
    for key in keys:
        if key not in fs.crafted_effects:
            continue
        if key == "brutal-tactics" and ctx.atk_extra_hits != 0:
            continue
        out.append(key)
    return out


def _start_battle_effects(state: GameState, ctx: BattleCtx, roll_att: int,
                          roll_def: int, rng) -> GameState:
    """効果使用ステージの開始(4.3.3、攻撃側→防御側の固定順に簡略化, 18.4)。"""
    if _battle_effect_options(state, ctx.attacker, ctx, True):
        return state.push_pending(BattleEffectsDecision(
            actor=ctx.attacker, ctx=ctx, roll_att=roll_att, roll_def=roll_def))
    return _advance_to_defender_effects(state, ctx, roll_att, roll_def, rng)


def _advance_to_defender_effects(state: GameState, ctx: BattleCtx, roll_att: int,
                                 roll_def: int, rng) -> GameState:
    if _battle_effect_options(state, ctx.defender, ctx, False):
        return state.push_pending(BattleEffectsDecision(
            actor=ctx.defender, ctx=ctx, roll_att=roll_att, roll_def=roll_def))
    return _finalize_battle_effects(state, ctx, roll_att, roll_def, rng)


def _finalize_battle_effects(state: GameState, ctx: BattleCtx, roll_att: int,
                             roll_def: int, rng) -> GameState:
    """効果ステージ完了後、ヒットを確定して割り振りへ(18.4)。

    無防備の追加ヒット(4.3.3.II)・司令官(7.8.3)は roll と独立に再計算する
    (armorers 使用有無に関わらず board 状態は効果ステージ中不変なので安全)。
    """
    def_sol = _soldier_cap(state, ctx, ctx.defender)
    atk_bonus = 1 if def_sol == 0 else 0  # 無防備(4.3.3.II)
    if ctx.attacker == FactionId.EYRIE and _eyrie_leader(state) == "commander":
        atk_bonus += 1  # 司令官(7.8.3)
    atk_hits = roll_att + atk_bonus + ctx.atk_extra_hits
    def_hits = roll_def + ctx.def_extra_hits
    return _push_allocations(state, ctx, atk_hits, def_hits)


def battle_effects_options(state: GameState, dec: BattleEffectsDecision) -> List:
    """BattleEffectsDecision の選択肢: 所有効果ごとの UseCraftedEffect + Skip。"""
    is_attacker = dec.actor == dec.ctx.attacker
    avail = _battle_effect_options(state, dec.actor, dec.ctx, is_attacker)
    out: List = [SkipBattleEffects(player=dec.actor)]
    for key in avail:
        out.append(UseCraftedEffect(player=dec.actor, card_key=key))
    return out


def apply_battle_effect(state: GameState, action: UseCraftedEffect, rng) -> GameState:
    """戦闘効果カードの使用(18.4)。BattleEffectsDecision への応答。"""
    from .mechanics import discard_crafted_effect
    dec = state.pending[-1]
    assert isinstance(dec, BattleEffectsDecision)
    ctx, roll_att, roll_def = dec.ctx, dec.roll_att, dec.roll_def
    faction = action.player
    key = action.card_key
    is_attacker = faction == ctx.attacker

    if key == "armorers":
        # 自分が受けるロール由来ヒットを0にする(奇襲2ヒット・sappers/brutal は対象外)
        state = discard_crafted_effect(state, faction, key)
        if is_attacker:
            roll_def = 0
        else:
            roll_att = 0
    elif key == "sappers":
        state = discard_crafted_effect(state, faction, key)
        ctx = dataclasses.replace(ctx, def_extra_hits=ctx.def_extra_hits + 1)
    elif key == "brutal-tactics":
        # 破棄しない(毎戦闘使える)。防御側への追加1ヒット+防御側に1VP
        ctx = dataclasses.replace(ctx, atk_extra_hits=ctx.atk_extra_hits + 1)
        state = _award_vp(state, ctx.defender, 1)
    else:
        raise NotImplementedError("unknown battle effect %r" % (key,))

    state = state.pop_pending()
    if _battle_effect_options(state, faction, ctx, is_attacker):
        return state.push_pending(BattleEffectsDecision(
            actor=faction, ctx=ctx, roll_att=roll_att, roll_def=roll_def))
    if is_attacker:
        return _advance_to_defender_effects(state, ctx, roll_att, roll_def, rng)
    return _finalize_battle_effects(state, ctx, roll_att, roll_def, rng)


def apply_skip_battle_effects(state: GameState, action: SkipBattleEffects, rng) -> GameState:
    """戦闘効果ステージのパス(18.4)。"""
    dec = state.pending[-1]
    assert isinstance(dec, BattleEffectsDecision)
    ctx, roll_att, roll_def = dec.ctx, dec.roll_att, dec.roll_def
    is_attacker = action.player == ctx.attacker
    state = state.pop_pending()
    if is_attacker:
        return _advance_to_defender_effects(state, ctx, roll_att, roll_def, rng)
    return _finalize_battle_effects(state, ctx, roll_att, roll_def, rng)


# ---------------- エントリポイント(apply から呼ぶ) ----------------
def _matching_ambush(state: GameState, faction: FactionId, clearing: int) -> Optional[str]:
    """戦場と一致する奇襲カードを手札から探す(4.3.1)。鳥はワイルド(2.1.1)。"""
    suit = state.map.clearing(clearing).suit
    for cid in state.fs(faction).hand:
        cdef = state.cards.get(cid)
        if cdef.is_ambush and (cdef.suit == suit or cdef.suit == Suit.BIRD):
            return cid
    return None


def declare_battle(state: GameState, action: DeclareBattle, rng) -> GameState:
    """戦闘宣言(4.3)。防御側に奇襲機会があれば積み、なければ即ロール。"""
    ctx = BattleCtx(attacker=action.player, defender=action.defender,
                    clearing=action.clearing)
    # 独裁者VP(7.8.4)の1戦闘1回フラグをリセット(戦闘は入れ子にならない)
    if (FactionId.EYRIE in (ctx.attacker, ctx.defender)
            and FactionId.EYRIE in state.factions):
        es = state.eyrie()
        if es.despot_awarded:
            state = state.with_faction_state(
                dataclasses.replace(es, despot_awarded=False))
    # 放浪部族の戦闘内損傷カウンタ(9.2.9.II.d 用の予約)を宣言時にリセット。
    # command-warren(18.3)経由の宣言は apply_battle(9.5.2)を通らないためここで行う。
    if _is_vagabond(state, ctx.attacker):
        vs = state.vagabond()
        if vs.damage_hits_this_battle:
            state = state.with_faction_state(
                dataclasses.replace(vs, damage_hits_this_battle=0))
    # scouting-party(18.4): 攻撃側が所有していれば防御側の奇襲ステップを丸ごと
    # スキップする(4.3.1に入らない)。破棄なし・毎戦闘有効。
    if "scouting-party" in state.fs(ctx.attacker).crafted_effects:
        return _roll_and_allocate(state, ctx, rng)
    if _matching_ambush(state, ctx.defender, ctx.clearing) is not None:
        return state.push_pending(AmbushDefenderDecision(actor=ctx.defender, ctx=ctx))
    return _roll_and_allocate(state, ctx, rng)


def resolve_ambush_defender(state: GameState, card_id: Optional[str], rng) -> GameState:
    """防御側の奇襲選択(4.3.1)。"""
    from .mechanics import discard_card
    dec = state.pending[-1]
    ctx = dec.ctx
    state = state.pop_pending()
    if card_id is None:  # 奇襲しない
        return _roll_and_allocate(state, ctx, rng)
    state = discard_card(state, ctx.defender, card_id)
    ctx = dataclasses.replace(ctx, ambush_used=True)
    # 攻撃側に妨害機会(4.3.1.I)があれば積む。なければ即2ヒット。
    if _matching_ambush(state, ctx.attacker, ctx.clearing) is not None:
        return state.push_pending(AmbushAttackerDecision(actor=ctx.attacker, ctx=ctx))
    return _apply_ambush_hits(state, ctx, rng)


def resolve_ambush_attacker(state: GameState, card_id: Optional[str], rng) -> GameState:
    """攻撃側の奇襲妨害選択(4.3.1.I)。"""
    from .mechanics import discard_card
    dec = state.pending[-1]
    ctx = dec.ctx
    state = state.pop_pending()
    if card_id is not None:  # 妨害成立 → 奇襲は打ち消され通常ロールへ
        state = discard_card(state, ctx.attacker, card_id)
        return _roll_and_allocate(state, ctx, rng)
    return _apply_ambush_hits(state, ctx, rng)


def _apply_ambush_hits(state: GameState, ctx: BattleCtx, rng) -> GameState:
    """奇襲2ヒットを攻撃側へ即時適用(4.3.1.II)。コマ全滅なら戦闘終了。

    終了判定は「攻撃側のコマ(=兵士等の立体物, G.1.17)がすべて除去」
    であり、建物タイル・トークンは含めない(建物が残っていても終了)。
    ※簡略化: 2ヒットの除去対象は兵士優先の自動選択(本来は 4.3.4 と
    同様に受け手が選択する。兵士のみなら結果は同一)。

    攻撃側が放浪部族なら2ヒット=アイテム2損傷(9.2.7、選択は Decision)。
    放浪者コマは除去されない(9.2.2)ため「全滅で戦闘終了」は発生せず、
    損傷解決後にロールへ継続する(roll_after=True)。

    非放浪部族の攻撃側は、2ヒットの除去対象を受け手自身が選択する
    (4.3.4 の兵士優先は allocate_options が強制, 15.4)。解決後の継続
    (生存ならロール、全滅なら戦闘終了)は :func:`_finish_allocation` に集約する。
    """
    if _is_vagabond(state, ctx.attacker):
        if _vagabond_can_take_hits(state):
            return state.push_pending(ItemDamageDecision(
                actor=ctx.attacker, remaining=2, ctx=ctx, roll_after=True))
        return _roll_and_allocate(state, ctx, rng)  # 損傷可能なアイテムなし → 無視
    if _has_pieces(state, ctx.clearing, ctx.attacker):
        return state.push_pending(AllocateHitsDecision(
            actor=ctx.attacker, victim=ctx.attacker, hits=2, source=ctx.defender,
            clearing=ctx.clearing, ctx=ctx, roll_after=True))
    return _roll_and_allocate(state, ctx, rng)  # 除去できるコマなし → ロールへ


def allocate_hit(state: GameState, action: AllocateHit, rng) -> GameState:
    """ヒット1つを適用(4.3.4)。

    このデシジョンを先に pop してから除去する。除去(remove_piece)は
    森林連合の蜂起(8.2.6)や拠点喪失時の支援者調整(8.2.4)で新たな
    デシジョンを pending に積むことがあるため、pop を除去より後に行うと
    スタック先頭を取り違える。継続の割り振りは除去後に積み直す。

    デシジョンが尽きたら(残ヒット0 or 配置物なし)イベント境界処理
    :func:`_finish_allocation` へ委ねる(野戦病院 6.2.3・奇襲後のロール継続
    4.3.1.II)。猫兵士の除去数は ``removed_soldiers`` に集計する(6.2.3)。
    """
    dec = state.pending[-1]
    state = state.pop_pending()
    is_soldier = action.target[0] == "soldier"
    state = remove_piece(state, dec.clearing, dec.victim, action.target, dec.source)
    removed = dec.removed_soldiers + (
        1 if (is_soldier and dec.victim == FactionId.MARQUISE) else 0)
    remaining = dec.hits - 1
    if remaining > 0 and _has_pieces(state, dec.clearing, dec.victim):
        return state.push_pending(
            dataclasses.replace(dec, hits=remaining, removed_soldiers=removed))
    return _finish_allocation(
        state, dataclasses.replace(dec, removed_soldiers=removed), rng)


def _continue_roll_after(state: GameState, ctx, roll_after: bool, rng) -> GameState:
    """奇襲2ヒット(4.3.1.II)後のロール継続。

    攻撃側の兵士が戦場に残っていればロールへ(4.3.2)、全滅なら戦闘終了。
    野戦病院(6.2.3)で城砦へ戻した兵士は戦場にいないため全滅判定は正しい。
    """
    if roll_after and ctx is not None:
        if state.clearing(ctx.clearing).soldier_count(ctx.attacker) > 0:
            return roll_battle(state, ctx, rng)
    return state


def _finish_allocation(state: GameState, dec: AllocateHitsDecision, rng) -> GameState:
    """割り振りデシジョン完了時のイベント境界処理(6.2.3 / 4.3.1.II, 15.3)。

    1. 受け手=猫かつ兵士除去ありなら野戦病院(6.2.3)を1回だけ判定する。
       デシジョンが積まれたら ctx/roll_after を引き継いで return(ロール継続は
       病院解決後に行われる)。
    2. そうでなければ奇襲後のロール継続(4.3.1.II)を処理する。
    """
    if dec.victim == FactionId.MARQUISE and dec.removed_soldiers > 0:
        from .factions import marquise as marquise_mod
        pushed = marquise_mod.maybe_field_hospital(
            state, dec.clearing, dec.removed_soldiers,
            ctx=dec.ctx, roll_after=dec.roll_after)
        if pushed is not None:
            return pushed
    return _continue_roll_after(state, dec.ctx, dec.roll_after, rng)


def allocate_options(state: GameState, dec: AllocateHitsDecision) -> List[AllocateHit]:
    """割り振りデシジョンの選択肢(4.3.4: 兵士が残る間は建物/トークン不可)。"""
    cs = state.clearing(dec.clearing)
    if cs.soldier_count(dec.victim) > 0:
        return [AllocateHit(player=dec.actor, target=("soldier",))]
    out: List[AllocateHit] = []
    seen = set()
    for p in cs.buildings_of(dec.victim):
        if ("building", p.kind) not in seen:
            seen.add(("building", p.kind))
            out.append(AllocateHit(player=dec.actor, target=("building", p.kind)))
    for p in cs.tokens_of(dec.victim):
        if ("token", p.kind) not in seen:
            seen.add(("token", p.kind))
            out.append(AllocateHit(player=dec.actor, target=("token", p.kind)))
    return out
