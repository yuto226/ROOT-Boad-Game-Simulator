"""森林連合(ウッドランド・アライアンス)ロジック(第8章)。

合法手生成・フェイズ開始処理・連合固有アクションの適用を担う。
共通アクション(戦闘・移動・クラフト)の本体は engine 側にあり、
ここは「いつ・何回・どのコストで使えるか」を差す(DESIGN.md 3.4)。

派閥コンセプト(8.1): 支持トークンの配置でVPを得る。支持トークンの
配置には支援者カード(第2の手札 8.2.3)が必要で、反乱(8.4.1)で拠点を
設立し、訓練(8.5.3)で指揮官を増やして夕闇の軍事作戦(8.6.1)を行う。

既知の簡略化(レビュー確認点):
- 支援者カードの支払い(反乱・支持拡大)は、一致suitと鳥の両方があるときだけ
  SupporterPaymentDecision で選択化する(19.2)。片方のみなら従来どおり自動。
  同 suit 内のどのカードを払うかは決定的(supporters タプルの先頭一致)=自動。
- 戒厳令(8.4.2.II.a)の「他プレイヤーの兵士3個以上」は、連合以外の
  1派閥が単独で兵士3個以上を置いている場合と解釈する(傭兵等の読み替えは
  フェーズ1未対応)。
"""
from __future__ import annotations

import dataclasses
from typing import List, Optional

from ..actions import (
    Action,
    AllianceDiscardSupporter,
    AllianceEndOps,
    AllianceMobilize,
    AllianceOpBattle,
    AllianceOpMove,
    AllianceOpOrganize,
    AllianceOpRecruit,
    AllianceRevolt,
    AllianceSpendSupporter,
    AllianceSpreadSympathy,
    AllianceTrain,
    DeclareBattle,
    DiscardDecision,
    EndPhase,
    OutrageDecision,
    OutragePay,
    SupporterPaymentDecision,
    SupportersLimitDecision,
)
from ..crafting import legal_crafts
from ..mechanics import award_vp, draw_cards, to_discard
from ..state import GameState
from ..types import (
    B_BASE,
    CLEARING_SUITS,
    FactionId,
    Phase,
    Piece,
    Suit,
    T_SYMPATHY,
)
from . import FactionLogic, register

ALLIANCE = FactionId.ALLIANCE


# ---------------- ヘルパ(支援者・支持トークン) ----------------
def has_base(cs) -> bool:
    return any(p.faction == ALLIANCE and p.kind == B_BASE for p in cs.buildings)


def add_supporter(state: GameState, card_id: str) -> GameState:
    """支援者ボックスへ1枚追加(8.2.3.I の上限処理込み)。

    マップ上に拠点タイルが1枚もない状態で支援者が既に5枚なら、入るはずの
    カードは捨て山へ(8.2.3.I)。拠点が1枚でもあれば上限なし。蜂起・動員・
    セットアップの全経路がこのヘルパを通る。
    """
    als = state.alliance()
    if len(als.bases_placed) == 0 and len(als.supporters) >= 5:
        return to_discard(state, card_id)  # 圧倒カードは盤脇へ(3.3.3/14.3)
    return state.with_faction_state(
        dataclasses.replace(als, supporters=als.supporters + (card_id,)))


def _supporter_payment(state: GameState, suit: Suit, n: int) -> Optional[List[str]]:
    """支援者ボックスから suit と一致する n 枚を選ぶ(決定的)。

    具体的な動物種のカードを先に、鳥カード(ワイルド 2.1.1)を後に消費する。
    n 枚に満たなければ None。
    """
    als = state.alliance()
    specific = [c for c in als.supporters if state.cards.suit_of(c) == suit]
    birds = [c for c in als.supporters if state.cards.suit_of(c) == Suit.BIRD]
    chosen: List[str] = []
    for c in specific + birds:
        if len(chosen) >= n:
            break
        chosen.append(c)
    if len(chosen) < n:
        return None
    return chosen


