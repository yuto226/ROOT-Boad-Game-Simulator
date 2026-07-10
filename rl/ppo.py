"""PPO self-play 学習ループ本体(DESIGN.md 13.3)。

- **収集**: E 個の :class:`~rl.env.RootEnv`(``auto_single=True``)を並べ、agent の
  区別なく「意思決定点=1ステップ」として遷移を集める。NN 推論は env 間でバッチする。
- **報酬とGAE**: 報酬は終局時 ±1(タイムアウト0)のみ。GAE は **agent 別の
  トラジェクトリ列**(同一 env 内で自分の意思決定点だけを繋いだ列)に対して計算する
  (γ=1.0, λ=0.95 を既定)。イテレーション途中で切れた列は value でブートストラップ。
- **PPO 更新**: clip=0.2, epochs=4, minibatch=256, lr=2.5e-4, value 係数 0.5(clip 付き),
  entropy 係数 0.01, grad clip 0.5。
- **対戦相手**: 純 self-play(両席同一の最新ネット)。

torch はこのモジュールに閉じる。env の seed はイテレーションごとに決定的に生成し、
学習用サンプリングは torch の rng に従う(乱数系列の分離, 13.3)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch

from engine.types import FactionId

from .env import RootEnv
from .net import ActorCritic, masked_logits


@dataclass
class PPOConfig:
    """PPO ハイパーパラメータ(DESIGN.md 13.3)。"""

    factions: Tuple[FactionId, ...]
    num_envs: int = 8
    rollout_steps: int = 2048          # 1イテレーションの総ステップ数(全 env 合算)
    gamma: float = 1.0
    gae_lambda: float = 0.95
    clip_coef: float = 0.2
    update_epochs: int = 4
    minibatch_size: int = 256
    lr: float = 2.5e-4
    vf_coef: float = 0.5
    ent_coef: float = 0.01
    max_grad_norm: float = 0.5
    max_turns: int = 300
    seed: int = 0                      # env seed 系列と torch rng の基点


# ------------------------------------------------------------
# トラジェクトリ(env×agent 別。1エピソードでの自分の意思決定点の列)
# ------------------------------------------------------------
class _Trajectory:
    """1エピソード・1 agent 分の遷移列(13.3)。

    obs/mask/action/logp/value を意思決定点順に貯め、報酬は途中 0・終局時に
    最後の遷移へ ±1 を書き込む。切れた列は ``bootstrap`` に value を持つ。
    """

    __slots__ = ("obs", "mask", "action", "logp", "value",
                 "reward", "done", "bootstrap")

    def __init__(self) -> None:
        self.obs: List[np.ndarray] = []
        self.mask: List[np.ndarray] = []
        self.action: List[int] = []
        self.logp: List[float] = []
        self.value: List[float] = []
        self.reward: List[float] = []
        self.done: bool = False        # True=終局(最後の遷移が終端)
        self.bootstrap: float = 0.0    # done=False のときの次 value

    def __len__(self) -> int:
        return len(self.obs)

    def add(self, obs: np.ndarray, mask: np.ndarray, action: int,
            logp: float, value: float) -> None:
        self.obs.append(obs)
        self.mask.append(mask)
        self.action.append(action)
        self.logp.append(logp)
        self.value.append(value)
        self.reward.append(0.0)


def compute_gae(values: List[float], rewards: List[float], done: bool,
                bootstrap: float, gamma: float, lam: float
                ) -> Tuple[List[float], List[float]]:
    """1トラジェクトリの GAE(advantage)とリターンを返す(DESIGN.md 13.3)。

    途中遷移は非終端・報酬 0、最後の遷移のみ終局(done=True, 次 value=0)または
    ブートストラップ(done=False, 次 value=bootstrap)。
    """
    n = len(values)
    adv = [0.0] * n
    last = 0.0
    for i in range(n - 1, -1, -1):
        if i == n - 1:
            next_value = 0.0 if done else bootstrap
            next_nonterminal = 0.0 if done else 1.0
        else:
            next_value = values[i + 1]
            next_nonterminal = 1.0  # 途中の意思決定点は終端ではない
        delta = rewards[i] + gamma * next_value * next_nonterminal - values[i]
        last = delta + gamma * lam * next_nonterminal * last
        adv[i] = last
    returns = [adv[i] + values[i] for i in range(n)]
    return adv, returns


@dataclass
class RolloutStats:
    """1イテレーションの収集統計(ログ用)。"""

    episodes: int = 0
    ep_len_sum: int = 0
    seat_wins: Dict[int, int] = field(default_factory=dict)  # seat index -> 勝利数
    draws: int = 0

    def ep_len_mean(self) -> float:
        return self.ep_len_sum / self.episodes if self.episodes else 0.0

    def seat_winrate(self, seat: int) -> float:
        return self.seat_wins.get(seat, 0) / self.episodes if self.episodes else 0.0


class _Worker:
    """1 env と現在エピソードの per-agent トラジェクトリを束ねる。"""

    def __init__(self, env: RootEnv) -> None:
        self.env = env
        self.agents: Tuple[str, ...] = tuple(env.possible_agents)
        self.traj: Dict[str, _Trajectory] = {a: _Trajectory() for a in self.agents}
        self.ep_steps: int = 0  # 現エピソードの意思決定点数(両席合算)

    def reset_episode(self) -> None:
        self.traj = {a: _Trajectory() for a in self.agents}
        self.ep_steps = 0


class PPOTrainer:
    """PPO self-play トレーナ(DESIGN.md 13.3)。"""

    def __init__(self, net: ActorCritic, optimizer: torch.optim.Optimizer,
                 config: PPOConfig, device: torch.device) -> None:
        self.net = net
        self.optimizer = optimizer
        self.cfg = config
        self.device = device
        self.total_steps = 0
        # env の seed 系列(イテレーションごとに決定的に生成, 13.3)。
        self._next_seed = config.seed * 1_000_003 + 1
        self.workers: List[_Worker] = [
            _Worker(RootEnv(config.factions, max_turns=config.max_turns,
                            auto_single=True, seed=self._alloc_seed()))
            for _ in range(config.num_envs)
        ]
        self._seat_of: Dict[str, int] = {
            f.value: i for i, f in enumerate(config.factions)}

    # ------------------------------------------------------------
    def _alloc_seed(self) -> int:
        """決定的な env seed を1つ払い出す(13.3)。"""
        s = self._next_seed
        self._next_seed = (self._next_seed * 1_103_515_245 + 12_345) & 0x7FFFFFFF
        return s

    # ------------------------------------------------------------
    def collect(self) -> Tuple[Dict[str, torch.Tensor], RolloutStats]:
        """T ステップ(全 env 合算)を収集しバッチ化して返す(13.3)。"""
        cfg = self.cfg
        stats = RolloutStats()
        completed: List[_Trajectory] = []
        steps = 0

        while steps < cfg.rollout_steps:
            # --- env 間バッチ推論(13.3): 各 env の現手番 agent の obs/mask を集める ---
            actors = [w.env.agent_selection for w in self.workers]
            obs_masks = [w.env.observe(a) for w, a in zip(self.workers, actors)]
            obs_batch = np.stack([om["observation"] for om in obs_masks])
            mask_batch = np.stack([om["action_mask"] for om in obs_masks])
            obs_t = torch.as_tensor(obs_batch, device=self.device)
            mask_t = torch.as_tensor(mask_batch, device=self.device)
            with torch.no_grad():
                action_t, logp_t, value_t = self.net.act(obs_t, mask_t)
            actions = action_t.cpu().numpy()
            logps = logp_t.cpu().numpy()
            values = value_t.cpu().numpy()

            for i, w in enumerate(self.workers):
                actor = actors[i]
                w.traj[actor].add(obs_batch[i], mask_batch[i], int(actions[i]),
                                  float(logps[i]), float(values[i]))
                w.ep_steps += 1
                w.env.step(int(actions[i]))
                steps += 1

                if w.env._done:
                    self._flush_episode(w, completed, stats)
                    w.reset_episode()
                    w.env.reset(self._alloc_seed())

        # --- 途中で切れた列を value でブートストラップして回収(13.3) ---
        self._bootstrap_open(completed)

        self.total_steps += steps
        batch = self._build_batch(completed)
        return batch, stats

    # ------------------------------------------------------------
    def _flush_episode(self, w: _Worker, completed: List[_Trajectory],
                       stats: RolloutStats) -> None:
        """終局した env の per-agent トラジェクトリを確定して回収する(13.3)。"""
        env = w.env
        info = env.infos[w.agents[0]]
        winner = info.get("winner")
        stats.episodes += 1
        stats.ep_len_sum += w.ep_steps
        if winner is None:
            stats.draws += 1
        else:
            seat = self._seat_of.get(winner)
            if seat is not None:
                stats.seat_wins[seat] = stats.seat_wins.get(seat, 0) + 1
        for a in w.agents:
            tr = w.traj[a]
            if len(tr) == 0:
                continue
            tr.reward[-1] = float(env.rewards[a])  # 終局時 ±1(タイムアウト0, 12.4)
            tr.done = True
            completed.append(tr)

    # ------------------------------------------------------------
    def _bootstrap_open(self, completed: List[_Trajectory]) -> None:
        """収集打ち切り時点で継続中の列を value ブートストラップする(13.3)。"""
        pending: List[Tuple[_Trajectory, np.ndarray]] = []
        for w in self.workers:
            if w.env._done:
                continue  # 直前に flush 済み(次エピソードは空)
            for a in w.agents:
                tr = w.traj[a]
                if len(tr) == 0:
                    continue
                # a 視点の現在 obs(value のみ使うのでマスクは不要)
                obs = w.env.observe(a)["observation"]
                pending.append((tr, obs))
        if not pending:
            return
        obs_t = torch.as_tensor(
            np.stack([o for _, o in pending]), device=self.device)
        vals = self.net.value_only(obs_t).cpu().numpy()
        for (tr, _), v in zip(pending, vals):
            tr.done = False
            tr.bootstrap = float(v)
            completed.append(tr)

    # ------------------------------------------------------------
    def _build_batch(self, trajs: List[_Trajectory]) -> Dict[str, torch.Tensor]:
        """全トラジェクトリを GAE 済みの平坦テンソルへ(13.3)。"""
        cfg = self.cfg
        obs_l: List[np.ndarray] = []
        mask_l: List[np.ndarray] = []
        act_l: List[int] = []
        logp_l: List[float] = []
        val_l: List[float] = []
        adv_l: List[float] = []
        ret_l: List[float] = []
        for tr in trajs:
            adv, ret = compute_gae(tr.value, tr.reward, tr.done, tr.bootstrap,
                                   cfg.gamma, cfg.gae_lambda)
            obs_l.extend(tr.obs)
            mask_l.extend(tr.mask)
            act_l.extend(tr.action)
            logp_l.extend(tr.logp)
            val_l.extend(tr.value)
            adv_l.extend(adv)
            ret_l.extend(ret)

        dev = self.device
        batch = {
            "obs": torch.as_tensor(np.stack(obs_l), device=dev),
            "mask": torch.as_tensor(np.stack(mask_l), device=dev),
            "action": torch.as_tensor(np.asarray(act_l, dtype=np.int64), device=dev),
            "logp": torch.as_tensor(np.asarray(logp_l, dtype=np.float32), device=dev),
            "value": torch.as_tensor(np.asarray(val_l, dtype=np.float32), device=dev),
            "adv": torch.as_tensor(np.asarray(adv_l, dtype=np.float32), device=dev),
            "ret": torch.as_tensor(np.asarray(ret_l, dtype=np.float32), device=dev),
        }
        return batch

    # ------------------------------------------------------------
    def update(self, batch: Dict[str, torch.Tensor]) -> Dict[str, float]:
        """PPO 更新を epochs×minibatch 回す(DESIGN.md 13.3)。"""
        cfg = self.cfg
        n = batch["obs"].shape[0]
        # advantage 正規化(バッチ全体)
        adv = batch["adv"]
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)

        pg_losses: List[float] = []
        v_losses: List[float] = []
        entropies: List[float] = []
        kls: List[float] = []
        clipfracs: List[float] = []

        idx = np.arange(n)
        for _ in range(cfg.update_epochs):
            np.random.shuffle(idx)
            for start in range(0, n, cfg.minibatch_size):
                mb = idx[start:start + cfg.minibatch_size]
                mb_t = torch.as_tensor(mb, device=self.device)
                new_logp, entropy, new_value = self.net.evaluate_actions(
                    batch["obs"][mb_t], batch["mask"][mb_t], batch["action"][mb_t])
                logratio = new_logp - batch["logp"][mb_t]
                ratio = torch.exp(logratio)
                mb_adv = adv[mb_t]

                # policy loss(clip)
                pg1 = -mb_adv * ratio
                pg2 = -mb_adv * torch.clamp(ratio, 1.0 - cfg.clip_coef,
                                            1.0 + cfg.clip_coef)
                pg_loss = torch.max(pg1, pg2).mean()

                # value loss(clip 付き, 13.3)
                old_value = batch["value"][mb_t]
                ret = batch["ret"][mb_t]
                v_clipped = old_value + torch.clamp(
                    new_value - old_value, -cfg.clip_coef, cfg.clip_coef)
                v_loss = 0.5 * torch.max((new_value - ret) ** 2,
                                         (v_clipped - ret) ** 2).mean()

                ent = entropy.mean()
                loss = pg_loss + cfg.vf_coef * v_loss - cfg.ent_coef * ent

                self.optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.net.parameters(),
                                               cfg.max_grad_norm)
                self.optimizer.step()

                with torch.no_grad():
                    approx_kl = ((ratio - 1.0) - logratio).mean()  # Schulman近似
                    clipfrac = (torch.abs(ratio - 1.0) > cfg.clip_coef).float().mean()
                pg_losses.append(float(pg_loss.item()))
                v_losses.append(float(v_loss.item()))
                entropies.append(float(ent.item()))
                kls.append(float(approx_kl.item()))
                clipfracs.append(float(clipfrac.item()))

        return {
            "policy_loss": float(np.mean(pg_losses)),
            "value_loss": float(np.mean(v_losses)),
            "entropy": float(np.mean(entropies)),
            "approx_kl": float(np.mean(kls)),
            "clipfrac": float(np.mean(clipfracs)),
            "batch_size": n,
        }
