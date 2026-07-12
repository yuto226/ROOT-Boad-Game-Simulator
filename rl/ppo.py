"""PPO self-play 学習ループ本体(DESIGN.md 13.3)。

- **収集**: E 個の :class:`~rl.env.RootEnv`(``auto_single=True``)を並べ、agent の
  区別なく「意思決定点=1ステップ」として遷移を集める。NN 推論は env 間でバッチする。
- **報酬とGAE**: 報酬は終局時 ±1(タイムアウト0)のみ。GAE は **agent 別の
  トラジェクトリ列**(同一 env 内で自分の意思決定点だけを繋いだ列)に対して計算する
  (γ=1.0, λ=0.95 を既定)。イテレーション途中で切れた列は value でブートストラップ。
- **PPO 更新**: clip=0.2, epochs=4, minibatch=256, lr=2.5e-4, value 係数 0.5(clip 付き),
  entropy 係数 0.01, grad clip 0.5。
- **対戦相手**: 純 self-play(両席同一の最新ネット)。``league_prob>0`` かつ
  :class:`~rl.league.OpponentPool` が非空なら、エピソード開始時に確率 ``league_prob``
  で片席を凍結した過去世代ネットに差し替える(リーグ戦, DESIGN.md 16.3)。

torch はこのモジュールに閉じる。env の seed はイテレーションごとに決定的に生成し、
学習用サンプリングは torch の rng に従う(乱数系列の分離, 13.3)。league 対戦相手の
抽選には専用の numpy rng を使い torch/env の乱数系列から分離する(16.3)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch

from engine.types import FactionId

from .env import RootEnv
from .league import OpponentPool
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
    league_prob: float = 0.0           # 過去世代凍結ネットに差し替える確率(0=無効, 16.5)
    vp_shaping: float = 0.0            # 自派閥 VP 増分×係数を毎 step 加算(0=無効, 12.4/12.7)
    build_shaping: float = 0.0         # EYRIE 建設欄ポテンシャルシェイピング係数(0=無効, 12.7)


# ------------------------------------------------------------
# トラジェクトリ(env×agent 別。1エピソードでの自分の意思決定点の列)
# ------------------------------------------------------------
class _Trajectory:
    """1エピソード・1 agent 分の遷移列(13.3, 12.7)。

    obs/mask/action/logp/value を意思決定点順に貯め、reward は追加時 0.0 で
    埋めておき、次の自分の意思決定点(または終局)で `_cumulative_rewards` の
    差分を1つ前の遷移へ書き込む(意思決定点間シェイピング回収, 12.7)。
    shaping が全て 0 のときは途中差分が常に 0 になり、終局差分が ±1(タイム
    アウト 0)のみになるため、従来(途中 0・終局のみ書き込み)と数値一致する。
    切れた列は ``bootstrap`` に value を持つ。
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
    """1イテレーションの収集統計(ログ用)。

    ``episodes`` / ``ep_len_sum`` / ``draws`` は self-play・league 両方を含む
    全エピソードの集計。``seat_wins`` は **self-play エピソードのみ**(既存の
    ``winrate_seat0/1`` の意味を変えないため, 16.4)。league エピソードは
    ``league_episodes`` / ``league_wins``(学習ネット視点)/ ``league_draws`` に
    別集計する。
    """

    episodes: int = 0
    ep_len_sum: int = 0
    seat_wins: Dict[int, int] = field(default_factory=dict)  # seat index -> 勝利数(self-play のみ)
    draws: int = 0
    league_episodes: int = 0
    league_wins: int = 0    # 学習ネット視点の勝利数
    league_draws: int = 0

    def ep_len_mean(self) -> float:
        return self.ep_len_sum / self.episodes if self.episodes else 0.0

    def seat_winrate(self, seat: int) -> float:
        # 分母は self-play エピソードのみ(league を含めると希釈される, 16.4)
        selfplay = self.episodes - self.league_episodes
        return self.seat_wins.get(seat, 0) / selfplay if selfplay else 0.0

    def league_winrate(self) -> float:
        return (self.league_wins / self.league_episodes
                if self.league_episodes else 0.0)


class _Worker:
    """1 env と現在エピソードの per-agent トラジェクトリを束ねる。"""

    def __init__(self, env: RootEnv) -> None:
        self.env = env
        self.agents: Tuple[str, ...] = tuple(env.possible_agents)
        self.traj: Dict[str, _Trajectory] = {a: _Trajectory() for a in self.agents}
        self.ep_steps: int = 0  # 現エピソードの意思決定点数(両席合算。学習・league 両方カウント, 16.3)
        # agent 別「直近の意思決定点時点での env._cumulative_rewards」(12.7)。
        # 次の意思決定点(または終局)でこの値との差分を1つ前の遷移へ書き込む。
        self.last_cum: Dict[str, float] = {a: 0.0 for a in self.agents}
        # league 対戦相手(16.3): None=純 self-play。非 None=(agent名, 凍結net, snapshot_id)。
        # 凍結側の意思決定点は traj に追加しない(バッファに入れない)。
        self.opponent: Optional[Tuple[str, ActorCritic, int]] = None

    def reset_episode(self) -> None:
        self.traj = {a: _Trajectory() for a in self.agents}
        self.ep_steps = 0
        self.last_cum = {a: 0.0 for a in self.agents}


