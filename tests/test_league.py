"""フェーズ6c(後半)リーグ戦の検証(DESIGN.md 16.6-1)。

torch 未導入環境では skip する(rl.league / rl.ppo は torch 必須, 13.1 と同じ方針)。
システム python(torch なし)では自動 skip され、``.venv/bin/python`` でのみ実走する。

  (a) pool の add/上限間引き/sample の決定性(rng 固定)
  (b) league エピソードで凍結側 agent の遷移がバッファに入らないこと
      (collect 後の batch サイズ=学習側意思決定点数と一致)
  (c) --league-prob 0 が従来の純 self-play と同一挙動(同 seed で batch 一致)
  (d) _flush_episode の league 勝敗集計が env.infos の実データ形式(str winner)で
      正しく動く回帰テスト(16.4)。
"""
from __future__ import annotations

import pytest

try:
    import numpy as np
    import torch
    _HAVE_TORCH = True
except ImportError:  # pragma: no cover
    _HAVE_TORCH = False

pytestmark = pytest.mark.skipif(not _HAVE_TORCH, reason="torch 未導入(rl の学習系は torch 必須)")

from engine.types import FactionId

_FACTIONS = (FactionId.MARQUISE, FactionId.EYRIE)


# ============================================================
# 16.6-1(a) pool の add/上限間引き/sample の決定性(rng 固定)
# ============================================================
def test_pool_add_evict_sample_deterministic(tmp_path):
    from rl.league import OpponentPool
    from rl.net import ActorCritic

    def build_and_sample(run_dir):
        pool = OpponentPool(str(run_dir), pool_max=3)
        rng = np.random.default_rng(42)
        net = ActorCritic(obs_dim=8, action_size=5)
        meta_history = []
        for u in range(1, 7):
            pool.add(net, u, rng)
            meta_history.append(sorted(uid for uid, _ in pool.save_meta()))
        samples = [pool.sample(rng)[0] for _ in range(5)]
        return meta_history, samples

    dir1 = tmp_path / "run1"
    dir2 = tmp_path / "run2"
    dir1.mkdir()
    dir2.mkdir()
    hist1, samples1 = build_and_sample(dir1)
    hist2, samples2 = build_and_sample(dir2)

    assert hist1 == hist2, "同一 rng seed で add/間引きの履歴が一致しない"
    assert samples1 == samples2, "同一 rng seed で sample の系列が一致しない"
    # 上限 3 を超えたら常に間引かれ、3 件以下に保たれる(16.2)
    assert all(len(h) <= 3 for h in hist1)
    # 6 回 add したのに毎回 3 件のままではなく、間引きが実際に起きている
    assert len(hist1[-1]) == 3

    # 空プールでは sample が None を返す(16.2)
    empty_pool = OpponentPool(str(tmp_path / "empty"), pool_max=3)
    assert empty_pool.sample(np.random.default_rng(0)) is None

    # save_meta のファイルが実際にディスクへ保存されている(16.2)
    pool = OpponentPool(str(tmp_path / "diskcheck"), pool_max=3)
    pool.add(ActorCritic(obs_dim=8, action_size=5), 1, np.random.default_rng(0))
    (update, filename), = pool.save_meta()
    assert update == 1
    import os
    assert os.path.exists(os.path.join(str(tmp_path / "diskcheck"), "league", filename))


