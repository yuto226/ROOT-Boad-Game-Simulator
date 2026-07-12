"""猫野侯国(マーキス・ド・キャット)のテスト(DESIGN.md 9.3 test_marquise.py)。

selftest.py の書き方(状態の手動構築 → apply → pending解決)を踏襲する。
selftest.py / engine/factions/marquise.py 自体は変更しない。
"""
from __future__ import annotations

import dataclasses

import pytest

from engine.actions import (
    AllianceOpMove,
    AllianceSpreadSympathy,
    MarquiseBuild,
    MarquiseRecruit,
)
from engine.apply import apply
from engine.factions import get_logic
from engine.types import (
    B_RECRUITER,
    B_SAWMILL,
    FactionId,
    Phase,
    Piece,
    T_KEEP,
    T_WOOD,
)

from conftest import assert_illegal, assert_legal, make_state, put

M = FactionId.MARQUISE
E = FactionId.EYRIE
A = FactionId.ALLIANCE


def _clear(state, cid: int):
    """広場 cid の駒(兵士・建物・トークン)をすべて取り除く(ruinは保持)。"""
    cs = dataclasses.replace(state.clearing(cid), soldiers=(), buildings=(), tokens=())
    return state.with_clearing(cs)


def _ready_daylight(state):
    """建設/募兵の合法判定に必要な最低条件(昼光フェイズ・行動回数3)を整える。"""
    state = state.replace(phase=Phase.DAYLIGHT)
    ms = state.marquise()
    return state.with_faction_state(dataclasses.replace(ms, actions_left=3))


# ---------------- 1. 建設の合法/違法(6.5.2 / 6.5.4.II) ----------------
def test_build_legal_iff_enough_connected_wood():
    """建設 6.5.2/6.5.4.II: 支配広場+空き枠+連結木材が足りれば合法、木材不足なら違法。"""
    state, rng = make_state((M, E))
    state = _ready_daylight(state)
    # セットアップで既にsawmillが1棟建っている(built_sawmill=1) → 次の1棟のコスト
    n = state.marquise().built_sawmill
    cost = state.board_defs["marquise"]["building_costs"][n]
    assert cost >= 1, "2棟目の製材所コストは1以上のはず(boards.json)"

    cid = 2  # 空き枠(slots=2)のある広場。セットアップの建物配置(0,1)とは無関係
    state = _clear(state, cid)
    state = put(state, cid, soldiers={M: 1})  # cid を支配

    # 木材0個: 違法
    assert_illegal(state, MarquiseBuild(player=M, clearing=cid, kind="sawmill"))

    # 連結木材をコスト分置くと合法になる
    for _ in range(cost):
        state = state.with_clearing(state.clearing(cid).add_token(Piece(M, T_WOOD)))
    assert_legal(state, MarquiseBuild(player=M, clearing=cid, kind="sawmill"))


# ---------------- 2. 建設の適用: 木材消費+印刷VP(6.5.4.III) ----------------
def test_build_consumes_wood_and_awards_printed_vp():
    """建設: 建設後に木材トークンが消費され、boards.jsonの印刷値どおりVPが入る。

    木材支払いは WoodPaymentDecision で1個ずつ選択化された(19.1)。木材の
    ある広場が1つだけなら候補は毎回1つ=単一選択の自動適用(3.2)相当なので、
    legal_actions[0] で解決する。
    """
    from engine.legal import legal_actions

    state, rng = make_state((M, E))
    state = _ready_daylight(state)
    n = state.marquise().built_sawmill
    cost = state.board_defs["marquise"]["building_costs"][n]
    vp = state.board_defs["marquise"]["building_vp"]["sawmill"][n]

    cid = 2
    state = _clear(state, cid)
    state = put(state, cid, soldiers={M: 1})
    for _ in range(cost):
        state = state.with_clearing(state.clearing(cid).add_token(Piece(M, T_WOOD)))

    wood_supply_before = state.marquise().wood_supply
    vp_before = state.marquise().vp

    state = apply(state, MarquiseBuild(player=M, clearing=cid, kind="sawmill"), rng)
    while state.pending:  # 木材支払い(19.1)。候補は cid のみ=毎回1択
        acts = legal_actions(state)
        assert len(acts) == 1, "単一の木材広場なら支払い候補は毎回1つ: %r" % acts
        state = apply(state, acts[0], rng)

    assert state.clearing(cid).wood_count(M) == 0, "連結木材が支払いで消費される"
    assert state.marquise().wood_supply == wood_supply_before + cost, (
        "除去した木材はサプライへ還元される(3.5)")
    assert state.marquise().vp == vp_before + vp, "boards.json の印刷VPが入るはず"
    assert state.marquise().built_sawmill == n + 1


