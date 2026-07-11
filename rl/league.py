"""過去世代対戦相手プール OpponentPool(DESIGN.md 16.2)。

純 self-play の非定常性(忘却・循環)対策として、凍結した過去 :class:`~rl.net.ActorCritic`
のスナップショットを保持し、``rl.ppo.PPOTrainer.collect`` から一様サンプルして片席の
対戦相手として差し込む(16.3)。

torch はこのモジュールに閉じる(net.py 同様, 13.1)。
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import torch

from .net import ActorCritic


@dataclass
class _Snapshot:
    """1個の凍結スナップショット(16.2)。"""

    update: int
    filename: str
    net: ActorCritic


class OpponentPool:
    """凍結ネットのスナップショットプール(DESIGN.md 16.2)。

    - ``add``: 現ネットの deepcopy を凍結(eval + requires_grad_(False))して追加し、
      ``run_dir/league/snap_<update>.pt``(state_dict のみ)へ保存する。上限超過時は
      **プール全体からランダムに1つ間引く**(FIFO でなく履歴全体をほぼ一様にカバーする
      ため)。
    - ``sample``: 一様サンプル。空なら ``None``。
    - 間引き・サンプルの乱数は呼び出し側から明示的に ``rng``(``np.random.Generator``)
      を受け取る(``PPOTrainer`` の league 用 rng, 16.3)。決定性テスト(16.6-1a)で
      rng を固定して再現できるようにするための設計判断。
    """

    def __init__(self, run_dir: str, pool_max: int = 20) -> None:
        self.run_dir = run_dir
        self.pool_max = pool_max
        self.league_dir = os.path.join(run_dir, "league")
        self._snapshots: List[_Snapshot] = []

    # ------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._snapshots)

    # ------------------------------------------------------------
    def add(self, net: ActorCritic, update: int, rng: np.random.Generator) -> None:
        """現ネットを凍結して追加する。上限超過時はランダムに1つ間引く(16.2)。"""
        frozen = copy.deepcopy(net)
        frozen.eval()
        frozen.requires_grad_(False)
        os.makedirs(self.league_dir, exist_ok=True)
        filename = "snap_%d.pt" % update
        torch.save(frozen.state_dict(), os.path.join(self.league_dir, filename))
        self._snapshots.append(_Snapshot(update=update, filename=filename, net=frozen))
        if len(self._snapshots) > self.pool_max:
            idx = int(rng.integers(0, len(self._snapshots)))
            evicted = self._snapshots.pop(idx)
            # ディスクも削除(長期 run での蓄積防止, 16.2)。過去 ckpt の league_meta が
            # 参照していても resume 側の warn+skip(16.5)で吸収される。
            path = os.path.join(self.league_dir, evicted.filename)
            if os.path.exists(path):
                os.remove(path)

    # ------------------------------------------------------------
    def sample(self, rng: np.random.Generator
              ) -> Optional[Tuple[int, ActorCritic]]:
        """一様サンプルで ``(snapshot_id, net)`` を返す。空なら ``None``(16.2)。

        ``snapshot_id`` はスナップショット作成時の ``update``(collect 側で
        「同一スナップショットの推論をまとめてバッチ化する」ためのキーに使う, 16.3)。
        """
        if not self._snapshots:
            return None
        idx = int(rng.integers(0, len(self._snapshots)))
        snap = self._snapshots[idx]
        return snap.update, snap.net

    # ------------------------------------------------------------
    def save_meta(self) -> List[Tuple[int, str]]:
        """ckpt へ埋め込む resume 用メタ(``[(update, ファイル名), ...]``, 16.2)。"""
        return [(s.update, s.filename) for s in self._snapshots]

    # ------------------------------------------------------------
    @classmethod
    def load(cls, run_dir: str, meta: List[Tuple[int, str]], pool_max: int,
             obs_dim: int, action_size: int, device: torch.device) -> "OpponentPool":
        """resume 時に ``run_dir/league/`` からプールを再構築する(16.2, 16.5)。

        ファイル欠損は警告してスキップする(16.5)。
        """
        pool = cls(run_dir, pool_max)
        for update, filename in meta:
            path = os.path.join(pool.league_dir, filename)
            if not os.path.exists(path):
                print("warning: league snapshot missing, skip: %s" % path)
                continue
            net = ActorCritic(obs_dim, action_size).to(device)
            state = torch.load(path, map_location=device, weights_only=True)
            net.load_state_dict(state)
            net.eval()
            net.requires_grad_(False)
            pool._snapshots.append(_Snapshot(update=update, filename=filename, net=net))
        return pool
