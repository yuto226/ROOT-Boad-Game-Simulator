"""共通ルールのテスト: 移動・戦闘・クラフト・支配(DESIGN.md 9.3 test_common.py)。

selftest.py の書き方(状態の手動構築 → apply → pending解決)を踏襲する。
selftest.py 自体は変更しない。``ScriptedRng`` は selftest.py 内の private な
テスト用スタブと同じ実装をこのファイルにローカル再定義したもの
(conftest.py は変更禁止のため、共有ヘルパーには追加できない)。
"""
from __future__ import annotations

import dataclasses

from engine.actions import AllocateHitsDecision, CraftCard, DeclareBattle, MarquiseMarch
from engine.apply import apply
from engine.types import B_ROOST, FactionId, ItemKind, Phase, Piece

from conftest import assert_illegal, assert_legal, find_card, make_state, put, set_hand

M = FactionId.MARQUISE
E = FactionId.EYRIE
A = FactionId.ALLIANCE


class ScriptedRng:
    """randint を固定列で返すテスト用スタブ(engine/selftest.py の同名クラスの複製)。

    conftest.py は変更禁止のため、共有ヘルパー化はせずここにローカル定義する。
    """

    def __init__(self, rolls):
        self.rolls = list(rolls)

    def randint(self, a, b):
        return self.rolls.pop(0)

    def shuffle(self, seq):
        pass

    def choice(self, seq):
        return seq[0]


def _clear(state, cid: int):
    """広場 cid の駒(兵士・建物・トークン)をすべて取り除く(ruinは保持)。"""
    cs = dataclasses.replace(state.clearing(cid), soldiers=(), buildings=(), tokens=())
    return state.with_clearing(cs)


def _ready_daylight(state):
    """移動/戦闘の合法判定に必要な最低条件(昼光フェイズ・行動回数3)を整える。"""
    state = state.replace(phase=Phase.DAYLIGHT)
    ms = state.marquise()
    return state.with_faction_state(dataclasses.replace(ms, actions_left=3))


# ---------------- 1. 移動(4.2) ----------------
def test_march_legal_with_control_of_src_or_dst():
    """移動 4.2.1: 出発か到着のどちらかを支配していれば合法。"""
    state, rng = make_state((M, E))
    state = _ready_daylight(state)
    state = _clear(state, 1)
    state = _clear(state, 2)
    # 出発側(1)をMが支配 → 合法
    state = put(state, 1, soldiers={M: 2})
    assert_legal(state, MarquiseMarch(player=M, src=1, dst=2, count=1))

    # 到着側だけをMが支配していても合法(出発側はEが支配、Mは兵士のみ保持)
    state2, _ = make_state((M, E))
    state2 = _ready_daylight(state2)
    state2 = _clear(state2, 1)
    state2 = _clear(state2, 2)
    state2 = put(state2, 1, soldiers={M: 1})
    state2 = put(state2, 1, soldiers={E: 3})  # Eが1を支配(3>1)
    state2 = put(state2, 2, soldiers={M: 2})  # Mが2(到着)を支配
    assert_legal(state2, MarquiseMarch(player=M, src=1, dst=2, count=1))


def test_march_illegal_without_control_of_either():
    """移動 4.2.1: 出発・到着のどちらも支配していなければ違法。"""
    state, rng = make_state((M, E))
    state = _ready_daylight(state)
    state = _clear(state, 1)
    state = _clear(state, 2)
    # Eが1を支配(3>1)。Mは兵士1のみ保持。2は完全に空。
    state = put(state, 1, soldiers={M: 1})
    state = put(state, 1, soldiers={E: 3})
    assert_illegal(state, MarquiseMarch(player=M, src=1, dst=2, count=1))


def test_march_illegal_to_nonadjacent_clearing():
    """移動 4.2: 隣接していない広場への移動は違法。"""
    state, rng = make_state((M, E))
    state = _ready_daylight(state)
    state = _clear(state, 0)
    state = put(state, 0, soldiers={M: 2})
    assert 5 not in state.map.clearing(0).adjacent
    assert_illegal(state, MarquiseMarch(player=M, src=0, dst=5, count=1))