def _pay_one_supporter(state: GameState, pay_suit: Suit) -> GameState:
    """pay_suit の支援者1枚を支援者ボックスから捨て山へ移す(19.2)。

    同 suit 内のどのカードを払うかは決定的(supporters タプルの先頭一致)。
    """
    als = state.alliance()
    card = next(c for c in als.supporters if state.cards.suit_of(c) == pay_suit)
    supporters = list(als.supporters)
    supporters.remove(card)
    state = state.with_faction_state(
        dataclasses.replace(als, supporters=tuple(supporters)))
    return to_discard(state, card)  # 圧倒カードは盤脇へ(3.3.3/14.3)


def _continue_supporter_payment(state: GameState, suit: Suit, remaining: int,
                                purpose: str, clearing: int, rng) -> GameState:
    """支援者支払いを、選択の余地がない間は自動で進める(19.2)。

    一致suitと鳥の両方があるときだけ ``SupporterPaymentDecision`` を push して
    選択化する(支払い1枚ごとに再push=このヘルパへ戻る)。remaining==0 に
    なったら支払い完了後の処理(反乱の解決・支持トークン配置)へ接続する。
    """
    while remaining > 0:
        als = state.alliance()
        has_specific = any(state.cards.suit_of(c) == suit for c in als.supporters)
        has_bird = any(state.cards.suit_of(c) == Suit.BIRD for c in als.supporters)
        if has_specific and has_bird:
            return state.push_pending(SupporterPaymentDecision(
                actor=ALLIANCE, suit=suit, remaining=remaining,
                purpose=purpose, clearing=clearing))
        assert has_specific or has_bird, "insufficient supporters"
        state = _pay_one_supporter(state, suit if has_specific else Suit.BIRD)
        remaining -= 1
    if purpose == "revolt":
        return _finish_revolt(state, clearing, rng)
    assert purpose == "spread", "unknown supporter payment purpose %r" % (purpose,)
    return _place_sympathy(state, clearing)


def sympathetic_clearings(state: GameState) -> List[int]:
    return [cs.cid for cs in state.clearings if cs.has_token(ALLIANCE, T_SYMPATHY)]


def _matching_sympathy_count(state: GameState, suit: Suit) -> int:
    """suit と一致する支持広場の数(8.4.1.III の兵士コマ数算出)。"""
    return sum(1 for cs in state.clearings
               if cs.has_token(ALLIANCE, T_SYMPATHY)
               and state.map.clearing(cs.cid).suit == suit)


def _place_sympathy(state: GameState, cid: int) -> GameState:
    """支持トークン1個を配置し露出したVPを獲得する(8.4.2.III / 8.6.1.IV)。

    VP = sympathy_vp[配置前のplaced_sympathy]、配置後に placed_sympathy+1。
    """
    als = state.alliance()
    vp = state.board_defs["alliance"]["sympathy_vp"][als.placed_sympathy]
    cs = state.clearing(cid).add_token(Piece(ALLIANCE, T_SYMPATHY))
    state = state.with_clearing(cs)
    als = state.alliance()
    state = state.with_faction_state(dataclasses.replace(
        als, placed_sympathy=als.placed_sympathy + 1))
    # 支持露出VP(8.4.2.III)は中央ヘルパ経由(VP凍結・非負クランプ, 14.2)
    return award_vp(state, ALLIANCE, vp)


def _martial_law(state: GameState, cid: int) -> bool:
    """戒厳令(8.4.2.II.a): 対象広場に連合以外の1派閥が兵士3個以上。"""
    cs = state.clearing(cid)
    return any(f != ALLIANCE and n >= 3 for f, n in cs.soldiers)


def _spread_cost(state: GameState, cid: int) -> int:
    als = state.alliance()
    base = state.board_defs["alliance"]["sympathy_costs"][als.placed_sympathy]
    return base + (1 if _martial_law(state, cid) else 0)