# ============================================================
# 16.6-1(b) league エピソードで凍結側 agent の遷移がバッファに入らないこと
# ============================================================
def test_league_frozen_side_excluded_from_buffer(tmp_path):
    from rl.catalog import ActionCatalog
    from rl.encoder import ObservationSpec
    from rl.league import OpponentPool
    from rl.net import build_net
    from rl.ppo import PPOConfig, PPOTrainer

    device = torch.device("cpu")
    torch.manual_seed(0)
    spec = ObservationSpec(_FACTIONS)
    catalog = ActionCatalog()
    net = build_net(spec.obs_dim, catalog.size, device)
    optimizer = torch.optim.Adam(net.parameters(), lr=1e-3)

    pool = OpponentPool(str(tmp_path), pool_max=5)
    pool.add(net, 1, np.random.default_rng(0))  # プールを非空にしておく(重みは何でもよい)

    cfg = PPOConfig(factions=_FACTIONS, num_envs=1, rollout_steps=6,
                    max_turns=300, seed=0, league_prob=1.0)
    trainer = PPOTrainer(net, optimizer, cfg, device, pool=pool)

    # league_prob=1.0 かつプール非空なので、__init__ 時点の _assign_opponent で
    # 必ず league 対戦相手が割り当たっているはず(16.3)。
    w = trainer.workers[0]
    assert w.opponent is not None, "league_prob=1.0 かつ pool 非空なのに opponent が割当たっていない"
    opp_agent = w.opponent[0]

    batch, stats = trainer.collect()

    # 凍結側(opp_agent)の遷移はバッファに入らない(16.3)。
    # rollout_steps=6・num_envs=1 という短い収集ではエピソードが完走しないため、
    # 収集終了時点の w.traj[opp_agent] を直接検査できる。
    assert len(w.traj[opp_agent]) == 0, "凍結側 agent の遷移が traj に入っている"

    # batch サイズ(GAE 済みトラジェクトリの平坦化後の行数)は
    # 「学習ネットの意思決定点数」= trainer.total_steps と一致する(16.3)。
    assert batch["obs"].shape[0] == trainer.total_steps
    assert batch["obs"].shape[0] > 0


# ============================================================
# 16.6-1(c) --league-prob 0 が従来の純 self-play と同一挙動(同 seed で batch 一致)
# ============================================================
def test_league_prob_zero_matches_pure_selfplay(tmp_path):
    from rl.catalog import ActionCatalog
    from rl.encoder import ObservationSpec
    from rl.league import OpponentPool
    from rl.net import build_net
    from rl.ppo import PPOConfig, PPOTrainer

    device = torch.device("cpu")
    spec = ObservationSpec(_FACTIONS)
    catalog = ActionCatalog()

    def make_trainer(pool):
        torch.manual_seed(7)  # net 初期化を両者で揃える
        net = build_net(spec.obs_dim, catalog.size, device)
        optimizer = torch.optim.Adam(net.parameters(), lr=1e-3)
        cfg = PPOConfig(factions=_FACTIONS, num_envs=2, rollout_steps=32,
                        max_turns=300, seed=3, league_prob=0.0)
        return PPOTrainer(net, optimizer, cfg, device, pool=pool)

    trainer_a = make_trainer(pool=None)

    pool = OpponentPool(str(tmp_path), pool_max=5)
    seed_net = build_net(spec.obs_dim, catalog.size, device)
    pool.add(seed_net, 1, np.random.default_rng(1))  # プールを非空にしても league_prob=0 なら無視される
    trainer_b = make_trainer(pool=pool)

    assert all(w.opponent is None for w in trainer_a.workers)
    assert all(w.opponent is None for w in trainer_b.workers)

    # torch の行動サンプリングはグローバル rng に従う(13.3)ため、collect() 直前に
    # 明示的に固定してから呼ぶ(そうしないと直前の build_net 呼び出し順の違いで
    # グローバル rng の消費量がずれ、サンプリング列が変わってしまう)。
    torch.manual_seed(123)
    batch_a, stats_a = trainer_a.collect()
    torch.manual_seed(123)
    batch_b, stats_b = trainer_b.collect()

    assert torch.equal(batch_a["obs"], batch_b["obs"])
    assert torch.equal(batch_a["mask"], batch_b["mask"])
    assert torch.equal(batch_a["action"], batch_b["action"])
    assert torch.allclose(batch_a["logp"], batch_b["logp"])
    assert stats_a.episodes == stats_b.episodes
    assert stats_a.league_episodes == 0
    assert stats_b.league_episodes == 0