# ---------------- 2. 戦闘の宣言可否(4.3) ----------------
def test_battle_legal_only_where_defender_has_pieces():
    """戦闘 4.3: 防御側の駒がある広場でのみ DeclareBattle が合法/自派閥のみの広場では違法。"""
    state, rng = make_state((M, E))
    state = _ready_daylight(state)
    c, d = 1, 2
    state = _clear(state, c)
    state = _clear(state, d)
    state = put(state, c, soldiers={M: 2, E: 1})  # Eの駒あり → 合法
    state = put(state, d, soldiers={M: 2})        # Mのみ → 違法
    assert_legal(state, DeclareBattle(player=M, clearing=c, defender=E))
    assert_illegal(state, DeclareBattle(player=M, clearing=d, defender=E))


# ---------------- 3. 無防備ボーナス(4.3.2 / 4.3.3.II) ----------------
def test_undefended_defender_grants_bonus_hit():
    """戦闘 4.3.3.II: 防御側が兵士を持たない(建物のみ)なら攻撃側+1ヒット。

    攻撃側兵士を1にすることで出目クランプが常に1になり(min(roll,1)==1
    はroll>=1で恒真)、無防備ボーナスの+1だけを切り分けて検証できる。
    """
    state, rng = make_state((M, E))
    c = 1
    state = _clear(state, c)
    state = put(state, c, soldiers={M: 1}, buildings=[Piece(E, B_ROOST)])
    state = set_hand(state, M, ())  # 奇襲カードを除いて通常ロールに固定
    state = set_hand(state, E, ())

    state = apply(state, DeclareBattle(player=M, clearing=c, defender=E), rng)

    dec = next(d for d in state.pending
               if isinstance(d, AllocateHitsDecision) and d.victim == E)
    assert dec.hits == 2, "無防備+1が乗った2ヒットのはず: got %d" % dec.hits


# ---------------- 4. ヒット数の出目クランプ(4.3.2.I) ----------------
def test_hits_capped_by_own_soldier_count():
    """戦闘 4.3.2.I: ヒット数は自兵士数が上限(出目クランプ)。

    防御側(E)の兵士を1に固定し、複数のダイス目(3〜6)でロールしても
    Mが受けるヒットが常に1でクランプされることを確認する。
    """
    for dice in ([6, 6], [5, 5], [4, 4], [3, 3]):
        state, _ = make_state((M, E))
        c = 1
        state = _clear(state, c)
        state = put(state, c, soldiers={M: 6, E: 1})
        state = set_hand(state, M, ())
        state = set_hand(state, E, ())
        rng = ScriptedRng(dice)

        state = apply(state, DeclareBattle(player=M, clearing=c, defender=E), rng)

        dec = next((d for d in state.pending
                    if isinstance(d, AllocateHitsDecision) and d.victim == M), None)
        hits = dec.hits if dec is not None else 0
        assert hits == 1, (
            "防御側兵士数1が上限のはず(dice=%r): got %d" % (dice, hits))


# ---------------- 5. クラフト(4.4 / 4.1) ----------------
def test_craft_illegal_without_matching_tool_suit():
    """クラフト 4.1.1: ツール(工房)のスート不足なら CraftCard は不合法。

    デフォルトセットアップの工房は1軒(rabbit広場)のみ。sword系カードは
    fox×2を要求するため支払えない。
    """
    state, rng = make_state((M, E))
    state = state.replace(phase=Phase.DAYLIGHT)
    card = find_card(state, item=ItemKind.SWORD)
    state = set_hand(state, M, (card,))
    assert_illegal(state, CraftCard(player=M, card_id=card))


def test_craft_illegal_when_item_supply_exhausted():
    """クラフト 4.1.2: アイテムがサプライ枯渇なら CraftCard は不合法。"""
    state, rng = make_state((M, E))
    state = state.replace(phase=Phase.DAYLIGHT)
    card = find_card(state, item=ItemKind.BOOTS)  # cost=['rabbit'] は工房で支払える
    state = set_hand(state, M, (card,))
    assert_legal(state, CraftCard(player=M, card_id=card))

    state = state.replace(supply_items=tuple(
        (k, 0) if k == ItemKind.BOOTS else (k, n) for k, n in state.supply_items))
    assert_illegal(state, CraftCard(player=M, card_id=card))


# ---------------- 6. 支配のタイブレーク(2.5) ----------------
def test_tied_clearing_has_no_controller():
    """支配 2.5: 同数タイなら支配者なし(鷲巣のタイブレークは test_eyrie 側で扱う)。"""
    state, rng = make_state((M, A))
    c = 1
    state = _clear(state, c)
    state = put(state, c, soldiers={M: 2, A: 2})
    assert state.controller(c) is None
    assert not state.controls(M, c)
    assert not state.controls(A, c)