# ---------------- 蜂起・拠点除去のフック(battle.py から呼ばれる) ----------------
def on_sympathy_removed(state: GameState, source: Optional[FactionId],
                        clearing: int) -> GameState:
    """支持トークン除去時(8.2.6 / 8.2.5)。placed_sympathy を減算し蜂起を積む。

    除去者が連合以外の実在プレイヤーなら、その広場についての蜂起(支払い)を
    OutrageDecision として積む(選択肢は legal.py / outrage_options)。
    """
    als = state.alliance()
    state = state.with_faction_state(dataclasses.replace(
        als, placed_sympathy=max(0, als.placed_sympathy - 1)))
    if source is not None and source != ALLIANCE and source in state.factions:
        state = state.push_pending(OutrageDecision(actor=source, clearing=clearing))
    return state


def on_base_removed(state: GameState, clearing: int) -> GameState:
    """拠点タイル除去の連鎖処理(8.2.4)。

    (1) 除去された拠点の動物種を bases_placed から外す。
    (2) その動物種と一致する支援者カード(鳥カード含む)をすべて捨てる。
    (3) 指揮官の半分(端数切り上げ)を除去しサプライへ戻す。
    (4) 全拠点を失い、かつ支援者が5枚を超えて残るなら5枚調整(8.2.3.I)。
    """
    suit = state.map.clearing(clearing).suit
    als = state.alliance()
    bases = list(als.bases_placed)
    if suit.value in bases:
        bases.remove(suit.value)
    kept: List[str] = []
    discarded: List[str] = []
    for c in als.supporters:
        s = state.cards.suit_of(c)
        if s == suit or s == Suit.BIRD:
            discarded.append(c)
        else:
            kept.append(c)
    removed_officers = (als.officers + 1) // 2  # 端数切り上げ
    als = dataclasses.replace(
        als, bases_placed=tuple(bases), supporters=tuple(kept),
        officers=als.officers - removed_officers,
        soldiers_supply=als.soldiers_supply + removed_officers)
    state = state.with_faction_state(als)
    for c in discarded:  # 圧倒カードは盤脇へ(3.3.3/14.3)
        state = to_discard(state, c)
    if not bases and len(kept) > 5:
        state = state.push_pending(SupportersLimitDecision(actor=ALLIANCE))
    return state


def outrage_on_move(state: GameState, mover: FactionId, dst_cid: int, rng) -> GameState:
    """他派閥が支持広場へ兵士コマを移動したとき呼ぶ(8.2.6)。

    連合不参加・移動元が連合自身・移動先が非支持広場なら no-op。該当時は
    移動先の蜂起(支払い)を積む。apply の行軍(猫)・勅令移動(鷲巣)から呼ぶ。
    """
    if ALLIANCE not in state.factions or mover == ALLIANCE:
        return state
    if not state.clearing(dst_cid).has_token(ALLIANCE, T_SYMPATHY):
        return state
    return state.push_pending(OutrageDecision(actor=mover, clearing=dst_cid))


# ---------------- デシジョンの選択肢(legal.py から呼ばれる) ----------------
def outrage_options(state: GameState, dec: OutrageDecision) -> List[Action]:
    """蜂起の支払い先(8.2.6): 広場と一致する手札カードごと。

    一致カード(鳥含む)がなければ、山札トップ補充を表す単一の OutragePay
    (card_id=None)を返す(手札公開はエンジン上 no-op)。
    """
    suit = state.map.clearing(dec.clearing).suit
    out: List[Action] = []
    seen = set()
    for cid in state.fs(dec.actor).hand:
        s = state.cards.suit_of(cid)
        if s == suit or s == Suit.BIRD:
            base = state.cards.base_id(cid)
            if base in seen:
                continue
            seen.add(base)
            out.append(OutragePay(player=dec.actor, card_id=cid))
    if not out:
        out.append(OutragePay(player=dec.actor, card_id=None))
    return out


def supporter_payment_options(state: GameState,
                              dec: SupporterPaymentDecision) -> List[Action]:
    """支援者支払いの選択肢(19.2): 一致suit / 鳥のうち払えるもの。

    デシジョンは両方あるときにしか積まれないため通常2択だが、防御的に
    現在の支援者ボックスから列挙する。
    """
    als = state.alliance()
    out: List[Action] = []
    if any(state.cards.suit_of(c) == dec.suit for c in als.supporters):
        out.append(AllianceSpendSupporter(player=ALLIANCE, suit=dec.suit))
    if any(state.cards.suit_of(c) == Suit.BIRD for c in als.supporters):
        out.append(AllianceSpendSupporter(player=ALLIANCE, suit=Suit.BIRD))
    return out


