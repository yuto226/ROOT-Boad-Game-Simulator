"""猫野侯国(マーキス・ド・キャット)ロジック(第6章)。

合法手生成とフェイズ開始処理を担う。共通アクション(戦闘・移動・
クラフト)の本体は engine 側にあり、ここは「いつ・何回・どのコストで
使えるか」を差す(3.4)。
"""
from __future__ import annotations

import dataclasses
from typing import List, Set

from ..actions import (
    Action,
    CraftCard,
    DeclareBattle,
    DiscardDecision,
    EndPhase,
    FieldHospitalDecision,
    MarquiseBuild,
    MarquiseChooseWood,
    MarquiseFieldHospital,
    MarquiseLabor,
    MarquiseMarch,
    MarquisePlayBirdCard,
    MarquiseRecruit,
    MarquiseSkipMove,
)
from ..crafting import legal_crafts
from ..mechanics import draw_cards
from ..state import ClearingState, GameState, MarquiseState
from ..types import (
    B_RECRUITER,
    B_SAWMILL,
    B_WORKSHOP,
    FactionId,
    MARQUISE_BUILDINGS,
    Phase,
    Piece,
    Suit,
    T_KEEP,
    T_WOOD,
)
from . import FactionLogic, register

MARQUISE = FactionId.MARQUISE


# ---------------- ヘルパ ----------------
def building_clearings(state: GameState, kind: str) -> List[int]:
    """マップ上で当該種の猫の建物がある広場ID一覧。"""
    out = []
    for cs in state.clearings:
        for p in cs.buildings:
            if p.faction == MARQUISE and p.kind == kind:
                out.append(cs.cid)
    return out


def connected_controlled(state: GameState, clearing: int) -> Set[int]:
    """建設広場から連結の支配下広場の集合(6.5.4.II)。

    建設広場自身 + 「道および自分の支配下広場」で接続した支配下広場群。
    建設広場を支配していなければ空集合。
    """
    if not state.controls(MARQUISE, clearing):
        return set()
    visited: Set[int] = {clearing}
    frontier = [clearing]
    while frontier:
        cur = frontier.pop()
        for nb in state.map.clearing(cur).adjacent:
            if nb in visited:
                continue
            if state.controls(MARQUISE, nb):
                visited.add(nb)
                frontier.append(nb)
    return visited


def reachable_wood(state: GameState, clearing: int) -> int:
    """建設広場から使える木材トークン総数(6.5.4.II)。"""
    return sum(state.clearing(c).wood_count(MARQUISE)
               for c in connected_controlled(state, clearing))


def wood_payment_options(state: GameState, dec) -> List[Action]:
    """木材支払いの候補広場(6.5.4.II, 19.1)。

    建設広場から連結の支配下広場(既存 BFS と同じ集合)のうち木材が1個以上
    ある広場。支配は兵士+建物で決まり木材(トークン)除去では変わらないため、
    支払い途中で eligibility(連結・支配)は変化しない。cid 昇順で決定的。
    """
    cids = connected_controlled(state, dec.build_clearing)
    return [MarquiseChooseWood(player=MARQUISE, clearing=c)
            for c in sorted(cids)
            if state.clearing(c).wood_count(MARQUISE) > 0]


def visible_card_icons(state: GameState) -> int:
    """派閥ボード上に見えているカードアイコン数(6.6)。

    アイコンはトラックの0-indexedスロット位置(boards.json)にあり、
    そのスロットのタイルがマップに出た時(=配置数がslot+1以上)に露出する。
    実物ボード確認済み: 募兵所スロット2,4(3枚目・5枚目の配置で+1ずつ)。
    """
    ms = state.marquise()
    slots = state.board_defs["marquise"]["card_icon_slots"].get("recruiter", [])
    built = ms.built_recruiter
    return sum(1 for v in slots if built >= v + 1)


# ---------------- 行軍(6.5.2, 2移動まで) ----------------
def _march_moves(state: GameState) -> List[Action]:
    """行軍の1移動ぶんの候補(4.2.1: 移動元か移動先を支配)。"""
    out: List[Action] = []
    for cs in state.clearings:
        n = cs.soldier_count(MARQUISE)
        if n <= 0:
            continue
        src = cs.cid
        for dst in state.map.clearing(src).adjacent:
            if not (state.controls(MARQUISE, src) or state.controls(MARQUISE, dst)):
                continue
            for count in range(1, n + 1):
                out.append(MarquiseMarch(player=MARQUISE, src=src, dst=dst, count=count))
    return out


