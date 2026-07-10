"""鷲巣王朝(第7章)の合法/違法テスト(DESIGN.md 9.3)。

カバー範囲(9.3 鷲巣王朝 5項目):
  1. 勅令 7.5: 列の左から強制実行 → test_decree_column_forced_left_to_right
  2. 内乱 7.7: selftest 済み(tests/test_selftest.py の
     test_eyrie_turmoil / test_eyrie_turmoil_new_generation)。ここには書かない。
  3. 森の王者 7.2.2: 同数タイの支配 → test_woodland_ruler_tiebreak
  4. 商業軽視 7.2.3: クラフトVPが1になる(建設者は例外) →
     test_craft_vp_commerce_disdain / test_craft_vp_builder_exempt
  5. 恥辱 7.7.1: selftest 済み(test_eyrie_turmoil の VP クランプ)。ここには書かない。
"""
from __future__ import annotations

import dataclasses

from engine.actions import CraftCard, EndPhase, EyrieDecreeBuild, EyrieDecreeMove
from engine.apply import apply
from engine.legal import legal_actions
from engine.types import B_ROOST, FactionId, Phase, Piece, Suit

from conftest import assert_illegal, assert_legal, find_card, make_state, put, set_hand

M = FactionId.MARQUISE
E = FactionId.EYRIE
A = FactionId.ALLIANCE


def _corner_roost_cid(state) -> int:
    """鷲巣の開始時の隅広場(止まり木あり)を探す。"""
    return next(cs.cid for cs in state.clearings
                if any(p.faction == E and p.kind == B_ROOST for p in cs.buildings))


# ---------------- 1. 勅令 7.5: 列の左から強制実行 ----------------
def test_decree_column_forced_left_to_right():
    """勅令 7.5: 昼光は勅令の列を左から強制実行、列にない任意アクションは違法。

    募兵列(col0)を空にし、移動列(col1)と建設列(col3)にカードを置く。
    移動列が最左の未消化列である間は建設アクションは選択肢に出ず、明示的に
    構築した EyrieDecreeBuild も違法。移動列を消化すると建設列が開放される
    (「列にない任意アクションは違法」「左から強制実行」の両方を検証)。
    """
    state, rng = make_state((M, E))
    corner_cid = _corner_roost_cid(state)
    corner_suit = state.map.clearing(corner_cid).suit
    move_card = find_card(state, suit=corner_suit)

    build_cid = next(
        cs.cid for cs in state.clearings
        if cs.cid != corner_cid and not cs.buildings and not cs.ruin
        and state.map.clearing(cs.cid).suit != corner_suit)
    build_suit = state.map.clearing(build_cid).suit
    build_card = find_card(state, suit=build_suit)
    state = put(state, build_cid, soldiers={E: 5})

    es = state.eyrie()
    es = dataclasses.replace(
        es, decree_remaining=((), (move_card,), (), (build_card,)),
        decree_started=True)
    state = state.with_faction_state(es)
    state = state.replace(phase=Phase.DAYLIGHT, turn_index=state.factions.index(E))

    acts = legal_actions(state)
    move_acts = [a for a in acts if isinstance(a, EyrieDecreeMove)]
    assert move_acts, "移動列(最左の非空列)の選択肢が出るはず: %r" % acts
    assert not any(isinstance(a, EyrieDecreeBuild) for a in acts), (
        "建設列はまだ未開放のため選択肢に出てはいけない: %r" % acts)
    assert_illegal(state, EyrieDecreeBuild(
        player=E, card_id=build_card, clearing=build_cid))
    assert_illegal(state, EndPhase(player=E))

    # 移動列を1枚消化 → 次に開放されるのは(募兵/戦闘が空なので)建設列
    state = apply(state, move_acts[0], rng)
    acts2 = legal_actions(state)
    assert any(
        isinstance(a, EyrieDecreeBuild) and a.card_id == build_card
        and a.clearing == build_cid for a in acts2), (
        "移動列消化後は建設列が開放されるはず: %r" % acts2)


# ---------------- 3. 森の王者 7.2.2 ----------------
def test_woodland_ruler_tiebreak():
    """森の王者 7.2.2: 鷲巣を含む同数タイは鷲巣が支配、鷲巣を含まないタイは支配者なし。"""
    state, rng = make_state((M, E, A))

    empty_clearings = [cs.cid for cs in state.clearings if not cs.buildings]
    eyrie_tie_cid, other_tie_cid = empty_clearings[0], empty_clearings[1]

    # 鷲巣 vs 猫の同数タイ → 森の王者(7.2.2)で鷲巣が支配
    state = put(state, eyrie_tie_cid, soldiers={M: 2, E: 2, A: 0})
    assert state.controller(eyrie_tie_cid) == E, (
        "鷲巣を含む同数タイは鷲巣が支配するはず(7.2.2)")

    # 猫 vs 連合の同数タイ(鷲巣は不参加)→ 通常どおり支配者なし
    state = put(state, other_tie_cid, soldiers={M: 2, A: 2, E: 0})
    assert state.controller(other_tie_cid) is None, (
        "鷲巣を含まない同数タイは支配者なしのはず(2.5)")


# ---------------- 4. 商業軽視 7.2.3 ----------------
def test_craft_vp_commerce_disdain():
    """商業軽視 7.2.3: クラフト(item効果)のVPは印刷値に関わらず常に1になる。"""
    state, rng = make_state((M, E))
    state = state.replace(phase=Phase.DAYLIGHT, turn_index=state.factions.index(E))
    corner_cid = _corner_roost_cid(state)
    fox_cid = next(cs.cid for cs in state.clearings
                   if cs.cid != corner_cid
                   and state.map.clearing(cs.cid).suit == Suit.FOX)
    state = put(state, fox_cid, buildings=[Piece(E, B_ROOST)])
    state = set_hand(state, E, ("anvil",))

    craft = CraftCard(player=E, card_id="anvil")
    assert_legal(state, craft)
    state = apply(state, craft, rng)
    assert state.fs(E).vp == 1, (
        "商業軽視: anvil の印刷VP=2 だが鷲巣は常に1VPになるはず, got %d"
        % state.fs(E).vp)


def test_craft_vp_builder_exempt():
    """商業軽視 7.2.3 の例外(7.8.1): 君主が建設者ならクラフトVPは印刷値のまま。"""
    state, rng = make_state((M, E))
    state = state.replace(phase=Phase.DAYLIGHT, turn_index=state.factions.index(E))
    es = state.eyrie()
    state = state.with_faction_state(dataclasses.replace(es, leader="builder"))
    corner_cid = _corner_roost_cid(state)
    mouse_cid = next(cs.cid for cs in state.clearings
                     if cs.cid != corner_cid
                     and state.map.clearing(cs.cid).suit == Suit.MOUSE)
    state = put(state, mouse_cid, buildings=[Piece(E, B_ROOST)])
    state = set_hand(state, E, ("root-tea-fox",))

    craft = CraftCard(player=E, card_id="root-tea-fox")
    assert_legal(state, craft)
    state = apply(state, craft, rng)
    assert state.fs(E).vp == 2, (
        "建設者は商業軽視の対象外: root-tea-fox の印刷VP=2 のままのはず, got %d"
        % state.fs(E).vp)