def supporters_limit_options(state: GameState,
                             dec: SupportersLimitDecision) -> List[Action]:
    """支援者5枚調整(8.2.4): 捨てる支援者カードごと。"""
    out: List[Action] = []
    seen = set()
    for cid in state.alliance().supporters:
        base = state.cards.base_id(cid)
        if base in seen:
            continue
        seen.add(base)
        out.append(AllianceDiscardSupporter(player=ALLIANCE, card_id=cid))
    return out


# ---------------- 合法手の部品 ----------------
def _revolt_options(state: GameState) -> List[Action]:
    """反乱(8.4.1): 未配置拠点の動物種と一致する支持広場。

    追加条件: 敵建物を全除去した後に拠点を置く枠があること。敵建物は
    すべて除去されるため、連合自身の建物数+遺跡 < slots で判定する。
    コスト: 一致する支援者2枚(鳥はワイルド)。
    """
    als = state.alliance()
    unplaced = [s.value for s in CLEARING_SUITS if s.value not in als.bases_placed]
    out: List[Action] = []
    for cs in state.clearings:
        cl = state.map.clearing(cs.cid)
        if cl.suit.value not in unplaced:
            continue
        if not cs.has_token(ALLIANCE, T_SYMPATHY):
            continue
        if state.placement_blocked(ALLIANCE, cs.cid):
            continue  # 城砦のある広場には拠点を配置できない(6.2.2, 防御的)
        own_after = len(cs.buildings_of(ALLIANCE)) + (1 if cs.ruin else 0)
        if own_after >= cl.slots:
            continue  # 敵建物除去後も拠点を置く枠がない
        if _supporter_payment(state, cl.suit, 2) is None:
            continue
        out.append(AllianceRevolt(player=ALLIANCE, clearing=cs.cid))
    return out


def _spread_options(state: GameState) -> List[Action]:
    """支持拡大(8.4.2): 支持広場に隣接する非支持広場(支持ゼロなら全非支持)。"""
    als = state.alliance()
    if als.placed_sympathy >= 10:
        return []
    supported = sympathetic_clearings(state)
    targets = set()
    if supported:
        for cid in supported:
            for nb in state.map.clearing(cid).adjacent:
                if not state.clearing(nb).has_token(ALLIANCE, T_SYMPATHY):
                    targets.add(nb)
    else:
        targets = {cs.cid for cs in state.clearings
                   if not cs.has_token(ALLIANCE, T_SYMPATHY)}
    out: List[Action] = []
    for cid in sorted(targets):
        if state.placement_blocked(ALLIANCE, cid):
            continue  # 城砦のある広場には支持トークンを配置できない(6.2.2)
        suit = state.map.clearing(cid).suit
        if _supporter_payment(state, suit, _spread_cost(state, cid)) is None:
            continue
        out.append(AllianceSpreadSympathy(player=ALLIANCE, clearing=cid))
    return out


def _mobilize_options(state: GameState) -> List[Action]:
    """動員(8.5.2): 手札のカードごと(動物種の制限なし)。"""
    out: List[Action] = []
    seen = set()
    for cid in state.alliance().hand:
        base = state.cards.base_id(cid)
        if base in seen:
            continue
        seen.add(base)
        out.append(AllianceMobilize(player=ALLIANCE, card_id=cid))
    return out


def _train_options(state: GameState) -> List[Action]:
    """訓練(8.5.3): 配置済み拠点の動物種と一致する手札(鳥ワイルド)。"""
    als = state.alliance()
    if als.soldiers_supply <= 0 or not als.bases_placed:
        return []
    base_suits = set(als.bases_placed)
    out: List[Action] = []
    seen = set()
    for cid in als.hand:
        s = state.cards.suit_of(cid)
        if s == Suit.BIRD or s.value in base_suits:
            base = state.cards.base_id(cid)
            if base in seen:
                continue
            seen.add(base)
            out.append(AllianceTrain(player=ALLIANCE, card_id=cid))
    return out


