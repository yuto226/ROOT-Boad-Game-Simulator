"""戦闘 pending スタック機構と鷲巣王朝の内乱(7.7)の自己テスト。

使い方: ``python3 -m engine.selftest``

1. 猫野侯国 + 「何もしないスタブ派閥」(DUMMY)の2派閥手動シナリオで、
   戦闘1回(4.3 の4ステップ)が保留デシジョンスタック(3.2)経由で
   解決できることを確認する。奇襲(4.3.1)パスも検証する。
2. 猫+鷲巣の2派閥シナリオで、実行不能な勅令による内乱(7.7)の
   VP喪失(クランプ含む)・忠臣残存・君主交代・夕闇直行を検証する。
"""
from __future__ import annotations

import dataclasses
import random
import sys

from .actions import (
    AllocateHit,
    AllocateHitsDecision,
    AmbushChoice,
    AmbushDefenderDecision,
    DeclareBattle,
    EndPhase,
    EyrieChooseCorner,
    EyrieChooseLeader,
    EyrieTurmoil,
    SetupChooseKeep,
)
from .apply import apply
from .game import new_game
from .legal import legal_actions
from .state import GameState
from .types import (
    B_ROOST,
    B_SAWMILL,
    Corner,
    FactionId,
    LOYAL_VIZIER,
    Phase,
    Piece,
    Suit,
)

M = FactionId.MARQUISE
D = FactionId.DUMMY
E = FactionId.EYRIE


def _setup_two_faction(rng: random.Random) -> GameState:
    """猫(城砦NW)+ダミーの2派閥状態を作り、広場1に対峙させる。"""
    state = new_game((M, D), rng)
    # セットアップ Decision(城砦の隅)を解決
    assert state.pending, "setup decision expected"
    state = apply(state, SetupChooseKeep(player=M, corner="NW"), rng)
    assert not state.pending

    # 手動シナリオ: 広場1に猫3・ダミー2+ダミー建物1を配置
    cs = state.clearing(1)
    cs = cs.with_soldiers(M, 3).with_soldiers(D, 2)
    cs = cs.add_building(Piece(D, B_SAWMILL))
    state = state.with_clearing(cs)
    return state


def test_battle_via_pending() -> None:
    """通常戦闘: DeclareBattle → ロール → AllocateHitsDecision 解決。"""
    rng = random.Random(42)
    state = _setup_two_faction(rng)
    # ダミーの手札から奇襲カードを除き、通常ロールに固定
    dfs = state.fs(D)
    hand = tuple(c for c in dfs.hand if not state.cards.get(c).is_ambush)
    state = state.with_faction_state(dataclasses.replace(dfs, hand=hand))

    before_m = state.clearing(1).soldier_count(M)
    before_d = state.clearing(1).soldier_count(D)

    state = apply(state, DeclareBattle(player=M, clearing=1, defender=D), rng)

    # ヒットが出ていれば AllocateHitsDecision が積まれている
    steps = 0
    while state.pending:
        steps += 1
        assert steps < 50, "pending loop did not terminate"
        dec = state.pending[-1]
        assert isinstance(dec, AllocateHitsDecision), "unexpected decision %r" % dec
        acts = legal_actions(state)
        assert acts, "no options for allocation"
        assert all(isinstance(a, AllocateHit) for a in acts)
        # 兵士が残る間は兵士のみが選択肢(4.3.4)
        if state.clearing(1).soldier_count(dec.victim) > 0:
            assert acts == [AllocateHit(player=dec.actor, target=("soldier",))]
        state = apply(state, acts[0], rng)

    after_m = state.clearing(1).soldier_count(M)
    after_d = state.clearing(1).soldier_count(D)
    removed = (before_m - after_m) + (before_d - after_d) + (
        1 - len(state.clearing(1).buildings_of(D)))
    assert removed >= 0
    # ダイスは 1..6 なので何かしらのヒットがほぼ必ず出るが、0 でも機構は成立
    print("  battle resolved: M %d->%d, D %d->%d, D buildings=%d, M vp=%d (steps=%d)"
          % (before_m, after_m, before_d, after_d,
             len(state.clearing(1).buildings_of(D)), state.fs(M).vp, steps))


