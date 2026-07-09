"""戦闘 pending スタック機構の自己テスト。

使い方: ``python3 -m engine.selftest``

猫野侯国 + 「何もしないスタブ派閥」(DUMMY)の2派閥手動シナリオで、
戦闘1回(4.3 の4ステップ)が保留デシジョンスタック(3.2)経由で
解決できることを確認する。奇襲(4.3.1)パスも検証する。
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
    SetupChooseKeep,
)
from .apply import apply
from .game import new_game
from .legal import legal_actions
from .state import GameState
from .types import FactionId, Piece, B_SAWMILL

M = FactionId.MARQUISE
D = FactionId.DUMMY


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


def main() -> int:
    print("selftest: battle via pending stack")
    test_battle_via_pending()
    print("selftest: ambush via pending stack")
    test_ambush_via_pending()
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