def _opmove_options(state: GameState) -> List[Action]:
    """作戦・移動(8.6.1.I, 4.2): 移動元か先を支配する自兵士の移動。"""
    out: List[Action] = []
    for cs in state.clearings:
        n = cs.soldier_count(ALLIANCE)
        if n <= 0:
            continue
        for dst in state.map.clearing(cs.cid).adjacent:
            if not (state.controls(ALLIANCE, cs.cid) or state.controls(ALLIANCE, dst)):
                continue
            for count in range(1, n + 1):
                out.append(AllianceOpMove(player=ALLIANCE, src=cs.cid, dst=dst, count=count))
    return out


def _opbattle_options(state: GameState) -> List[Action]:
    """作戦・戦闘(8.6.1.II, 4.3): 自兵士のいる戦場で敵1派閥へ宣言。"""
    from .vagabond import vagabond_in_clearing
    out: List[Action] = []
    for cs in state.clearings:
        if cs.soldier_count(ALLIANCE) <= 0:
            continue
        defenders = set()
        for f, n in cs.soldiers:
            if f != ALLIANCE and n > 0:
                defenders.add(f)
        for p in cs.buildings + cs.tokens:
            if p.faction != ALLIANCE:
                defenders.add(p.faction)
        # 放浪者コマも戦闘対象(9.2.2。放浪部族参戦時のみ)
        if vagabond_in_clearing(state, cs.cid):
            defenders.add(FactionId.VAGABOND)
        for d in sorted(defenders, key=lambda f: f.value):
            out.append(AllianceOpBattle(player=ALLIANCE, clearing=cs.cid, defender=d))
    return out


def _oprecruit_options(state: GameState) -> List[Action]:
    """作戦・募兵(8.6.1.III): 拠点のある広場に兵士1(サプライ>0)。"""
    if state.alliance().soldiers_supply <= 0:
        return []
    return [AllianceOpRecruit(player=ALLIANCE, clearing=cs.cid)
            for cs in state.clearings if has_base(cs)]


def _oporganize_options(state: GameState) -> List[Action]:
    """作戦・組織(8.6.1.IV): 非支持広場の自兵士1個を除去し支持トークン配置。"""
    if state.alliance().placed_sympathy >= 10:
        return []
    out: List[Action] = []
    for cs in state.clearings:
        if cs.has_token(ALLIANCE, T_SYMPATHY):
            continue
        if cs.soldier_count(ALLIANCE) <= 0:
            continue
        out.append(AllianceOpOrganize(player=ALLIANCE, clearing=cs.cid))
    return out