def march_decision_options(state: GameState) -> List[Action]:
    """行軍の2移動目の選択肢(6.5.2)。移動候補 + スキップ。

    候補ゼロでもスキップがあるため詰まらない(DESIGN.md 15.2)。
    """
    return _march_moves(state) + [MarquiseSkipMove(player=MARQUISE)]


# ---------------- 野戦病院(6.2.3) ----------------
def _keep_clearing(state: GameState) -> int:
    """城砦トークンがマップ上にある広場ID(なければ -1)。"""
    for cs in state.clearings:
        if cs.has_token(MARQUISE, T_KEEP):
            return cs.cid
    return -1


def _hospital_cards(state: GameState, clearing: int) -> List[str]:
    """除去元広場と一致する手札カード(鳥=ワイルド 2.1.1)を base_id で dedup。"""
    suit = state.map.clearing(clearing).suit
    out: List[str] = []
    seen = set()
    for cid in state.marquise().hand:
        cs_suit = state.cards.suit_of(cid)
        if cs_suit != suit and cs_suit != Suit.BIRD:
            continue
        base = state.cards.base_id(cid)
        if base in seen:
            continue
        seen.add(base)
        out.append(cid)
    return out


def maybe_field_hospital(state: GameState, clearing: int, count: int,
                         ctx=None, roll_after: bool = False):
    """野戦病院(6.2.3)の発動判定。

    城砦がマップ上にあり、除去元広場と一致するカードが手札にあるときだけ
    ``FieldHospitalDecision`` を積んだ新しい状態を返す。前提を満たさなければ
    ``None`` を返す(呼び元が roll_after を処理する)。
    """
    if _keep_clearing(state) < 0:
        return None
    if not _hospital_cards(state, clearing):
        return None
    return state.push_pending(FieldHospitalDecision(
        actor=MARQUISE, clearing=clearing, count=count,
        ctx=ctx, roll_after=roll_after))


def field_hospital_options(state: GameState,
                           dec: FieldHospitalDecision) -> List[Action]:
    """野戦病院の選択肢(6.2.3)。使わない(None)+ 一致カード各種。

    デシジョンが積まれた後に城砦が除去され得る(Favor 18.2 は複数広場を順に
    処理するため、先の広場の病院デシジョンが残ったまま後の広場で城砦が除去
    されることがある)。城砦がマップにないときは「使わない」のみを返す。
    """
    out: List[Action] = [MarquiseFieldHospital(player=MARQUISE, card_id=None)]
    if _keep_clearing(state) < 0:
        return out
    for cid in _hospital_cards(state, dec.clearing):
        out.append(MarquiseFieldHospital(player=MARQUISE, card_id=cid))
    return out


