"""鷲巣王朝(アイリー・ダイナスティ)ロジック(第7章)。

合法手生成・フェイズ開始処理・鷲巣固有アクションの適用を担う。
共通アクション(戦闘・移動・クラフト)の本体は engine 側にあり、
ここは「いつ・何回・どのコストで使えるか」を差す(DESIGN.md 3.4)。

勅令(7.5.2)は EyrieState.decree(4列のカードIDタプル)に蓄積され、
昼光の実行進行は decree_remaining で追跡する。実行不能な勅令が
出現したら内乱(7.7)。忠臣カードは擬似ID LOYAL_VIZIER(動物種=鳥)。
"""
from __future__ import annotations

import dataclasses
from typing import List, Optional

from ..actions import (
    Action,
    DeclareBattle,
    DiscardDecision,
    EndPhase,
    EyrieAddToDecree,
    EyrieChooseCorner,
    EyrieChooseLeader,
    EyrieDecreeBattle,
    EyrieDecreeBuild,
    EyrieDecreeDecision,
    EyrieDecreeMove,
    EyrieLeaderDecision,
    EyriePlaceRoost,
    EyrieRecruit,
    EyrieRoostDecision,
    EyrieSkipDecree,
    EyrieTurmoil,
)
from ..crafting import legal_crafts
from ..mechanics import draw_cards
from ..state import EyrieState, GameState
from ..types import (
    B_ROOST,
    Corner,
    EYRIE_LEADERS,
    FactionId,
    LOYAL_VIZIER,
    OPPOSITE_CORNER,
    Phase,
    Piece,
    Suit,
    T_KEEP,
)
from . import FactionLogic, register

EYRIE = FactionId.EYRIE

#: 勅令の列インデックス(7.5.2: 左から募兵→移動→戦闘→建設)
COL_RECRUIT, COL_MOVE, COL_BATTLE, COL_BUILD = 0, 1, 2, 3

#: 君主ごとの忠臣カード配置列(7.8)
VIZIER_COLUMNS = {
    "builder": (COL_RECRUIT, COL_MOVE),        # 7.8.1 建設者
    "charismatic": (COL_RECRUIT, COL_BATTLE),  # 7.8.2 カリスマ
    "commander": (COL_MOVE, COL_BATTLE),       # 7.8.3 司令官
    "despot": (COL_MOVE, COL_BUILD),           # 7.8.4 独裁者
}


# ---------------- ヘルパ ----------------
def card_suit(state: GameState, card_id: str) -> Suit:
    """勅令カードの動物種。忠臣カードは鳥(7.3.4)。"""
    if card_id == LOYAL_VIZIER:
        return Suit.BIRD
    return state.cards.suit_of(card_id)


def _matches(state: GameState, card_id: str, cid: int) -> bool:
    """勅令カードと広場の一致判定(2.2.2)。鳥はワイルド(2.1.1)。"""
    s = card_suit(state, card_id)
    return s == Suit.BIRD or s == state.map.clearing(cid).suit


def has_roost(cs) -> bool:
    return any(p.faction == EYRIE and p.kind == B_ROOST for p in cs.buildings)


def roost_clearings(state: GameState) -> List[int]:
    """マップ上で止まり木タイルのある広場ID一覧。"""
    return [cs.cid for cs in state.clearings if has_roost(cs)]


def _viziers_decree(leader: str):
    """忠臣2枚を君主の指定列に置いた勅令(7.3.4 / 7.7.3)。"""
    cols = [(), (), (), ()]
    for c in VIZIER_COLUMNS[leader]:
        cols[c] = (LOYAL_VIZIER,)
    return tuple(cols)


def visible_card_icons(state: GameState) -> int:
    """派閥ボード上に露出しているカードアイコン数(7.6.2)。

    アイコンは止まり木トラックの0-indexedスロット位置(boards.json)に
    あり、そのスロットのタイルがマップに出た時(=配置数がslot+1以上)に
    露出する。実物ボード確認済み: スロット2,5(3枚目・6枚目で+1ずつ)。
    """
    es = state.eyrie()
    slots = state.board_defs["eyrie"]["roost_card_icon_slots"]
    return sum(1 for v in slots if es.built_roosts >= v + 1)


def _current_column(es: EyrieState) -> Optional[int]:
    """未実行の勅令カードが残る最左の列(7.5.2)。全消化なら None。"""
    for col in range(4):
        if es.decree_remaining[col]:
            return col
    return None


