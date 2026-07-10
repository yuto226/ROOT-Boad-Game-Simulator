"""PPO self-play 用ネットワーク(DESIGN.md 13.2)。

共有胴体 MLP + 2ヘッド(policy / value)の Actor-Critic。両席とも同一ネットを
用いる self-play(視点は観測の perspective onehot が担う, 12.3)。

- 胴体: ``obs_dim -> 512 -> 512``(ReLU / 直交初期化 gain=√2)
- policy ヘッド: ``512 -> catalog.size``(直交初期化 gain=0.01)
- value ヘッド: ``512 -> 1``(直交初期化 gain=1.0)
- マスク適用: ``logits.masked_fill(~mask, -1e9)`` → Categorical。
  entropy・log_prob もマスク後の分布で計算する(13.2)。

torch はこのモジュール以降にのみ閉じる(catalog/encoder/env は numpy のまま, 13.1)。
"""
from __future__ import annotations

from typing import Optional, Tuple

import torch
import torch.nn as nn
from torch.distributions import Categorical

#: マスクで塞ぐロジットの値。-inf ではなく大きな負値にして 0*(-1e9)=0 で
#: entropy が nan にならないようにする(13.2)。
NEG_INF = -1e9


def _orthogonal(layer: nn.Linear, gain: float) -> nn.Linear:
    """直交初期化(gain 指定)+バイアス 0(13.2)。"""
    nn.init.orthogonal_(layer.weight, gain=gain)
    nn.init.zeros_(layer.bias)
    return layer


def masked_logits(logits: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """合法手マスクを適用したロジットを返す(13.2)。

    ``mask`` は bool テンソル(True=合法)。非合法は :data:`NEG_INF` で塞ぐ。
    """
    return logits.masked_fill(~mask, NEG_INF)


class ActorCritic(nn.Module):
    """共有胴体 Actor-Critic(DESIGN.md 13.2)。"""

    def __init__(self, obs_dim: int, action_size: int, hidden: int = 512) -> None:
        super().__init__()
        self.obs_dim = obs_dim
        self.action_size = action_size
        root2 = 2.0 ** 0.5
        self.body = nn.Sequential(
            _orthogonal(nn.Linear(obs_dim, hidden), root2),
            nn.ReLU(),
            _orthogonal(nn.Linear(hidden, hidden), root2),
            nn.ReLU(),
        )
        self.policy_head = _orthogonal(nn.Linear(hidden, action_size), 0.01)
        self.value_head = _orthogonal(nn.Linear(hidden, 1), 1.0)

    # ------------------------------------------------------------
    def forward(self, obs: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """``obs[B, obs_dim]`` → ``(logits[B, action_size], value[B])``。"""
        h = self.body(obs)
        logits = self.policy_head(h)
        value = self.value_head(h).squeeze(-1)
        return logits, value

    # ------------------------------------------------------------
    def act(self, obs: torch.Tensor, mask: torch.Tensor,
            deterministic: bool = False) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """収集時の 1 ステップ推論(13.3)。

        マスク後分布から行動をサンプル(``deterministic`` で argmax)し、
        ``(action[B], log_prob[B], value[B])`` を返す。サンプリングは torch の
        グローバル rng に従う(学習用サンプリングは torch の rng, 13.3)。
        """
        logits, value = self.forward(obs)
        ml = masked_logits(logits, mask)
        dist = Categorical(logits=ml)
        if deterministic:
            action = torch.argmax(ml, dim=-1)
        else:
            action = dist.sample()
        log_prob = dist.log_prob(action)
        return action, log_prob, value

    # ------------------------------------------------------------
    def evaluate_actions(self, obs: torch.Tensor, mask: torch.Tensor,
                         action: torch.Tensor
                         ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """PPO 更新時: 既存行動の ``(log_prob, entropy, value)`` を返す(13.3)。

        log_prob・entropy はマスク後の分布で計算する(13.2)。
        """
        logits, value = self.forward(obs)
        ml = masked_logits(logits, mask)
        dist = Categorical(logits=ml)
        log_prob = dist.log_prob(action)
        entropy = dist.entropy()
        return log_prob, entropy, value

    # ------------------------------------------------------------
    @torch.no_grad()
    def value_only(self, obs: torch.Tensor) -> torch.Tensor:
        """ブートストラップ用に value のみ推論する(13.3)。"""
        h = self.body(obs)
        return self.value_head(h).squeeze(-1)


def build_net(obs_dim: int, action_size: int,
              device: Optional[torch.device] = None) -> ActorCritic:
    """ネットワークを構築して device へ載せる(13.2)。"""
    net = ActorCritic(obs_dim, action_size)
    if device is not None:
        net = net.to(device)
    return net