# ---------------- ロジック ----------------
class MarquiseLogic(FactionLogic):
    faction = MARQUISE

    # -- フェイズ開始の強制処理 --
    def begin_phase(self, state: GameState, rng) -> GameState:
        if state.phase == Phase.BIRDSONG:
            state = self._birdsong(state)
            # 継続効果カードの1ターン1回使用済み(effects_used, 18.1)をリセット。
            return state.with_faction_state(dataclasses.replace(
                state.marquise(), effects_used=()))
        if state.phase == Phase.DAYLIGHT:
            ms = state.marquise()
            return state.with_faction_state(dataclasses.replace(
                ms, actions_left=3, recruited_this_turn=False, workshop_used=False))
        if state.phase == Phase.EVENING:
            return self._evening(state, rng)
        return state

    def _birdsong(self, state: GameState) -> GameState:
        """製材所1枚につき木材1配置(6.4)。サプライ不足なら可能な限り。"""
        ms = state.marquise()
        wood = ms.wood_supply
        for cid in building_clearings(state, B_SAWMILL):
            if wood <= 0:
                break
            cs = state.clearing(cid)
            cs = cs.add_token(Piece(MARQUISE, T_WOOD))
            state = state.with_clearing(cs)
            wood -= 1
        return state.with_faction_state(dataclasses.replace(state.marquise(), wood_supply=wood))

    def _evening(self, state: GameState, rng) -> GameState:
        """ドロー(1+アイコン)+手札5枚調整(6.6)。"""
        n = 1 + visible_card_icons(state)
        state = draw_cards(state, MARQUISE, n, rng)
        if len(state.fs(MARQUISE).hand) > 5:
            state = state.push_pending(DiscardDecision(actor=MARQUISE))
        return state

    # -- 合法手 --
    def legal_actions(self, state: GameState) -> List[Action]:
        if state.phase == Phase.BIRDSONG:
            return [EndPhase(player=MARQUISE)]
        if state.phase == Phase.EVENING:
            return [EndPhase(player=MARQUISE)]
        return self._daylight_actions(state)

    def _daylight_actions(self, state: GameState) -> List[Action]:
        ms = state.marquise()
        acts: List[Action] = []

        # クラフト(アクション回数を消費しない, 6.5)
        acts.extend(legal_crafts(state, MARQUISE))

        if ms.actions_left > 0:
            acts.extend(self._build_actions(state, ms))
            acts.extend(self._recruit_actions(state, ms))
            acts.extend(self._march_actions(state))
            acts.extend(self._labor_actions(state))
            acts.extend(self._battle_actions(state))
        else:
            # 3アクション後: 鳥カード消費で追加アクション(6.5)
            for cid in ms.hand:
                if state.cards.suit_of(cid) == Suit.BIRD:
                    acts.append(MarquisePlayBirdCard(player=MARQUISE, card_id=cid))

        acts.append(EndPhase(player=MARQUISE))
        return acts

    def _build_actions(self, state: GameState, ms: MarquiseState) -> List[Action]:
        costs = state.board_defs["marquise"]["building_costs"]
        out: List[Action] = []
        for cs in state.clearings:
            cl = state.map.clearing(cs.cid)
            if cs.occupied_slots() >= cl.slots:
                continue
            if not state.controls(MARQUISE, cs.cid):
                continue
            avail_wood = reachable_wood(state, cs.cid)
            for kind in MARQUISE_BUILDINGS:
                bc = ms.built_count(kind)
                if bc >= 6:
                    continue
                if avail_wood >= costs[bc]:
                    out.append(MarquiseBuild(player=MARQUISE, clearing=cs.cid, kind=kind))
        return out

    def _recruit_actions(self, state: GameState, ms: MarquiseState) -> List[Action]:
        if ms.recruited_this_turn:
            return []
        if ms.soldiers_supply <= 0:
            return []
        if not building_clearings(state, B_RECRUITER):
            return []
        return [MarquiseRecruit(player=MARQUISE)]

    def _march_actions(self, state: GameState) -> List[Action]:
        # 1移動目の候補(6.5.2)。2移動目は MarquiseMarchDecision 経由(15.2)。
        return _march_moves(state)

    def _labor_actions(self, state: GameState) -> List[Action]:
        out: List[Action] = []
        ms = state.marquise()
        if ms.wood_supply <= 0:
            return out
        hand = ms.hand
        for cid in building_clearings(state, B_SAWMILL):
            suit = state.map.clearing(cid).suit
            for card in hand:
                cs_suit = state.cards.suit_of(card)
                if cs_suit == suit or cs_suit == Suit.BIRD:
                    out.append(MarquiseLabor(player=MARQUISE, clearing=cid, card_id=card))
        return out

    def _battle_actions(self, state: GameState) -> List[Action]:
        from .vagabond import vagabond_in_clearing
        out: List[Action] = []
        for cs in state.clearings:
            if cs.soldier_count(MARQUISE) <= 0:
                continue
            defenders = set()
            for f, n in cs.soldiers:
                if f != MARQUISE and n > 0:
                    defenders.add(f)
            for p in cs.buildings + cs.tokens:
                if p.faction != MARQUISE:
                    defenders.add(p.faction)
            # 放浪者コマも戦闘対象(9.2.2。放浪部族参戦時のみ)
            if vagabond_in_clearing(state, cs.cid):
                defenders.add(FactionId.VAGABOND)
            for d in sorted(defenders, key=lambda f: f.value):
                out.append(DeclareBattle(player=MARQUISE, clearing=cs.cid, defender=d))
        return out


register(MarquiseLogic())