# ---------------- デシジョンの選択肢(legal.py から呼ばれる) ----------------
def corner_options(state: GameState) -> List[Action]:
    """開始時広場の隅選択(7.3.2)。

    他プレイヤーの開始時広場(=猫の城砦トークンのある隅)があるなら、
    可能ならその対角。なければ空いている任意の隅。
    """
    taken: List[Corner] = []
    free: List[Corner] = []
    for corner in Corner:
        cid = state.map.corner_clearing(corner)
        if cid is None:
            continue
        if any(p.kind == T_KEEP for p in state.clearing(cid).tokens):
            taken.append(corner)
        else:
            free.append(corner)
    if taken:
        diagonals = [OPPOSITE_CORNER[c] for c in taken if OPPOSITE_CORNER[c] in free]
        if diagonals:
            return [EyrieChooseCorner(player=EYRIE, corner=c.value) for c in diagonals]
    return [EyrieChooseCorner(player=EYRIE, corner=c.value) for c in free]


def leader_options(state: GameState) -> List[Action]:
    """君主選択(7.3.3 / 7.7.3): 表向きの君主カードから1枚。"""
    es = state.eyrie()
    avail = [l for l in EYRIE_LEADERS
             if l not in es.used_leaders and l != es.leader]
    return [EyrieChooseLeader(player=EYRIE, leader=l) for l in avail]


def decree_add_options(state: GameState, dec: EyrieDecreeDecision) -> List[Action]:
    """勅令追加(7.4.2)の選択肢。2枚目は任意、鳥2枚同時は不可。"""
    es = state.eyrie()
    out: List[Action] = []
    if not dec.first:
        out.append(EyrieSkipDecree(player=EYRIE))
    seen = set()
    for cid in es.hand:
        base = state.cards.base_id(cid)
        if base in seen:
            continue
        seen.add(base)
        if (not dec.first) and dec.bird_added and state.cards.suit_of(cid) == Suit.BIRD:
            continue  # 鳥カード2枚の同時追加は不可(7.4.2)
        for col in range(4):
            out.append(EyrieAddToDecree(player=EYRIE, card_id=cid, column=col))
    return out


def roost_candidates(state: GameState) -> List[int]:
    """止まり木確保(7.4.3)の候補広場。

    空き建物枠のある広場(=止まり木を配置できる広場)のうち、
    全派閥合計の兵士コマ数が最少のもの。配置できない広場は選べない。
    候補なしならこのステップはスキップされる。
    """
    eligible = [cs.cid for cs in state.clearings
                if cs.occupied_slots() < state.map.clearing(cs.cid).slots]
    if not eligible:
        return []
    m = min(state.clearing(c).total_soldiers() for c in eligible)
    return [c for c in eligible if state.clearing(c).total_soldiers() == m]


def roost_options(state: GameState) -> List[Action]:
    return [EyriePlaceRoost(player=EYRIE, clearing=cid)
            for cid in roost_candidates(state)]


# ---------------- 勅令実行の選択肢(7.5.2) ----------------
def decree_options(state: GameState, es: EyrieState, col: int) -> List[Action]:
    """現在の列の勅令カード1枚ぶんの実行選択肢。空なら内乱(7.7)。"""
    out: List[Action] = []
    seen_suits = set()
    for card in es.decree_remaining[col]:
        suit = card_suit(state, card)
        if suit in seen_suits:
            continue  # 同一動物種のカードは選択肢が同一
        seen_suits.add(suit)
        if col == COL_RECRUIT:
            out.extend(_recruit_options(state, es, card))
        elif col == COL_MOVE:
            out.extend(_move_options(state, card))
        elif col == COL_BATTLE:
            out.extend(_battle_options(state, card))
        else:
            out.extend(_build_options(state, es, card))
    return out


def _recruit_options(state: GameState, es: EyrieState, card: str) -> List[Action]:
    """募兵(7.5.2.I): 止まり木があり一致する広場に兵士1(カリスマ2, 7.8.2)。

    サプライが必要数未満なら実行不能=内乱(公式裁定)。
    """
    need = 2 if es.leader == "charismatic" else 1
    if es.soldiers_supply < need:
        return []
    return [EyrieRecruit(player=EYRIE, card_id=card, clearing=cid)
            for cid in roost_clearings(state) if _matches(state, card, cid)]