# ============================================================
# 16.6-1(d) _flush_episode の league 勝敗集計が実データ形式(str winner)で正しく動く
#
# 回帰テスト: rl.env.RootEnv は infos[agent]["winner"] を FactionId ではなく
# 既に .value(str)で格納する(12.4)。_flush_episode 側で誤って winner.value と
# もう一度 .value を呼ぶと、実ゲームで league エピソードが終局するまで顕在化しない
# AttributeError になる(スモークで実際に踏んだ)。フルゲーム完走を待たずに直接検証する。
# ============================================================
def test_flush_episode_league_stats_str_winner():
    from rl.ppo import PPOTrainer, RolloutStats, _Trajectory, _Worker

    class _FakeEnv:
        def __init__(self, agents, winner, rewards):
            self.possible_agents = list(agents)
            self.infos = {a: {"winner": winner} for a in agents}
            self.rewards = rewards
            # _flush_episode は 12.7 以降 _cumulative_rewards との差分で残額を回収する。
            # このフェイクは終局1発なので、累積 = 終局 reward そのもの(shaping なし)。
            self._cumulative_rewards = dict(rewards)

    class _FakeTrainer:
        _seat_of = {"marquise": 0, "eyrie": 1}
        _flush_episode = PPOTrainer._flush_episode

    def make_worker(agents, winner, frozen_seat_agent, rewards):
        env = _FakeEnv(agents, winner, rewards)
        w = _Worker.__new__(_Worker)
        w.env = env
        w.agents = agents
        w.traj = {a: _Trajectory() for a in agents}
        w.last_cum = {a: 0.0 for a in agents}  # __new__ は __init__ を通らないため明示初期化(12.7)
        # 学習ネット側だけ 1 遷移追加(凍結側は常に空, 16.3)
        learner_agent = [a for a in agents if a != frozen_seat_agent][0]
        w.traj[learner_agent].add(np.zeros(1, dtype=np.float32),
                                  np.ones(1, dtype=np.bool_), 0, 0.0, 0.0)
        w.ep_steps = 5
        w.opponent = (frozen_seat_agent, None, 1)
        return w

    agents = ("marquise", "eyrie")
    trainer = _FakeTrainer()

    # 学習ネット(marquise)が勝利 -> league_wins += 1(winner は str "marquise")
    stats = RolloutStats()
    completed = []
    w_win = make_worker(agents, winner="marquise", frozen_seat_agent="eyrie",
                        rewards={"marquise": 1.0, "eyrie": -1.0})
    trainer._flush_episode(w_win, completed, stats)
    assert stats.league_episodes == 1
    assert stats.league_wins == 1
    assert stats.league_draws == 0
    assert len(completed) == 1  # marquise(学習ネット)側の traj のみ回収

    # 凍結ネット(eyrie)が勝利 -> league_wins は増えない
    stats2 = RolloutStats()
    completed2 = []
    w_lose = make_worker(agents, winner="eyrie", frozen_seat_agent="eyrie",
                         rewards={"marquise": -1.0, "eyrie": 1.0})
    trainer._flush_episode(w_lose, completed2, stats2)
    assert stats2.league_episodes == 1
    assert stats2.league_wins == 0
    assert stats2.league_draws == 0

    # 引き分け(winner=None)-> league_draws += 1
    stats3 = RolloutStats()
    completed3 = []
    w_draw = make_worker(agents, winner=None, frozen_seat_agent="eyrie",
                         rewards={"marquise": 0.0, "eyrie": 0.0})
    trainer._flush_episode(w_draw, completed3, stats3)
    assert stats3.league_episodes == 1
    assert stats3.league_wins == 0
    assert stats3.league_draws == 1

    # 全体集計(episodes/ep_len_sum/draws)は self-play・league 合算(16.4)
    assert stats.episodes == 1
    assert stats.ep_len_sum == 5