# ---------------- 3. 木こり(製材所の木材生産, 6.4) ----------------
def test_sawmills_place_wood_up_to_supply_limit():
    """木こり 6.4: 製材所のある広場に鳥歌フェイズで木材が置かれる(サプライ上限まで)。"""
    state, rng = make_state((M, E))
    # デフォルトセットアップで既に sawmill が広場0にある(6.3.4)。もう1棟を
    # 別の被支配広場(2)に手動配置し、複数製材所がある状況を作る。
    state = put(state, 2, buildings=[Piece(M, B_SAWMILL)])
    ms = state.marquise()
    state = state.with_faction_state(dataclasses.replace(ms, wood_supply=1))

    assert state.phase == Phase.BIRDSONG
    state = get_logic(M).begin_phase(state, rng)

    # サプライ1個のみ → cid昇順で先に処理される広場0にのみ配置され、2には置けない
    assert state.clearing(0).wood_count(M) == 1
    assert state.clearing(2).wood_count(M) == 0, "サプライ枯渇で2つ目の製材所には置けない"
    assert state.marquise().wood_supply == 0


# ---------------- 4. 徴兵(6.5.3) ----------------
def test_recruit_places_soldiers_at_all_recruiter_clearings():
    """徴兵 6.5.3: 募兵所のある広場すべてに兵士1体ずつ配置される。"""
    state, rng = make_state((M, E))
    state = _ready_daylight(state)
    # デフォルトセットアップで既に recruiter が広場1にある(6.3.4)。2つ目を追加。
    state = put(state, 2, buildings=[Piece(M, B_RECRUITER)])
    ms = state.marquise()
    state = state.with_faction_state(dataclasses.replace(ms, recruited_this_turn=False))

    recruiter_cids = sorted(
        cs.cid for cs in state.clearings
        if any(p.faction == M and p.kind == B_RECRUITER for p in cs.buildings))
    assert recruiter_cids == [1, 2]
    before = {cid: state.clearing(cid).soldier_count(M) for cid in recruiter_cids}
    before_supply = state.marquise().soldiers_supply

    assert_legal(state, MarquiseRecruit(player=M))
    state = apply(state, MarquiseRecruit(player=M), rng)

    for cid in recruiter_cids:
        assert state.clearing(cid).soldier_count(M) == before[cid] + 1
    assert state.marquise().soldiers_supply == before_supply - len(recruiter_cids)
    assert state.marquise().recruited_this_turn is True


def test_recruit_partial_placement_when_supply_insufficient():
    """徴兵 6.5.3/1.5.4: サプライ不足時は可能な限り配置する(全滅ではなく部分適用)。"""
    state, rng = make_state((M, E))
    state = _ready_daylight(state)
    state = put(state, 2, buildings=[Piece(M, B_RECRUITER)])
    ms = state.marquise()
    state = state.with_faction_state(dataclasses.replace(
        ms, recruited_this_turn=False, soldiers_supply=1))

    before_1 = state.clearing(1).soldier_count(M)
    before_2 = state.clearing(2).soldier_count(M)

    state = apply(state, MarquiseRecruit(player=M), rng)

    # サプライ1体分のみ配置される(cid昇順で広場1が先に処理される)
    assert state.clearing(1).soldier_count(M) == before_1 + 1
    assert state.clearing(2).soldier_count(M) == before_2
    assert state.marquise().soldiers_supply == 0


# ---------------- 5. 城砦(6.2.1/6.2.2) ----------------
def test_keep_clearing_blocks_sympathy_placement():
    """城砦 6.2.2: 城砦広場への支持拡大(配置)は他派閥にとって非合法。"""
    state, rng = make_state((M, A))
    state = state.replace(turn_index=state.factions.index(A))  # 鳥歌(8.4)は連合の手番
    keep_cid = next(
        cs.cid for cs in state.clearings
        if any(p.faction == M and p.kind == T_KEEP for p in cs.tokens))
    suit = state.map.clearing(keep_cid).suit
    cost = state.board_defs["alliance"]["sympathy_costs"][0]
    cards = [d.id for d in state.cards.defs if not d.is_dominance and d.suit == suit][:cost]
    assert len(cards) >= cost

    als = state.alliance()
    state = state.with_faction_state(dataclasses.replace(
        als, placed_sympathy=0, supporters=tuple(cards)))

    action = AllianceSpreadSympathy(player=A, clearing=keep_cid)
    assert_illegal(state, action)


def test_keep_clearing_allows_enemy_movement():
    """城砦 6.2.2: 城砦広場への移動そのものは合法(「そこへ移動させることは可能」)。"""
    state, rng = make_state((M, A))
    keep_cid = next(
        cs.cid for cs in state.clearings
        if any(p.faction == M and p.kind == T_KEEP for p in cs.tokens))
    adj_cid = state.map.clearing(keep_cid).adjacent[0]

    state = _clear(state, adj_cid)
    state = put(state, adj_cid, soldiers={A: 2})  # Aがadj_cidを支配

    als = state.alliance()
    state = state.with_faction_state(dataclasses.replace(
        als, officers=1, ops_used=0, ops_done=False))
    state = state.replace(phase=Phase.EVENING, turn_index=state.factions.index(A))

    action = AllianceOpMove(player=A, src=adj_cid, dst=keep_cid, count=1)
    assert_legal(state, action)
