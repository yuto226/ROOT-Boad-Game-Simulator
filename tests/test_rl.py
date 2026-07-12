"""フェーズ6a RL 環境ラッパーの検証(DESIGN.md 12.5)。

numpy 未導入環境では skip する(env/encoder は numpy 必須, 12.1)。
"""
from __future__ import annotations

import dataclasses
import os
import random
import subprocess
import sys

import pytest

try:
    import numpy as np
    _HAVE_NUMPY = True
except ImportError:  # pragma: no cover
    _HAVE_NUMPY = False

pytestmark = pytest.mark.skipif(not _HAVE_NUMPY, reason="numpy 未導入(rl は numpy 必須)")

from engine.apply import apply
from engine.game import begin_first_turn, new_game
from engine.legal import legal_actions
from engine.types import LOYAL_VIZIER, FactionId

from rl.catalog import ActionCatalog, action_for, action_key, legal_mask

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FACTIONS = (FactionId.MARQUISE, FactionId.EYRIE,
             FactionId.ALLIANCE, FactionId.VAGABOND)


# ============================================================
# 12.5-1 カタログ決定性
# ============================================================
def test_catalog_determinism():
    cat = ActionCatalog()
    # size 固定・index↔key 全単射(catalog v5: 19.4 で MarquiseChooseWood 12 +
    # AllianceSpendSupporter 4 + VagabondExhaustItem 8 + VagabondRepairItem 8
    # = 32 キー追加。8129 → 8161)
    assert cat.size == 8161
    assert len(set(cat._keys)) == cat.size
    for i in range(cat.size):
        assert cat.index_of(cat.key_at(i)) == i

    # PYTHONHASHSEED を変えた subprocess で size と先頭/末尾キーが一致
    script = (
        "from rl.catalog import ActionCatalog;"
        "c=ActionCatalog();"
        "print(c.size);"
        "print(repr(c.key_at(0)));"
        "print(repr(c.key_at(c.size-1)))"
    )
    outs = []
    for hashseed in ("0", "1", "12345"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = hashseed
        env["PYTHONPATH"] = _REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        res = subprocess.run([sys.executable, "-c", script], cwd=_REPO_ROOT,
                             env=env, capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        outs.append(res.stdout)
    assert outs[0] == outs[1] == outs[2], "catalog はハッシュシード非依存であるべき\n%r" % outs


# ============================================================
# 12.5-2 整合性(ランダム対戦の全意思決定点)
# ============================================================
def _drive_game(seed, cat, max_turns=300, check=None):
    """1試合をランダムに回し、各意思決定点で check(state) を呼ぶ。"""
    rng = random.Random(seed)
    state = new_game(_FACTIONS, rng)
    setup_done = False
    while not state.finished and state.turn_count < max_turns:
        if not state.pending and not setup_done:
            state = begin_first_turn(state, rng)
            setup_done = True
            continue
        acts = legal_actions(state)
        if not acts:
            break
        if check is not None:
            check(state, acts)
        action = acts[0] if len(acts) == 1 else rng.choice(acts)
        state = apply(state, action, rng)
    return state


def test_catalog_integrity_random_games():
    cat = ActionCatalog()

    def check(state, acts):
        mask = legal_mask(state, cat)
        # (b) mask の True 数 >= 1
        assert int(mask.sum()) >= 1
        # (a) 全合法手が action_key でインデックス化できる → そのビットが立つ
        for a in acts:
            i = cat.index_of(action_key(state, a))
            assert mask[i]
        # (c) mask=True の全 i で action_for(state, i) が合法手に含まれる
        for i in np.nonzero(mask)[0]:
            resolved = action_for(state, int(i), cat)
            assert resolved in acts

    for g in range(20):
        _drive_game(1000 + g, cat, check=check)


# ============================================================
# 12.5-3 env 決定性
# ============================================================
def _rollout(seed, max_turns=300):
    """同一 seed の env を、独立 rng のマスク上サンプリングで走らせる。"""
    from rl.env import RootEnv
    env = RootEnv(_FACTIONS, max_turns=max_turns, auto_single=True, seed=seed)
    sampler = random.Random(9999)  # env 内部 rng とは独立
    obs_trace = []
    rewards_trace = []
    while env.agents:
        obs = env.observe(env.agent_selection)
        assert np.all(np.isfinite(obs["observation"]))
        obs_trace.append(obs["observation"].tobytes())
        legal_idx = np.nonzero(obs["action_mask"])[0]
        if len(legal_idx) == 0:
            break
        idx = int(sampler.choice(list(legal_idx)))
        env.step(idx)
        rewards_trace.append(tuple(sorted(env.rewards.items())))
    return obs_trace, rewards_trace, dict(env.terminations), dict(env.truncations), dict(env.infos)


def test_env_determinism():
    a = _rollout(42)
    b = _rollout(42)
    assert a[0] == b[0], "obs 列が seed 一致で不一致"
    assert a[1] == b[1], "reward 列が不一致"
    assert a[2] == b[2] and a[3] == b[3], "終局フラグが不一致"
    assert a[4] == b[4], "infos が不一致"


# ============================================================
# 12.5-4 episode 完走
# ============================================================
def test_env_episode_completes():
    from rl.env import RootEnv
    env = RootEnv(_FACTIONS, max_turns=300, auto_single=True, seed=7)
    sampler = random.Random(3)
    steps = 0
    while env.agents and steps < 200000:
        obs = env.observe(env.agent_selection)
        legal_idx = np.nonzero(obs["action_mask"])[0]
        if len(legal_idx) == 0:
            break
        env.step(int(sampler.choice(list(legal_idx))))
        steps += 1

    # terminated or truncated まで到達
    assert env._done
    terminated = any(env.terminations.values())
    truncated = any(env.truncations.values())
    assert terminated or truncated

    if terminated and not truncated:
        # 勝者 reward=+1 / 他 -1 の整合
        winner = env.infos[_FACTIONS[0].value]["winner"]
        assert winner is not None
        for fid in _FACTIONS:
            expected = 1.0 if fid.value == winner else -1.0
            assert env.rewards[fid.value] == expected
        # 合計 = +1 + (-1)*(F-1)
        assert abs(sum(env.rewards.values()) - (1.0 - (len(_FACTIONS) - 1))) < 1e-9


# ============================================================
# 12.7 build_column_potential 単体テスト
# ============================================================
def _with_build_column(state, cards):
    """建設列(勅令4列目, decree[COL_BUILD])を指定カード列に差し替えた state を返す。"""
    from engine.factions.eyrie import COL_BUILD

    es = state.eyrie()
    decree = list(es.decree)
    decree[COL_BUILD] = tuple(cards)
    es2 = dataclasses.replace(es, decree=tuple(decree))
    return state.with_faction_state(es2)


def test_build_column_potential_table():
    from rl.env import build_column_potential

    rng = random.Random(0)
    state = new_game(_FACTIONS, rng)
    BIRD = "armorers#1"        # Suit.BIRD
    MOUSE = "codebreakers#1"   # Suit.MOUSE(非鳥)

    # (カード列, 期待 φ) = (base(b) - 0.5*n)
    cases = [
        ((), -1.0),                      # b=0, n=0
        ((BIRD,), 1.0),                  # b=1, n=0
        ((BIRD, BIRD), 0.0),             # b=2, n=0
        ((BIRD, MOUSE), 0.5),            # b=1, n=1
        ((MOUSE, MOUSE), -2.0),          # b=0, n=2
        ((LOYAL_VIZIER, MOUSE), 0.5),    # 忠臣は鳥扱い(7.3.4): b=1, n=1
    ]
    for cards, expected in cases:
        s = _with_build_column(state, cards)
        assert build_column_potential(s) == pytest.approx(expected), cards


def test_build_column_potential_no_eyrie():
    from rl.env import build_column_potential

    rng = random.Random(0)
    state = new_game((FactionId.MARQUISE, FactionId.ALLIANCE), rng)
    assert build_column_potential(state) == 0.0


# ============================================================
# 12.7 テレスコープ検証: 累積 shaping = -φ(初期状態)、終局で ±1(0)加算
# ============================================================
def test_build_shaping_telescopes_to_negative_initial_potential():
    from rl.env import RootEnv

    factions = (FactionId.MARQUISE, FactionId.EYRIE)
    for seed in (11, 12, 13):
        env = RootEnv(factions, max_turns=200, auto_single=True, seed=seed,
                      build_shaping=1.0)
        phi0 = env._build_phi_prev  # reset 時に記録した φ(s0)(12.7)
        sampler = random.Random(seed + 900)
        steps = 0
        while env.agents and steps < 200000:
            obs = env.observe(env.agent_selection)
            legal_idx = np.nonzero(obs["action_mask"])[0]
            if len(legal_idx) == 0:
                break
            env.step(int(sampler.choice(list(legal_idx))))
            steps += 1
        assert env._done

        winner = env.infos[FactionId.MARQUISE.value].get("winner")
        if winner is None:
            outcome = 0.0  # タイムアウト
        else:
            outcome = 1.0 if winner == FactionId.EYRIE.value else -1.0
        got = env._cumulative_rewards[FactionId.EYRIE.value] - outcome
        assert got == pytest.approx(-phi0), (seed, got, phi0)


# ============================================================
# 12.7 互換性検証: shaping 全 0 なら従来どおり env.rewards は
# 途中 0・終局のみ ±1(タイムアウト0)
# ============================================================
def test_shaping_disabled_matches_legacy_reward_pattern():
    from rl.env import RootEnv

    for seed in (21, 22, 23):
        env = RootEnv(_FACTIONS, max_turns=150, auto_single=True, seed=seed)
        sampler = random.Random(seed + 700)
        steps = 0
        while env.agents and steps < 200000:
            obs = env.observe(env.agent_selection)
            legal_idx = np.nonzero(obs["action_mask"])[0]
            if len(legal_idx) == 0:
                break
            env.step(int(sampler.choice(list(legal_idx))))
            steps += 1
            if not env._done:
                # 途中ステップは全 agent の reward が 0(shaping 無効時, 12.7)
                assert all(v == 0.0 for v in env.rewards.values())
        assert env._done
        terminated = any(env.terminations.values())
        truncated = any(env.truncations.values())
        if terminated and not truncated:
            for fid in _FACTIONS:
                expected = 1.0 if env.infos[_FACTIONS[0].value]["winner"] == fid.value else -1.0
                assert env.rewards[fid.value] == expected
        else:
            assert all(v == 0.0 for v in env.rewards.values())