def test_ambush_via_pending() -> None:
    """奇襲パス: 防御側に奇襲カードを持たせ AmbushDefenderDecision を解決。"""
    rng = random.Random(7)
    state = _setup_two_faction(rng)

    # 広場1(mouse)一致の奇襲カードをダミーの手札に強制注入
    ambush_id = None
    suit = state.map.clearing(1).suit
    for d in state.cards.defs:
        if d.is_ambush and d.suit == suit:
            ambush_id = d.id
            break
    assert ambush_id is not None, "no ambush card def found"
    dfs = state.fs(D)
    state = state.with_faction_state(dataclasses.replace(dfs, hand=dfs.hand + (ambush_id,)))
    # 攻撃側(猫)の手札から奇襲を除き、妨害選択肢を消す
    mfs = state.fs(M)
    state = state.with_faction_state(dataclasses.replace(
        mfs, hand=tuple(c for c in mfs.hand if not state.cards.get(c).is_ambush)))

    state = apply(state, DeclareBattle(player=M, clearing=1, defender=D), rng)
    assert state.pending and isinstance(state.pending[-1], AmbushDefenderDecision)

    acts = legal_actions(state)
    ambush_acts = [a for a in acts if isinstance(a, AmbushChoice) and a.card_id]
    assert ambush_acts, "ambush option missing"
    before_m = state.clearing(1).soldier_count(M)
    state = apply(state, ambush_acts[0], rng)

    # 奇襲2ヒットは兵士へ自動適用(4.3.1.II)済み → 残ヒットの割り振りを解決
    assert state.clearing(1).soldier_count(M) == before_m - 2, "ambush must deal 2 hits"
    steps = 0
    while state.pending:
        steps += 1
        assert steps < 50
        acts = legal_actions(state)
        state = apply(state, acts[0], rng)
    print("  ambush resolved: M soldiers %d->%d" % (before_m, state.clearing(1).soldier_count(M)))


# ---------------- 鷲巣王朝: 内乱(7.7) ----------------
def _setup_eyrie_pre_turmoil(rng: random.Random, used_leaders=()) -> GameState:
    """猫(城砦NW)+鷲巣(隅SE, 君主カリスマ)を作り、内乱直前まで進める。

    勅令の募兵列に鳥カード+キツネカードを追加した上で、マップ上の
    止まり木を全撤去して募兵(7.5.2.I)を実行不能にする。
    """
    state = new_game((M, E), rng)
    state = apply(state, SetupChooseKeep(player=M, corner="NW"), rng)

    # 7.3.2: 城砦が隅NWにあるので、鷲巣の隅は対角SEが強制される
    acts = legal_actions(state)
    assert acts == [EyrieChooseCorner(player=E, corner="SE")], (
        "対角の隅が強制されるはず(7.3.2): %r" % acts)
    state = apply(state, acts[0], rng)

    # 7.3.3: 君主4枚から選択 → カリスマ(忠臣は募兵・戦闘列, 7.8.2)
    acts = legal_actions(state)
    assert len(acts) == 4 and all(isinstance(a, EyrieChooseLeader) for a in acts)
    state = apply(state, EyrieChooseLeader(player=E, leader="charismatic"), rng)
    assert not state.pending
    es = state.fs(E)
    assert es.decree == ((LOYAL_VIZIER,), (), (LOYAL_VIZIER,), ())

    # 勅令に鳥1枚+キツネ1枚を注入(鳥計3枚: 忠臣2+鳥1)
    bird_card = fox_card = None
    for d in state.cards.defs:
        if d.is_dominance:
            continue  # 2人戦の山札に存在しないカードは避ける(5.1.3)
        if bird_card is None and d.suit == Suit.BIRD:
            bird_card = d.id
        if fox_card is None and d.suit == Suit.FOX:
            fox_card = d.id
    assert bird_card and fox_card
    decree = ((LOYAL_VIZIER, bird_card, fox_card), (), (LOYAL_VIZIER,), ())

    # マップ上の止まり木を全撤去 → 募兵列(最左)が実行不能
    corner_cid = state.map.corner_clearing(Corner.SE)
    state = state.with_clearing(
        state.clearing(corner_cid).remove_building(Piece(E, B_ROOST)))

    es = state.fs(E)
    es = dataclasses.replace(
        es, vp=1, hand=(), decree=decree, decree_remaining=decree,
        decree_started=False, built_roosts=0, used_leaders=tuple(used_leaders))
    state = state.with_faction_state(es)
    # 鷲巣の昼光フェイズにする
    return state.replace(turn_index=state.factions.index(E), phase=Phase.DAYLIGHT)