def _move_options(state: GameState, card: str) -> List[Action]:
    """移動(7.5.2.II): 一致広場から自兵士1個以上を移動(4.2.1)。"""
    out: List[Action] = []
    for cs in state.clearings:
        n = cs.soldier_count(EYRIE)
        if n <= 0 or not _matches(state, card, cs.cid):
            continue
        for dst in state.map.clearing(cs.cid).adjacent:
            # 移動条件(4.2.1): 移動元か移動先を支配(森の王者 7.2.2 込み)
            if not (state.controls(EYRIE, cs.cid) or state.controls(EYRIE, dst)):
                continue
            for count in range(1, n + 1):
                out.append(EyrieDecreeMove(player=EYRIE, card_id=card,
                                           src=cs.cid, dst=dst, count=count))
    return out


def _battle_options(state: GameState, card: str) -> List[Action]:
    """戦闘(7.5.2.III): 一致広場を戦場に戦闘1回(4.3)。"""
    out: List[Action] = []
    for cs in state.clearings:
        if cs.soldier_count(EYRIE) <= 0 or not _matches(state, card, cs.cid):
            continue
        defenders = set()
        for f, n in cs.soldiers:
            if f != EYRIE and n > 0:
                defenders.add(f)
        for p in cs.buildings + cs.tokens:
            if p.faction != EYRIE:
                defenders.add(p.faction)
        for d in sorted(defenders, key=lambda f: f.value):
            out.append(EyrieDecreeBattle(player=EYRIE, card_id=card,
                                         clearing=cs.cid, defender=d))
    return out


def _build_options(state: GameState, es: EyrieState, card: str) -> List[Action]:
    """建設(7.5.2.IV): 一致する自分の支配下広場で止まり木未配置かつ空き枠。"""
    if es.built_roosts >= 7:
        return []  # 止まり木は総数7(7.3.5)
    out: List[Action] = []
    for cs in state.clearings:
        if not _matches(state, card, cs.cid):
            continue
        if has_roost(cs):
            continue  # 1広場1枚まで
        if cs.occupied_slots() >= state.map.clearing(cs.cid).slots:
            continue
        if not state.controls(EYRIE, cs.cid):
            continue
        out.append(EyrieDecreeBuild(player=EYRIE, card_id=card, clearing=cs.cid))
    return out


# ---------------- ロジック ----------------
class EyrieLogic(FactionLogic):
    faction = EYRIE

    def setup(self, state: GameState, rng) -> GameState:
        # セットアップ選択(7.3.2 隅 / 7.3.3 君主)は game.py が Decision と
        # して積む(3.9)。ここでの追加処理はない。
        return state

    # -- フェイズ開始の強制処理 --
    def begin_phase(self, state: GameState, rng) -> GameState:
        if state.phase == Phase.BIRDSONG:
            return self._birdsong(state, rng)
        if state.phase == Phase.DAYLIGHT:
            es = state.eyrie()
            return state.with_faction_state(dataclasses.replace(
                es, decree_remaining=es.decree, decree_started=False,
                used_roost_clearings=()))
        if state.phase == Phase.EVENING:
            return self._evening(state, rng)
        return state

    def _birdsong(self, state: GameState, rng) -> GameState:
        """鳥歌(7.4): 緊急命令→勅令追加→止まり木確保。"""
        # 7.4.1 緊急命令: 手札がないなら1ドロー
        if not state.eyrie().hand:
            state = draw_cards(state, EYRIE, 1, rng)
        decisions = []
        # 7.4.2 勅令追加(1〜2枚, 強制)。山札切れで手札0なら追加不能
        if state.eyrie().hand:
            decisions.append(EyrieDecreeDecision(actor=EYRIE, first=True))
        # 7.4.3 止まり木確保: マップに止まり木0なら復帰(候補なしはスキップ)
        if state.eyrie().built_roosts == 0 and roost_candidates(state):
            decisions.append(EyrieRoostDecision(actor=EYRIE))
        if decisions:
            state = state.push_pending(*decisions)
        return state

    def _evening(self, state: GameState, rng) -> GameState:
        """夕闇(7.6): VP獲得→ドロー→手札調整。"""
        es = state.eyrie()
        # 7.6.1 VP獲得: 止まり木エリア最右空き枠 = roost_vp[マップ上の枚数-1]
        if es.built_roosts > 0:
            vp = state.board_defs["eyrie"]["roost_vp"][es.built_roosts - 1]
            state = state.with_faction_state(dataclasses.replace(es, vp=es.vp + vp))
        # 7.6.2 ドロー(1+露出アイコン数)、手札6枚以上なら5枚に
        state = draw_cards(state, EYRIE, 1 + visible_card_icons(state), rng)
        if len(state.fs(EYRIE).hand) > 5:
            state = state.push_pending(DiscardDecision(actor=EYRIE))
        return state

    # -- 合法手 --
    def legal_actions(self, state: GameState) -> List[Action]:
        if state.phase in (Phase.BIRDSONG, Phase.EVENING):
            return [EndPhase(player=EYRIE)]
        return self._daylight_actions(state)

    def _daylight_actions(self, state: GameState) -> List[Action]:
        """昼光(7.5): クラフト(勅令実行前のみ)→勅令解決。"""
        es = state.eyrie()
        acts: List[Action] = []
        if not es.decree_started:
            acts.extend(legal_crafts(state, EYRIE))  # 7.5.1
        col = _current_column(es)
        if col is None:
            acts.append(EndPhase(player=EYRIE))  # 勅令完遂
            return acts
        opts = decree_options(state, es, col)
        if opts:
            acts.extend(opts)
        else:
            # 残りカードのどれも実行不能 → 内乱(7.5.2 / 7.7)
            acts.append(EyrieTurmoil(player=EYRIE))
        return acts