# ---------------- ロジック ----------------
class AllianceLogic(FactionLogic):
    faction = ALLIANCE

    def setup(self, state: GameState, rng) -> GameState:
        # 8.3.4 の支援者3枚は game.py が山札トップから直接配置する(3.9)。
        return state

    def begin_phase(self, state: GameState, rng) -> GameState:
        als = state.alliance()
        if state.phase == Phase.BIRDSONG:
            # 鳥歌(8.4)は反乱・支持拡大とも任意で強制処理なし。継続効果カードの
            # 1ターン1回使用済み(effects_used, 18.1)のみリセットする。
            return state.with_faction_state(dataclasses.replace(als, effects_used=()))
        if state.phase == Phase.DAYLIGHT:
            # クラフトツール(支持トークン)の起動記録をリセット(4.1.1)
            return state.with_faction_state(
                dataclasses.replace(als, used_sympathy_clearings=()))
        if state.phase == Phase.EVENING:
            # 作戦行動の進行状態をリセット(8.6)
            return state.with_faction_state(
                dataclasses.replace(als, ops_used=0, ops_done=False))
        return state

    def legal_actions(self, state: GameState) -> List[Action]:
        if state.phase == Phase.BIRDSONG:
            return self._birdsong_actions(state)
        if state.phase == Phase.DAYLIGHT:
            return self._daylight_actions(state)
        return self._evening_actions(state)

    def _birdsong_actions(self, state: GameState) -> List[Action]:
        """鳥歌(8.4): 反乱 + 支持拡大 + EndPhase(いずれも任意・望む回数)。"""
        acts: List[Action] = []
        acts.extend(_revolt_options(state))
        acts.extend(_spread_options(state))
        acts.append(EndPhase(player=ALLIANCE))
        return acts

    def _daylight_actions(self, state: GameState) -> List[Action]:
        """昼光(8.5): クラフト + 動員 + 訓練 + EndPhase(任意順・任意回数)。"""
        acts: List[Action] = []
        acts.extend(legal_crafts(state, ALLIANCE))  # 8.5.1
        acts.extend(_mobilize_options(state))       # 8.5.2
        acts.extend(_train_options(state))          # 8.5.3
        acts.append(EndPhase(player=ALLIANCE))
        return acts

    def _evening_actions(self, state: GameState) -> List[Action]:
        """夕闇(8.6): 作戦行動(指揮官数まで)→ 手札調整。"""
        als = state.alliance()
        if als.ops_done:
            return [EndPhase(player=ALLIANCE)]
        acts: List[Action] = []
        if als.ops_used < als.officers:
            acts.extend(_opmove_options(state))
            acts.extend(_opbattle_options(state))
            acts.extend(_oprecruit_options(state))
            acts.extend(_oporganize_options(state))
        acts.append(AllianceEndOps(player=ALLIANCE))
        return acts


# ---------------- アクション適用(apply.py から呼ばれる) ----------------
def _remove_all_enemies(state: GameState, cid: int) -> GameState:
    """広場の敵配置物をすべて除去する(8.4.1.III)。source=連合でVPが入る。"""
    from .. import battle as battle_mod
    cs = state.clearing(cid)
    removed_marquise = 0
    for f, n in list(cs.soldiers):
        if f == ALLIANCE:
            continue
        for _ in range(n):
            state = battle_mod.remove_piece(state, cid, f, ("soldier",), ALLIANCE)
            if f == FactionId.MARQUISE:
                removed_marquise += 1
    for p in list(state.clearing(cid).buildings):
        if p.faction == ALLIANCE:
            continue
        state = battle_mod.remove_piece(state, cid, p.faction, ("building", p.kind), ALLIANCE)
    for p in list(state.clearing(cid).tokens):
        if p.faction == ALLIANCE:
            continue
        state = battle_mod.remove_piece(state, cid, p.faction, ("token", p.kind), ALLIANCE)
    # 放浪者コマの広場が対象なら、コマは除去せずアイテム3損傷(9.2.2.I)。
    # 放浪部族不参加なら no-op(既存3派閥の挙動は不変)。
    from . import vagabond as vagabond_mod
    state = vagabond_mod.on_area_removal(state, cid)
    # 野戦病院(6.2.3): 反乱で猫兵士が除去されたイベントとして1回だけ判定する。
    # 除去兵士はサプライへ戻っており、病院発動で城砦広場へ取り出す。
    if removed_marquise > 0 and FactionId.MARQUISE in state.factions:
        from . import marquise as marquise_mod
        pushed = marquise_mod.maybe_field_hospital(state, cid, removed_marquise)
        if pushed is not None:
            state = pushed
    return state


def apply_revolt(state: GameState, action: AllianceRevolt, rng) -> GameState:
    """反乱(8.4.1): 支援者2枚(19.2 で選択化)→ 解決(_finish_revolt)。"""
    cid = action.clearing
    suit = state.map.clearing(cid).suit
    assert _supporter_payment(state, suit, 2) is not None, \
        "revolt without payable supporters"
    return _continue_supporter_payment(state, suit, 2, "revolt", cid, rng)


