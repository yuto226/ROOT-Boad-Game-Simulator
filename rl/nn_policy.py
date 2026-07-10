"""学習ネットの bots ``Policy`` アダプタ(DESIGN.md 13.4)。

:class:`NNPolicy` は bots の ``Policy`` プロトコル
(``choose(state, legal_actions, rng) -> Action``)を実装し、
encode → mask → argmax(または sample)→ ``action_for`` で Action に解決する。
これにより **既存の ``run_game`` / HeuristicBot / RandomBot がそのまま評価対戦相手**
になる(13.4)。torch はこのモジュールに閉じる。
"""
from __future__ import annotations

import random
from typing import List

import numpy as np
import torch

from engine.actions import Action
from engine.state import GameState

from .catalog import ActionCatalog, action_for, action_key, legal_mask
from .encoder import ObservationSpec
from .net import ActorCritic, masked_logits


class NNPolicy:
    """学習ネットを Policy として使うアダプタ(DESIGN.md 13.4)。

    - ``greedy=True``: マスク後ロジットの argmax(評価既定, 決定的)。
    - ``greedy=False``: マスク後分布からサンプル(渡された ``rng`` で決定的に
      サンプルし、run_game の消費列の再現性を保つ)。
    """

    def __init__(self, net: ActorCritic, spec: ObservationSpec,
                 catalog: ActionCatalog, device: torch.device,
                 greedy: bool = True) -> None:
        self.net = net
        self.spec = spec
        self.catalog = catalog
        self.device = device
        self.greedy = greedy

    # ------------------------------------------------------------
    def choose(self, state: GameState, actions: List[Action],
               rng: random.Random) -> Action:
        # 単一合法手は評価不要(run_game は元来 1 手のとき choose を呼ばないが安全側)。
        if len(actions) == 1:
            return actions[0]

        perspective = state.to_act()  # 学習時の視点=手番 agent(perspective onehot, 12.3)
        obs = self.spec.encode(state, perspective)
        mask = legal_mask(state, self.catalog)

        obs_t = torch.as_tensor(obs, device=self.device).unsqueeze(0)
        mask_t = torch.as_tensor(mask, device=self.device).unsqueeze(0)
        with torch.no_grad():
            logits, _ = self.net(obs_t)
            ml = masked_logits(logits, mask_t)[0]

        if self.greedy:
            index = int(torch.argmax(ml).item())
        else:
            # 渡された rng で決定的にサンプル(numpy 確率 + rng.choices)。
            probs = torch.softmax(ml, dim=-1).cpu().numpy().astype(np.float64)
            legal = np.nonzero(mask)[0]
            weights = probs[legal]
            total = float(weights.sum())
            if total <= 0.0:  # 数値異常時は一様(実質起きない)
                index = int(rng.choice(list(legal)))
            else:
                index = int(rng.choices(list(legal), weights=list(weights), k=1)[0])

        action = action_for(state, index, self.catalog, actions)
        if action is None:
            # マスク一致が取れない異常時のフォールバック(学習を止めない)。
            return rng.choice(actions)
        return action
