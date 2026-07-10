"""フェーズ6c(前半)PPO 学習コードの検証(DESIGN.md 13.5-1)。

torch 未導入環境では skip する(net/ppo/nn_policy は torch 必須, 13.1)。
システム python(torch なし)では自動 skip され、`.venv/bin/python` でのみ実走する。

  (a) マスク分布: mask=False の行動の確率が 0
  (b) GAE の手計算一致(小さな固定列)
  (c) NNPolicy が合法手のみ返す(ランダム初期化ネットで 10 手)
"""
from __future__ import annotations

import random

import pytest

try:
    import numpy as np
    import torch
    _HAVE_TORCH = True
except ImportError:  # pragma: no cover
    _HAVE_TORCH = False

pytestmark = pytest.mark.skipif(not _HAVE_TORCH, reason="torch 未導入(rl の学習系は torch 必須)")

from engine.apply import apply
from engine.game import begin_first_turn, new_game
from engine.legal import legal_actions
from engine.types import FactionId

_FACTIONS = (FactionId.MARQUISE, FactionId.EYRIE)


# ============================================================
# 13.5-1(a) マスク分布: 非合法行動の確率が 0
# ============================================================
def test_masked_distribution_zero_prob():
    from torch.distributions import Categorical

    from rl.net import ActorCritic, masked_logits

    torch.manual_seed(0)
    action_size = 50
    net = ActorCritic(obs_dim=16, action_size=action_size)
    obs = torch.randn(4, 16)

    # ランダムなマスク(各行に必ず 1 つは合法を残す)
    mask = torch.rand(4, action_size) > 0.5
    mask[:, 0] = True  # 最低 1 手保証

    logits, _ = net(obs)
    ml = masked_logits(logits, mask)
    probs = Categorical(logits=ml).probs

    # 非合法(mask=False)の確率は厳密に 0
    illegal = probs[~mask]
    assert torch.all(illegal == 0.0), "非合法行動に確率が残っている: max=%r" % float(illegal.max())
    # 合法側だけで確率が 1 に正規化されている
    assert torch.allclose(probs.sum(dim=-1), torch.ones(4), atol=1e-5)


# ============================================================
# 13.5-1(b) GAE の手計算一致
# ============================================================
def test_gae_matches_hand_calc():
    from rl.ppo import compute_gae

    # --- 終局列: values=[0.5,0.2], rewards=[0,1], done=True, γ=1, λ=0.95 ---
    # i=1: delta=1+0-0.2=0.8, adv=0.8
    # i=0: delta=0+0.2-0.5=-0.3, adv=-0.3+0.95*0.8=0.46
    adv, ret = compute_gae([0.5, 0.2], [0.0, 1.0], done=True, bootstrap=0.0,
                           gamma=1.0, lam=0.95)
    assert adv == pytest.approx([0.46, 0.8])
    assert ret == pytest.approx([0.96, 1.0])

    # --- ブートストラップ列: values=[0.3], rewards=[0], done=False, bootstrap=0.7 ---
    # i=0: delta=0+0.7-0.3=0.4, adv=0.4, ret=0.7
    adv2, ret2 = compute_gae([0.3], [0.0], done=False, bootstrap=0.7,
                             gamma=1.0, lam=0.95)
    assert adv2 == pytest.approx([0.4])
    assert ret2 == pytest.approx([0.7])

    # --- 割引ありの 3 段(γ=0.9, λ=0.5)で漸化式一致 ---
    values = [1.0, 2.0, 3.0]
    rewards = [0.0, 0.0, 5.0]
    adv3, ret3 = compute_gae(values, rewards, done=True, bootstrap=0.0,
                             gamma=0.9, lam=0.5)
    # 手計算(reversed):
    # i=2: delta=5-3=2.0 ; adv=2.0
    # i=1: delta=0+0.9*3-2=0.7 ; adv=0.7+0.9*0.5*2.0=1.6
    # i=0: delta=0+0.9*2-1=0.8 ; adv=0.8+0.9*0.5*1.6=1.52
    assert adv3 == pytest.approx([1.52, 1.6, 2.0])
    assert ret3 == pytest.approx([1.52 + 1.0, 1.6 + 2.0, 2.0 + 3.0])


# ============================================================
# 13.5-1(c) NNPolicy が合法手のみ返す(ランダム初期化ネット)
# ============================================================
def test_nnpolicy_returns_legal_actions():
    from rl.catalog import ActionCatalog
    from rl.encoder import ObservationSpec
    from rl.net import build_net
    from rl.nn_policy import NNPolicy

    torch.manual_seed(1)
    device = torch.device("cpu")
    spec = ObservationSpec(_FACTIONS)
    catalog = ActionCatalog()
    net = build_net(spec.obs_dim, catalog.size, device)
    net.eval()

    for greedy in (True, False):
        policy = NNPolicy(net, spec, catalog, device, greedy=greedy)
        rng = random.Random(0)
        state = new_game(_FACTIONS, rng)
        setup_done = False
        decisions = 0
        guard = 0
        while decisions < 10 and not state.finished and guard < 5000:
            guard += 1
            if not state.pending and not setup_done:
                state = begin_first_turn(state, rng)
                setup_done = True
                continue
            acts = legal_actions(state)
            if not acts:
                break
            if len(acts) > 1:
                action = policy.choose(state, acts, rng)
                assert action in acts, "NNPolicy が非合法手を返した"
                decisions += 1
            else:
                action = acts[0]
            state = apply(state, action, rng)
        assert decisions >= 1, "10 手に届く前に終局/停止(greedy=%s)" % greedy