# ---------------- アクション適用(apply.py から呼ばれる) ----------------
def apply_choose_corner(state: GameState, action: EyrieChooseCorner, rng) -> GameState:
    """開始時配置(7.3.2): 隅の広場に止まり木1+兵士6。"""
    state = state.pop_pending()
    cid = state.map.corner_clearing(Corner(action.corner))
    assert cid is not None
    cs = state.clearing(cid).add_building(Piece(EYRIE, B_ROOST)).add_soldiers(EYRIE, 6)
    state = state.with_clearing(cs)
    es = state.eyrie()
    return state.with_faction_state(dataclasses.replace(
        es, soldiers_supply=es.soldiers_supply - 6, built_roosts=1))


def apply_choose_leader(state: GameState, action: EyrieChooseLeader, rng) -> GameState:
    """君主選択(7.3.3 / 7.7.3)+忠臣カードの配置替え(7.3.4)。

    内乱由来(turmoil=True)なら選択後に休止(7.7.4): 昼光を即終了し
    夕闇フェイズを開始する。
    """
    dec = state.pending[-1]
    assert isinstance(dec, EyrieLeaderDecision)
    state = state.pop_pending()
    es = state.eyrie()
    es = dataclasses.replace(es, leader=action.leader,
                             decree=_viziers_decree(action.leader),
                             decree_remaining=((), (), (), ()))
    state = state.with_faction_state(es)
    if dec.turmoil:
        state = state.replace(phase=Phase.EVENING)
        from . import get_logic
        state = get_logic(EYRIE).begin_phase(state, rng)
    return state


def apply_add_to_decree(state: GameState, action: EyrieAddToDecree, rng) -> GameState:
    """勅令追加(7.4.2)。カードは手札から勅令列へ(捨て山を経由しない)。"""
    dec = state.pending[-1]
    assert isinstance(dec, EyrieDecreeDecision)
    state = state.pop_pending()
    es = state.eyrie()
    hand = list(es.hand)
    hand.remove(action.card_id)
    cols = list(es.decree)
    cols[action.column] = cols[action.column] + (action.card_id,)
    es = dataclasses.replace(es, hand=tuple(hand), decree=tuple(cols))
    state = state.with_faction_state(es)
    if dec.first and es.hand:
        is_bird = state.cards.suit_of(action.card_id) == Suit.BIRD
        state = state.push_pending(EyrieDecreeDecision(
            actor=EYRIE, first=False, bird_added=is_bird))
    return state


def apply_skip_decree(state: GameState, action: EyrieSkipDecree, rng) -> GameState:
    """2枚目の勅令追加をしない(7.4.2)。"""
    assert isinstance(state.pending[-1], EyrieDecreeDecision)
    return state.pop_pending()


def apply_place_roost(state: GameState, action: EyriePlaceRoost, rng) -> GameState:
    """止まり木確保(7.4.3): 止まり木1+兵士3(サプライ不足は可能な限り, 1.5.4)。"""
    assert isinstance(state.pending[-1], EyrieRoostDecision)
    state = state.pop_pending()
    es = state.eyrie()
    put = min(3, es.soldiers_supply)
    cs = state.clearing(action.clearing)
    cs = cs.add_building(Piece(EYRIE, B_ROOST)).add_soldiers(EYRIE, put)
    state = state.with_clearing(cs)
    es = state.eyrie()
    return state.with_faction_state(dataclasses.replace(
        es, soldiers_supply=es.soldiers_supply - put,
        built_roosts=es.built_roosts + 1))


