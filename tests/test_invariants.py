"""状態不変量 validate() の単体テスト + ミニスモーク(DESIGN.md 9.4 / 9.5)。"""
from __future__ import annotations

import dataclasses

import pytest

from engine.game import run_game
from engine.types import B_SAWMILL, FactionId, Piece

from conftest import make_state, put

M = FactionId.MARQUISE
E = FactionId.EYRIE
A = FactionId.ALLIANCE
V = FactionId.VAGABOND
THREE = (M, E, A)
FOUR = (M, E, A, V)


# ---------------- ミニスモーク(9.5) ----------------
def test_mini_smoke_three_player_validates():
    """3人戦(猫・鷲巣・連合)を validate_each_step=True で10試合(9.5)。

    各 apply 後に validate() を呼び、全不変量(9.4)が試合を通して破れない
    ことを検証する。数十秒以内に収まる規模。
    """
    from bots.random_bot import RandomBot
    bot = RandomBot()
    policies = {f: bot for f in THREE}
    for seed in range(10):
        result = run_game(THREE, policies, seed=seed, max_turns=300,
                          validate_each_step=True)
        # クラッシュせず勝者確定 or timeout で正常終了すれば合格。
        assert result.turns >= 1


def test_mini_smoke_four_player_with_vagabond_validates():
    """4人戦(猫・鷲巣・連合・放浪部族)を validate_each_step=True で10試合
    (フェーズ5: 放浪部族実装後の回帰確認。9.5 と同方式)。

    3人戦版と同様、各 apply 後に validate() を呼び、放浪部族参加時も
    全不変量(9.4)が試合を通して破れないことを検証する。
    """
    from bots.random_bot import RandomBot
    bot = RandomBot()
    policies = {f: bot for f in FOUR}
    for seed in range(10):
        result = run_game(FOUR, policies, seed=seed, max_turns=300,
                          validate_each_step=True)
        assert result.turns >= 1


# ---------------- validate() ポジティブ ----------------
def test_valid_initial_state_passes():
    """セットアップ直後の正当な初期状態は validate() を通過する。"""
    state, _ = make_state(THREE)
    state.validate()  # 例外が飛ばなければ合格


# ---------------- validate() ネガティブ ----------------
def test_slot_overflow_raises():
    """建物枠超過(9.4 既存チェック)で AssertionError。"""
    state, _ = make_state(THREE)
    # どの広場も枠は 1〜3。建物を大量追加して確実に超過させる。
    cid = 1
    state = put(state, cid, buildings=[Piece(M, B_SAWMILL) for _ in range(5)])
    with pytest.raises(AssertionError):
        state.validate()


def test_soldier_limit_exceeded_raises():
    """兵士総数上限超過(9.4.1)で AssertionError。"""
    state, _ = make_state(THREE)
    # 盤上に上限(25)を超える猫兵士を置く(サプライは別途正の値のまま)。
    state = put(state, 1, soldiers={M: 100})
    with pytest.raises(AssertionError):
        state.validate()


def test_card_conservation_violation_raises():
    """カード保存則違反(9.4.4)で AssertionError。"""
    state, _ = make_state(THREE)
    # どこからも移さずに架空カードを1枚手札へ追加 → 合計が期待値+1。
    ms = state.fs(M)
    state = state.with_faction_state(
        dataclasses.replace(ms, hand=ms.hand + ("phantom-card",)))
    with pytest.raises(AssertionError):
        state.validate()