def apply_spend_supporter(state: GameState, action: AllianceSpendSupporter,
                          rng) -> GameState:
    """支援者1枚の支払い(19.2)。``SupporterPaymentDecision`` の応答。

    支払い後は _continue_supporter_payment に戻り、再push または完了処理へ。
    """
    dec = state.pending[-1]
    assert isinstance(dec, SupporterPaymentDecision)
    state = state.pop_pending()
    state = _pay_one_supporter(state, action.suit)
    return _continue_supporter_payment(
        state, dec.suit, dec.remaining - 1, dec.purpose, dec.clearing, rng)


def _finish_revolt(state: GameState, cid: int, rng) -> GameState:
    """反乱の解決(8.4.1): 敵全除去 → 拠点 → 兵士 → 指揮官1(支払い後, 19.2)。"""
    suit = state.map.clearing(cid).suit
    # 敵配置物の全除去(建物/トークン除去で1VPずつ, 3.2.1)
    state = _remove_all_enemies(state, cid)
    # 拠点タイル配置(動物種はこの広場の suit)
    state = state.with_clearing(state.clearing(cid).add_building(Piece(ALLIANCE, B_BASE)))
    als = state.alliance()
    state = state.with_faction_state(dataclasses.replace(
        als, bases_placed=als.bases_placed + (suit.value,)))
    # 兵士コマ = 拠点動物種と一致する支持広場の数(サプライ不足は可能な限り 1.5.4)
    n_sym = _matching_sympathy_count(state, suit)
    put = min(n_sym, state.alliance().soldiers_supply)
    if put > 0:
        state = state.with_clearing(state.clearing(cid).add_soldiers(ALLIANCE, put))
        als = state.alliance()
        state = state.with_faction_state(dataclasses.replace(
            als, soldiers_supply=als.soldiers_supply - put))
    # 最後にサプライ残があれば指揮官ボックスに兵士1個
    als = state.alliance()
    if als.soldiers_supply > 0:
        state = state.with_faction_state(dataclasses.replace(
            als, officers=als.officers + 1, soldiers_supply=als.soldiers_supply - 1))
    return state


def apply_spread(state: GameState, action: AllianceSpreadSympathy, rng) -> GameState:
    """支持拡大(8.4.2): 支援者(累進+戒厳令。19.2 で選択化)→ トークン配置+VP。"""
    cid = action.clearing
    suit = state.map.clearing(cid).suit
    cost = _spread_cost(state, cid)
    assert _supporter_payment(state, suit, cost) is not None, \
        "spread without payable supporters"
    return _continue_supporter_payment(state, suit, cost, "spread", cid, rng)


def apply_mobilize(state: GameState, action: AllianceMobilize, rng) -> GameState:
    """動員(8.5.2): 手札1枚 → 支援者ボックス(上限処理込み)。"""
    als = state.alliance()
    hand = list(als.hand)
    hand.remove(action.card_id)
    state = state.with_faction_state(dataclasses.replace(als, hand=tuple(hand)))
    return add_supporter(state, action.card_id)


def apply_train(state: GameState, action: AllianceTrain, rng) -> GameState:
    """訓練(8.5.3): 一致手札1枚を捨て、サプライ兵士1個 → 指揮官。"""
    from ..mechanics import discard_card
    state = discard_card(state, ALLIANCE, action.card_id)
    als = state.alliance()
    assert als.soldiers_supply > 0, "train without supply"
    return state.with_faction_state(dataclasses.replace(
        als, officers=als.officers + 1, soldiers_supply=als.soldiers_supply - 1))


def _spend_op(state: GameState) -> GameState:
    als = state.alliance()
    return state.with_faction_state(dataclasses.replace(als, ops_used=als.ops_used + 1))


def apply_op_move(state: GameState, action: AllianceOpMove, rng) -> GameState:
    """作戦・移動(8.6.1.I, 4.2)。連合自身の移動は蜂起(8.2.6)の対象外。"""
    src = state.clearing(action.src)
    assert src.soldier_count(ALLIANCE) >= action.count
    state = state.with_clearing(src.add_soldiers(ALLIANCE, -action.count))
    state = state.with_clearing(
        state.clearing(action.dst).add_soldiers(ALLIANCE, action.count))
    return _spend_op(state)