def test_eyrie_turmoil() -> None:
    """内乱: VP喪失(0にクランプ)・追放・忠臣残存・君主交代・夕闇直行。"""
    rng = random.Random(3)
    state = _setup_eyrie_pre_turmoil(rng)
    bird_card = state.fs(E).decree[0][1]
    fox_card = state.fs(E).decree[0][2]

    # 実行不能な勅令 → 合法手は内乱のみ(7.5.2)
    acts = legal_actions(state)
    assert acts == [EyrieTurmoil(player=E)], "内乱が強制されるはず: %r" % acts
    state = apply(state, acts[0], rng)

    es = state.fs(E)
    # 7.7.1 恥辱: VP1 - 鳥3枚(忠臣2+鳥1) → 0未満にはしない
    assert es.vp == 0, "VP must clamp at 0, got %d" % es.vp
    # 7.7.2 追放: 忠臣以外は捨て山へ、忠臣は捨て山に行かない
    assert bird_card in state.discard and fox_card in state.discard
    assert LOYAL_VIZIER not in state.discard
    # 7.7.3 失脚: カリスマは裏向きへ
    assert es.leader is None and es.used_leaders == ("charismatic",)

    # 君主交代 Decision: 表向きの3枚から選択
    acts = legal_actions(state)
    assert sorted(a.leader for a in acts) == ["builder", "commander", "despot"]
    state = apply(state, EyrieChooseLeader(player=E, leader="despot"), rng)

    es = state.fs(E)
    # 忠臣2枚が新君主の指定列(独裁者=移動・建設, 7.8.4)へ
    assert es.decree == ((), (LOYAL_VIZIER,), (), (LOYAL_VIZIER,))
    assert es.leader == "despot"
    # 7.7.4 休止: 昼光を即終了して夕闇へ(VP 0枚=0, ドロー1+0)
    assert state.phase == Phase.EVENING
    assert es.vp == 0
    assert len(es.hand) == 1, "evening draw of 1 expected, hand=%r" % (es.hand,)
    assert not state.pending
    assert legal_actions(state) == [EndPhase(player=E)]
    print("  turmoil resolved: vp=%d leader=%s phase=%s hand=%d"
          % (es.vp, es.leader, state.phase.name, len(es.hand)))


def test_eyrie_turmoil_new_generation() -> None:
    """新世代(7.7.3.I): 全君主が裏なら全て表に返してから選択。"""
    rng = random.Random(11)
    state = _setup_eyrie_pre_turmoil(
        rng, used_leaders=("builder", "commander", "despot"))
    state = apply(state, EyrieTurmoil(player=E), rng)
    es = state.fs(E)
    assert es.used_leaders == (), "all leaders must flip face-up (7.7.3.I)"
    acts = legal_actions(state)
    assert sorted(a.leader for a in acts) == [
        "builder", "charismatic", "commander", "despot"]
    print("  new generation: %d leaders selectable" % len(acts))


def main() -> int:
    print("selftest: battle via pending stack")
    test_battle_via_pending()
    print("selftest: ambush via pending stack")
    test_ambush_via_pending()
    print("selftest: eyrie turmoil (7.7)")
    test_eyrie_turmoil()
    print("selftest: eyrie turmoil new generation (7.7.3.I)")
    test_eyrie_turmoil_new_generation()
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