def _collect_shaped_reward(w: "_Worker", agent: str) -> float:
    """agent の直近の意思決定点からの累積報酬差分を取り出す(12.7, 13.3)。

    ``env._cumulative_rewards[agent]``(毎 step 加算, 12.4)と ``w.last_cum[agent]``
    (前回この関数を呼んだ時点の値)の差分を返し、``last_cum`` を更新する。
    shaping が全て 0 なら途中差分は常に 0、終局差分は ±1(タイムアウト 0)のみになる。
    """
    cum = w.env._cumulative_rewards[agent]
    r = cum - w.last_cum[agent]
    w.last_cum[agent] = cum
    return r


class PPOTrainer:
    """PPO self-play トレーナ(DESIGN.md 13.3)。"""

    def __init__(self, net: ActorCritic, optimizer: torch.optim.Optimizer,
                 config: PPOConfig, device: torch.device,
                 pool: Optional[OpponentPool] = None) -> None:
        self.net = net
        self.optimizer = optimizer
        self.cfg = config
        self.device = device
        self.total_steps = 0
        self.pool = pool  # league 対戦相手プール(None=未使用, 16.3)
        # league 対戦相手の抽選専用 rng(torch/env の乱数系列と分離, 16.3)。
        # resume 時も再構築するのみで状態は保存しない(16.5: 抽選列が変わるのは許容)。
        self._league_rng: np.random.Generator = np.random.default_rng(config.seed + 1_000_003)
        # env の seed 系列(イテレーションごとに決定的に生成, 13.3)。
        self._next_seed = config.seed * 1_000_003 + 1
        self.workers: List[_Worker] = [
            _Worker(RootEnv(config.factions, max_turns=config.max_turns,
                            auto_single=True, seed=self._alloc_seed(),
                            vp_shaping=config.vp_shaping,
                            build_shaping=config.build_shaping,
                            shaping_gamma=config.gamma))
            for _ in range(config.num_envs)
        ]
        self._seat_of: Dict[str, int] = {
            f.value: i for i, f in enumerate(config.factions)}
        for w in self.workers:
            self._assign_opponent(w)

    # ------------------------------------------------------------
    def _alloc_seed(self) -> int:
        """決定的な env seed を1つ払い出す(13.3)。"""
        s = self._next_seed
        self._next_seed = (self._next_seed * 1_103_515_245 + 12_345) & 0x7FFFFFFF
        return s

    # ------------------------------------------------------------
    def _assign_opponent(self, w: _Worker) -> None:
        """エピソード開始時(reset 直後)に league 対戦相手を抽選する(16.3)。

        ``league_prob<=0`` または pool が未設定/空なら常に純 self-play(``opponent=None``)。
        それ以外は確率 ``league_prob`` で発火し、席(0/1)を一様に選んで凍結ネットを割当てる。
        """
        w.opponent = None
        if self.cfg.league_prob <= 0 or self.pool is None or len(self.pool) == 0:
            return
        if self._league_rng.random() >= self.cfg.league_prob:
            return
        seat = int(self._league_rng.integers(0, len(w.agents)))
        sampled = self.pool.sample(self._league_rng)
        if sampled is None:
            return
        snapshot_id, net = sampled
        w.opponent = (w.agents[seat], net, snapshot_id)

    # ------------------------------------------------------------
    def collect(self) -> Tuple[Dict[str, torch.Tensor], RolloutStats]:
        """T ステップ(学習ネットの意思決定点のみ合算)を収集しバッチ化して返す(13.3, 16.3)。

        league 対戦相手が割り当たった env は、その席の手番のときだけ凍結ネットで
        推論する(sample で行動、バッファには入れない)。``steps``(rollout_steps の
        カウンタ)は学習ネットの意思決定点のみ進む(16.3)。
        """
        cfg = self.cfg
        stats = RolloutStats()
        completed: List[_Trajectory] = []
        steps = 0

        while steps < cfg.rollout_steps:
            actors = [w.env.agent_selection for w in self.workers]

            # --- 学習ネット担当と凍結ネット担当の env を分ける(16.3) ---
            learner_idx: List[int] = []
            frozen_idx: List[int] = []
            for i, w in enumerate(self.workers):
                if w.opponent is not None and w.opponent[0] == actors[i]:
                    frozen_idx.append(i)
                else:
                    learner_idx.append(i)

            actions: List[int] = [0] * len(self.workers)

            # --- 学習ネット分: 従来どおり1バッチ(13.3) ---
            if learner_idx:
                obs_masks = [self.workers[i].env.observe(actors[i]) for i in learner_idx]
                obs_batch = np.stack([om["observation"] for om in obs_masks])
                mask_batch = np.stack([om["action_mask"] for om in obs_masks])
                obs_t = torch.as_tensor(obs_batch, device=self.device)
                mask_t = torch.as_tensor(mask_batch, device=self.device)
                with torch.no_grad():
                    action_t, logp_t, value_t = self.net.act(obs_t, mask_t)
                a_np = action_t.cpu().numpy()
                logp_np = logp_t.cpu().numpy()
                value_np = value_t.cpu().numpy()
                for k, i in enumerate(learner_idx):
                    w = self.workers[i]
                    actor = actors[i]
                    tr = w.traj[actor]
                    # 新しい意思決定点を作る直前に、直近の意思決定点からの累積報酬
                    # 差分を1つ前の遷移へ書き込む(12.7)。列の先頭(len==0)なら
                    # 書き込み先がないので last_cum のベースライン更新のみ。
                    r = _collect_shaped_reward(w, actor)
                    if len(tr) > 0:
                        tr.reward[-1] = r
                    tr.add(obs_batch[k], mask_batch[k], int(a_np[k]),
                           float(logp_np[k]), float(value_np[k]))
                    w.ep_steps += 1
                    actions[i] = int(a_np[k])
                    steps += 1  # 学習ネットの意思決定点のみ進める(16.3)

            # --- 凍結ネット分: snapshot_id ごとにまとめて no_grad 推論(16.3) ---
            if frozen_idx:
                groups: Dict[int, List[int]] = {}
                for i in frozen_idx:
                    snap_id = self.workers[i].opponent[2]
                    groups.setdefault(snap_id, []).append(i)
                for snap_id, idxs in groups.items():
                    frozen_net = self.workers[idxs[0]].opponent[1]
                    obs_masks = [self.workers[i].env.observe(actors[i]) for i in idxs]
                    obs_batch = np.stack([om["observation"] for om in obs_masks])
                    mask_batch = np.stack([om["action_mask"] for om in obs_masks])
                    obs_t = torch.as_tensor(obs_batch, device=self.device)
                    mask_t = torch.as_tensor(mask_batch, device=self.device)
                    with torch.no_grad():
                        # sample で行動(greedy にしない=多様性維持, 16.3)。
                        action_t, _, _ = frozen_net.act(obs_t, mask_t)
                    a_np = action_t.cpu().numpy()
                    for k, i in enumerate(idxs):
                        actions[i] = int(a_np[k])
                        self.workers[i].ep_steps += 1  # 意思決定点数のみ数える。traj には入れない(16.3)

            # --- 全 env に行動を適用(16.3) ---
            for i, w in enumerate(self.workers):
                w.env.step(actions[i])
                if w.env._done:
                    self._flush_episode(w, completed, stats)
                    w.reset_episode()
                    w.env.reset(self._alloc_seed())
                    self._assign_opponent(w)

        # --- 途中で切れた列を value でブートストラップして回収(13.3) ---
        self._bootstrap_open(completed)

        self.total_steps += steps
        batch = self._build_batch(completed)
        return batch, stats

    # ------------------------------------------------------------
    def _flush_episode(self, w: _Worker, completed: List[_Trajectory],
                       stats: RolloutStats) -> None:
        """終局した env の per-agent トラジェクトリを確定して回収する(13.3, 16.4)。

        self-play エピソードは従来どおり ``seat_wins`` へ、league エピソードは
        ``league_episodes/league_wins(学習ネット視点)/league_draws`` へ分離して
        計上する(16.4)。``episodes``/``ep_len_sum``/``draws`` は両方を含む全体集計。
        """
        env = w.env
        info = env.infos[w.agents[0]]
        winner = info.get("winner")  # env.py が既に .value(str)へ変換済み(12.4)
        stats.episodes += 1
        stats.ep_len_sum += w.ep_steps
        if w.opponent is None:
            # 純 self-play(16.4: 既存 seat_wins/winrate_seat0/1 の意味は変えない)
            if winner is None:
                stats.draws += 1
            else:
                seat = self._seat_of.get(winner)
                if seat is not None:
                    stats.seat_wins[seat] = stats.seat_wins.get(seat, 0) + 1
        else:
            # league: 片席が凍結ネット(16.4)
            opp_agent = w.opponent[0]
            stats.league_episodes += 1
            if winner is None:
                stats.draws += 1
                stats.league_draws += 1
            elif winner != opp_agent:
                stats.league_wins += 1  # 学習ネット側が勝利
        for a in w.agents:
            tr = w.traj[a]
            if len(tr) == 0:
                continue
            # 最後の意思決定点以降の残額(終局 ±1/タイムアウト0 + 遅れて発生した
            # shaping)を累積報酬差分で回収する(12.7)。shaping が全て 0 のときは
            # ±1(タイムアウト0)のみになり、従来の `float(env.rewards[a])` と一致する。
            tr.reward[-1] = _collect_shaped_reward(w, a)
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