def _consume(state: GameState, col: int, card_id: str) -> GameState:
    """勅令カード1枚を実行済みにする(decree 本体には残る)。"""
    es = state.eyrie()
    cols = list(es.decree_remaining)
    cards = list(cols[col])
    cards.remove(card_id)
    cols[col] = tuple(cards)
    es = dataclasses.replace(es, decree_remaining=tuple(cols), decree_started=True)
    return state.with_faction_state(es)


def apply_decree_recruit(state: GameState, action: EyrieRecruit, rng) -> GameState:
    """募兵(7.5.2.I)。カリスマは兵士2個(7.8.2)。"""
    state = _consume(state, COL_RECRUIT, action.card_id)
    es = state.eyrie()
    n = 2 if es.leader == "charismatic" else 1
    assert es.soldiers_supply >= n, "recruit without supply must be turmoil"
    state = state.with_clearing(state.clearing(action.clearing).add_soldiers(EYRIE, n))
    es = state.eyrie()
    return state.with_faction_state(dataclasses.replace(
        es, soldiers_supply=es.soldiers_supply - n))


def apply_decree_move(state: GameState, action: EyrieDecreeMove, rng) -> GameState:
    """移動(7.5.2.II, 4.2)。"""
    state = _consume(state, COL_MOVE, action.card_id)
    src = state.clearing(action.src)
    assert src.soldier_count(EYRIE) >= action.count
    state = state.with_clearing(src.add_soldiers(EYRIE, -action.count))
    state = state.with_clearing(
        state.clearing(action.dst).add_soldiers(EYRIE, action.count))
    return state


def apply_decree_battle(state: GameState, action: EyrieDecreeBattle, rng) -> GameState:
    """戦闘(7.5.2.III)。既存の戦闘 pending 機構(3.6)をそのまま使う。

    戦闘解決中は勅令進行が自然に中断され、pending が空になれば再開する。
    """
    from .. import battle as battle_mod
    state = _consume(state, COL_BATTLE, action.card_id)
    decl = DeclareBattle(player=EYRIE, clearing=action.clearing,
                         defender=action.defender)
    return battle_mod.declare_battle(state, decl, rng)


def apply_decree_build(state: GameState, action: EyrieDecreeBuild, rng) -> GameState:
    """建設(7.5.2.IV): 止まり木タイル1枚を配置。"""
    state = _consume(state, COL_BUILD, action.card_id)
    cs = state.clearing(action.clearing).add_building(Piece(EYRIE, B_ROOST))
    state = state.with_clearing(cs)
    es = state.eyrie()
    return state.with_faction_state(dataclasses.replace(
        es, built_roosts=es.built_roosts + 1))


def apply_turmoil(state: GameState, action: EyrieTurmoil, rng) -> GameState:
    """内乱(7.7): 恥辱→追放→失脚(Decision)→休止(君主選択後)。"""
    es = state.eyrie()
    # 7.7.1 恥辱: 勅令内の鳥カード枚数(忠臣2枚含む)ぶんVP喪失。0未満不可
    birds = sum(1 for col in es.decree for c in col
                if card_suit(state, c) == Suit.BIRD)
    vp = max(0, es.vp - birds)
    # 7.7.2 追放: 忠臣カード以外の全勅令カードを捨て山へ
    purged = tuple(c for col in es.decree for c in col if c != LOYAL_VIZIER)
    # 7.7.3 失脚: 現君主を裏向きに。全裏なら全表に戻す(7.7.3.I 新世代)
    used = es.used_leaders + ((es.leader,) if es.leader else ())
    if len(used) >= len(EYRIE_LEADERS):
        used = ()
    es = dataclasses.replace(es, vp=vp, leader=None, used_leaders=used,
                             decree=((), (), (), ()),
                             decree_remaining=((), (), (), ()))
    state = state.with_faction_state(es).replace(discard=state.discard + purged)
    # 君主交代の選択(7.7.3)。選択の適用時に休止(7.7.4)で夕闇へ
    return state.push_pending(EyrieLeaderDecision(actor=EYRIE, turmoil=True))


register(EyrieLogic())