def apply_op_battle(state: GameState, action: AllianceOpBattle, rng) -> GameState:
    """作戦・戦闘(8.6.1.II)。戦闘機構(3.6)をそのまま使う。"""
    from .. import battle as battle_mod
    state = _spend_op(state)
    decl = DeclareBattle(player=ALLIANCE, clearing=action.clearing,
                         defender=action.defender)
    return battle_mod.declare_battle(state, decl, rng)


def apply_op_recruit(state: GameState, action: AllianceOpRecruit, rng) -> GameState:
    """作戦・募兵(8.6.1.III): 拠点広場に兵士1個。"""
    state = _spend_op(state)
    als = state.alliance()
    assert als.soldiers_supply > 0, "recruit without supply"
    state = state.with_clearing(
        state.clearing(action.clearing).add_soldiers(ALLIANCE, 1))
    als = state.alliance()
    return state.with_faction_state(dataclasses.replace(
        als, soldiers_supply=als.soldiers_supply - 1))


def apply_op_organize(state: GameState, action: AllianceOpOrganize, rng) -> GameState:
    """作戦・組織(8.6.1.IV): 自兵士1個除去 → 支持トークン配置+VP。"""
    state = _spend_op(state)
    cid = action.clearing
    state = state.with_clearing(state.clearing(cid).add_soldiers(ALLIANCE, -1))
    als = state.alliance()
    state = state.with_faction_state(dataclasses.replace(
        als, soldiers_supply=als.soldiers_supply + 1))
    return _place_sympathy(state, cid)


def apply_end_ops(state: GameState, action: AllianceEndOps, rng) -> GameState:
    """手札調整(8.6.2): (1+拠点数×アイコン)枚ドロー、6枚以上なら5枚へ。"""
    als = state.alliance()
    per = state.board_defs["alliance"]["base_card_icons_per_base"]
    draw = 1 + len(als.bases_placed) * per
    state = state.with_faction_state(dataclasses.replace(als, ops_done=True))
    state = draw_cards(state, ALLIANCE, draw, rng)
    if len(state.fs(ALLIANCE).hand) > 5:
        state = state.push_pending(DiscardDecision(actor=ALLIANCE))
    return state


def apply_outrage_pay(state: GameState, action: OutragePay, rng) -> GameState:
    """蜂起の支払い(8.2.6)。手札1枚 or 山札トップ1枚を支援者ボックスへ。"""
    assert isinstance(state.pending[-1], OutrageDecision)
    state = state.pop_pending()
    if action.card_id is None:
        # 一致カードなし → 山札トップ1枚を支援者ボックスへ(手札公開は no-op)
        deck = list(state.deck)
        discard = list(state.discard)
        if not deck:
            if not discard:
                return state  # 山札・捨て山とも空 → 補充不能(no-op)
            deck = discard
            discard = []
            rng.shuffle(deck)
        card = deck.pop()
        state = state.replace(deck=tuple(deck), discard=tuple(discard))
        return add_supporter(state, card)
    # 支払者の手札から支援者ボックスへ
    fs = state.fs(action.player)
    hand = list(fs.hand)
    hand.remove(action.card_id)
    state = state.with_faction_state(dataclasses.replace(fs, hand=tuple(hand)))
    return add_supporter(state, action.card_id)


def apply_discard_supporter(state: GameState, action: AllianceDiscardSupporter,
                            rng) -> GameState:
    """支援者5枚調整(8.2.4): 支援者1枚を捨て山へ。5枚以下でデシジョン解消。"""
    assert isinstance(state.pending[-1], SupportersLimitDecision)
    als = state.alliance()
    supporters = list(als.supporters)
    supporters.remove(action.card_id)
    state = state.with_faction_state(dataclasses.replace(als, supporters=tuple(supporters)))
    state = to_discard(state, action.card_id)  # 圧倒カードは盤脇へ(3.3.3/14.3)
    if len(state.alliance().supporters) <= 5:
        state = state.pop_pending()
    return state


register(AllianceLogic())
