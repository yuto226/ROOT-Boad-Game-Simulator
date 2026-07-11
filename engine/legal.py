"""合法手の列挙(3.2 / 3.3)。

pending スタックが空でなければスタック先頭(末尾要素)の Decision に
対する選択肢のみを返す。空ならターンプレイヤーの派閥ロジックへ
ディスパッチする(DESIGN.md 3.2)。
"""
from __future__ import annotations

from typing import List

from .actions import (
    Action,
    ActivateDominance,
    AllocateHitsDecision,
    AmbushAttackerDecision,
    AmbushChoice,
    AmbushDefenderDecision,
    BattleEffectsDecision,
    CobblerMoveDecision,
    CommandWarrenDecision,
    DiscardCard,
    DiscardDecision,
    FieldHospitalDecision,
    MarquiseMarchDecision,
    EyrieDecreeDecision,
    EyrieLeaderDecision,
    EyrieRoostDecision,
    EyrieSetupCornerDecision,
    ItemDamageDecision,
    ItemLimitDecision,
    OutrageDecision,
    RefreshDecision,
    SetupChooseKeep,
    SetupKeepDecision,
    SupportersLimitDecision,
    TakeDominance,
    VagabondCoalition,
    VagabondSetupCharacterDecision,
    VagabondSetupForestDecision,
)
from .battle import _matching_ambush, allocate_options, battle_effects_options
from . import crafting as crafting_mod
from .state import GameState
from .types import Corner, FactionId, Phase, Suit


def legal_actions(state: GameState) -> List[Action]:
    """現状態で選択可能な全アクション。"""
    if state.finished:
        return []
    if state.pending:
        return _decision_options(state)
    from .factions import get_logic
    acts = get_logic(state.current_faction()).legal_actions(state)
    # 昼光の共通自由アクション: 圧倒カード発動/回収・共闘軍(3.3 / 9.2.8)。
    # 派閥ロジックには足さず、ここで共通フックとして追加する(14.4)。
    if state.phase == Phase.DAYLIGHT:
        acts = list(acts) + _common_daylight_actions(state)
    # 継続効果カードのフェイズ効果(鳥歌/昼光/夕闇, 18.3)。全フェイズ共通フック。
    acts = list(acts) + crafting_mod.phase_effect_actions(
        state, state.current_faction(), state.phase)
    return acts


def _dedup_by_base(state: GameState, card_ids) -> List[str]:
    """base_id が同じカードは1つに畳む(手札順を保つ, 決定性 10.2)。"""
    seen = set()
    out: List[str] = []
    for cid in card_ids:
        base = state.cards.base_id(cid)
        if base in seen:
            continue
        seen.add(base)
        out.append(cid)
    return out


def _spend_candidates(state: GameState, hand, dom_suit: Suit) -> List[str]:
    """圧倒回収の支払いに使える手札カード(3.3.4 / 2.1.1)。

    鳥の圧倒には鳥カードのみ。一般の圧倒には一致動物種+鳥(ワイルド)。
    """
    out: List[str] = []
    for cid in hand:
        s = state.cards.suit_of(cid)
        if dom_suit == Suit.BIRD:
            if s == Suit.BIRD:
                out.append(cid)
        elif s == dom_suit or s == Suit.BIRD:
            out.append(cid)
    return _dedup_by_base(state, out)


def _coalition_partners(state: GameState) -> List[FactionId]:
    """共闘軍の対象候補(9.2.8): 圧倒未発動・共闘未結成の他派閥のうち最低VP。

    同点なら複数候補を返す(放浪部族が選択, 決定性=factions 定義順)。
    """
    eligible = [f for f in state.factions
                if f != FactionId.VAGABOND
                and state.fs(f).dominance_card is None]
    if not eligible:
        return []
    lowest = min(state.fs(f).vp for f in eligible)
    return [f for f in eligible if state.fs(f).vp == lowest]


def _common_daylight_actions(state: GameState) -> List[Action]:
    """昼光の圧倒/共闘の共通合法手(3.3 / 9.2.8)。手番派閥のみ。"""
    f = state.current_faction()
    fs = state.fs(f)
    out: List[Action] = []
    hand_dominance = _dedup_by_base(
        state, [c for c in fs.hand if state.cards.get(c).is_dominance])

    if f == FactionId.VAGABOND:
        # 放浪部族は圧倒発動不可。代わりに共闘軍(9.2.8, 4人以上戦)。
        if (len(state.factions) >= 4 and fs.coalition_with is None
                and hand_dominance):
            partners = _coalition_partners(state)
            for card_id in hand_dominance:
                for partner in partners:
                    out.append(VagabondCoalition(
                        player=f, card_id=card_id, partner=partner))
        return out

    # 圧倒発動(3.3.1): VP10以上・未発動・手札に圧倒カード
    if fs.dominance_card is None and fs.vp >= 10:
        for card_id in hand_dominance:
            out.append(ActivateDominance(player=f, card_id=card_id))

    # 圧倒回収(3.3.4): 盤脇に圧倒カードがあり一致動物種の手札で支払える
    for dom_id in state.dominance_aside:
        dom_suit = state.cards.suit_of(dom_id)
        for spend_id in _spend_candidates(state, fs.hand, dom_suit):
            out.append(TakeDominance(
                player=f, spend_card_id=spend_id, dominance_id=dom_id))
    return out


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

    if isinstance(dec, BattleEffectsDecision):
        # 戦闘効果使用ステージ(4.3.3, 18.4)
        return battle_effects_options(state, dec)

    if isinstance(dec, CommandWarrenDecision):
        # command-warren(18.3): 無消費の戦闘宣言候補
        return crafting_mod.command_warren_options(state, dec)

    if isinstance(dec, CobblerMoveDecision):
        # cobbler(18.3): 無消費の移動候補
        return crafting_mod.cobbler_move_options(state, dec.actor)

    if isinstance(dec, MarquiseMarchDecision):
        # 行軍の2移動目(6.5.2): 移動候補 + スキップ
        from .factions import marquise
        return marquise.march_decision_options(state)

    if isinstance(dec, FieldHospitalDecision):
        # 野戦病院(6.2.3): 使わない(None)+ 一致カード各種
        from .factions import marquise
        return marquise.field_hospital_options(state, dec)

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

    if isinstance(dec, VagabondSetupCharacterDecision):
        # キャラクター選択(9.3.1)
        from .factions import vagabond
        return vagabond.character_options(state)

    if isinstance(dec, VagabondSetupForestDecision):
        # 開始樹林の選択(9.3.2)
        from .factions import vagabond
        return vagabond.forest_options(state)

    if isinstance(dec, RefreshDecision):
        # 鳥歌の回復(9.4.1)
        from .factions import vagabond
        return vagabond.refresh_options(state, dec)

    if isinstance(dec, ItemDamageDecision):
        # 受けヒットのアイテム損傷(9.2.7 / 9.2.2.I)
        from .factions import vagabond
        return vagabond.damage_options(state, dec)

    if isinstance(dec, ItemLimitDecision):
        # 夕闇のアイテム上限調整(9.6.4)
        from .factions import vagabond
        return vagabond.limit_options(state, dec)

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
