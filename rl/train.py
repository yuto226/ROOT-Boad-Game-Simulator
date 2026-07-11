"""PPO self-play 学習 CLI エントリ(DESIGN.md 13.3 / 13.4)。

  .venv/bin/python -m rl.train --factions marquise,eyrie --total-steps 20000

チェックポイント ``rl_runs/<run名>/ckpt_<update>.pt``(model+optimizer+設定+総ステップ)、
``--resume`` で再開。ログは CSV(``rl_runs/<run名>/log.csv``)。評価は ``--eval-every``
更新ごとに vs RandomBot / vs HeuristicBot を各席で行い ``eval.csv`` へ書く。
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from typing import List, Optional

import numpy as np
import torch

from engine.types import FactionId

from .catalog import CATALOG_VERSION, ActionCatalog
from .encoder import ObservationSpec
from .eval import evaluate_both_seats, parse_factions, select_device
from .net import build_net
from .ppo import PPOConfig, PPOTrainer

_LOG_FIELDS = [
    "update", "steps", "ep_len_mean", "episodes",
    "winrate_seat0", "winrate_seat1", "draws",
    "policy_loss", "value_loss", "entropy", "approx_kl", "clipfrac",
    "sec_per_update", "steps_per_sec",
]
_EVAL_FIELDS = [
    "update", "steps", "opponent", "learn_seat", "faction",
    "games", "wins", "draws", "winrate", "vp_mean",
]


def _csv_writer(path: str, fields: List[str]):
    """追記用 CSV を開く。新規ならヘッダを書く。"""
    exists = os.path.exists(path)
    fh = open(path, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(fh, fieldnames=fields)
    if not exists:
        writer.writeheader()
    return fh, writer


def _save_ckpt(path: str, trainer: PPOTrainer, update: int,
               factions, cfg: PPOConfig) -> None:
    """model+optimizer+設定+総ステップを保存する(13.3)。"""
    torch.save({
        "model": trainer.net.state_dict(),
        "optimizer": trainer.optimizer.state_dict(),
        "update": update,
        "total_steps": trainer.total_steps,
        "next_seed": trainer._next_seed,
        "factions": [f.value for f in factions],
        "obs_dim": trainer.net.obs_dim,
        "action_size": trainer.net.action_size,
        "catalog_version": CATALOG_VERSION,
        "config": {
            "num_envs": cfg.num_envs, "rollout_steps": cfg.rollout_steps,
            "gamma": cfg.gamma, "gae_lambda": cfg.gae_lambda,
            "clip_coef": cfg.clip_coef, "update_epochs": cfg.update_epochs,
            "minibatch_size": cfg.minibatch_size, "lr": cfg.lr,
            "vf_coef": cfg.vf_coef, "ent_coef": cfg.ent_coef,
            "max_grad_norm": cfg.max_grad_norm, "max_turns": cfg.max_turns,
            "seed": cfg.seed,
        },
    }, path)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Root PPO self-play 学習(DESIGN.md 13.3)")
    parser.add_argument("--factions", type=str, default="marquise,eyrie",
                         help="2人戦固定(既定 marquise vs eyrie, 13.1)")
    parser.add_argument("--total-steps", type=int, default=1_000_000)
    parser.add_argument("--num-envs", type=int, default=8)
    parser.add_argument("--rollout-steps", type=int, default=2048)
    parser.add_argument("--update-epochs", type=int, default=4)
    parser.add_argument("--minibatch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=2.5e-4)
    parser.add_argument("--gamma", type=float, default=1.0)
    parser.add_argument("--gae-lambda", type=float, default=0.95)
    parser.add_argument("--clip-coef", type=float, default=0.2)
    parser.add_argument("--vf-coef", type=float, default=0.5)
    parser.add_argument("--ent-coef", type=float, default=0.01)
    parser.add_argument("--max-grad-norm", type=float, default=0.5)
    parser.add_argument("--max-turns", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", type=str, default="auto",
                         help="auto=cuda>mps>cpu(13.6)")
    parser.add_argument("--run-name", type=str, default="run")
    parser.add_argument("--runs-dir", type=str, default="rl_runs")
    parser.add_argument("--save-every", type=int, default=10, help="N 更新ごとに ckpt 保存")
    parser.add_argument("--eval-every", type=int, default=10,
                         help="N 更新ごとに vs Random/Heuristic 評価(0=無効, 13.4)")
    parser.add_argument("--eval-games", type=int, default=32)
    parser.add_argument("--resume", type=str, default=None, help="再開する ckpt パス")
    args = parser.parse_args(argv)

    factions = parse_factions(args.factions)
    device = select_device(args.device)
    torch.manual_seed(args.seed)  # 学習用サンプリングは torch の rng(13.3)
    np.random.seed(args.seed)     # minibatch シャッフル用

    run_dir = os.path.join(args.runs_dir, args.run_name)
    os.makedirs(run_dir, exist_ok=True)

    spec = ObservationSpec(factions)
    catalog = ActionCatalog()
    net = build_net(spec.obs_dim, catalog.size, device)
    optimizer = torch.optim.Adam(net.parameters(), lr=args.lr)

    cfg = PPOConfig(
        factions=factions, num_envs=args.num_envs, rollout_steps=args.rollout_steps,
        gamma=args.gamma, gae_lambda=args.gae_lambda, clip_coef=args.clip_coef,
        update_epochs=args.update_epochs, minibatch_size=args.minibatch_size,
        lr=args.lr, vf_coef=args.vf_coef, ent_coef=args.ent_coef,
        max_grad_norm=args.max_grad_norm, max_turns=args.max_turns, seed=args.seed,
    )
    trainer = PPOTrainer(net, optimizer, cfg, device)

    start_update = 0
    if args.resume:
        ckpt = torch.load(args.resume, map_location=device, weights_only=False)
        ckpt_catalog_version = ckpt.get("catalog_version")
        if ckpt_catalog_version != CATALOG_VERSION:
            raise RuntimeError(
                "resume failed: checkpoint %s has catalog_version=%r but current "
                "rl.catalog.CATALOG_VERSION=%d. Action catalog changed incompatibly "
                "(e.g. dominance-card actions added in 14.7) — old checkpoints cannot "
                "be resumed across a catalog version bump."
                % (args.resume, ckpt_catalog_version, CATALOG_VERSION))
        ckpt_action_size = ckpt.get("action_size")
        if ckpt_action_size != catalog.size:
            raise RuntimeError(
                "resume failed: checkpoint %s has action_size=%r but current "
                "ActionCatalog().size=%d. This should not happen when catalog_version "
                "matches — check rl/catalog.py for nondeterminism."
                % (args.resume, ckpt_action_size, catalog.size))
        net.load_state_dict(ckpt["model"])
        optimizer.load_state_dict(ckpt["optimizer"])
        trainer.total_steps = int(ckpt["total_steps"])
        trainer._next_seed = int(ckpt.get("next_seed", trainer._next_seed))
        start_update = int(ckpt["update"])
        print("resumed from %s (update=%d total_steps=%d)"
              % (args.resume, start_update, trainer.total_steps))

    log_fh, log_writer = _csv_writer(os.path.join(run_dir, "log.csv"), _LOG_FIELDS)
    eval_fh, eval_writer = _csv_writer(os.path.join(run_dir, "eval.csv"), _EVAL_FIELDS)

    print("run=%s device=%s obs_dim=%d action_size=%d factions=%s"
          % (run_dir, device, spec.obs_dim, catalog.size, [f.value for f in factions]))

    update = start_update
    try:
        while trainer.total_steps < args.total_steps:
            update += 1
            t0 = time.perf_counter()
            batch, stats = trainer.collect()
            metrics = trainer.update(batch)
            dt = time.perf_counter() - t0
            steps_per_sec = metrics["batch_size"] / dt if dt > 0 else 0.0

            row = {
                "update": update, "steps": trainer.total_steps,
                "ep_len_mean": round(stats.ep_len_mean(), 2),
                "episodes": stats.episodes,
                "winrate_seat0": round(stats.seat_winrate(0), 4),
                "winrate_seat1": round(stats.seat_winrate(1), 4),
                "draws": stats.draws,
                "policy_loss": round(metrics["policy_loss"], 5),
                "value_loss": round(metrics["value_loss"], 5),
                "entropy": round(metrics["entropy"], 5),
                "approx_kl": round(metrics["approx_kl"], 6),
                "clipfrac": round(metrics["clipfrac"], 4),
                "sec_per_update": round(dt, 2),
                "steps_per_sec": round(steps_per_sec, 1),
            }
            log_writer.writerow(row)
            log_fh.flush()
            print("upd %d steps %d eplen %.1f ep %d wr0 %.2f wr1 %.2f "
                  "ent %.3f kl %.4f ploss %.3f vloss %.3f %.0f st/s"
                  % (update, trainer.total_steps, stats.ep_len_mean(),
                     stats.episodes, stats.seat_winrate(0), stats.seat_winrate(1),
                     metrics["entropy"], metrics["approx_kl"],
                     metrics["policy_loss"], metrics["value_loss"], steps_per_sec))

            if args.save_every > 0 and update % args.save_every == 0:
                _save_ckpt(os.path.join(run_dir, "ckpt_%d.pt" % update),
                           trainer, update, factions, cfg)

            if args.eval_every > 0 and update % args.eval_every == 0:
                net.eval()
                for opponent in ("random", "heuristic"):
                    rows = evaluate_both_seats(
                        net, spec, catalog, device, factions, opponent,
                        args.eval_games, base_seed=args.seed, greedy=True)
                    for r in rows:
                        eval_writer.writerow({
                            "update": update, "steps": trainer.total_steps,
                            "opponent": opponent, "learn_seat": r["learn_seat"],
                            "faction": factions[r["learn_seat"]].value,
                            "games": r["games"], "wins": r["wins"],
                            "draws": r["draws"], "winrate": round(r["winrate"], 4),
                            "vp_mean": round(r["vp_mean"], 2),
                        })
                    print("  eval vs %-9s winrate seat0=%.3f seat1=%.3f"
                          % (opponent, rows[0]["winrate"],
                             rows[1]["winrate"] if len(rows) > 1 else float("nan")))
                eval_fh.flush()
                net.train()

        # 最終 ckpt
        _save_ckpt(os.path.join(run_dir, "ckpt_%d.pt" % update),
                   trainer, update, factions, cfg)
        print("done: %d updates, %d steps" % (update, trainer.total_steps))
    finally:
        log_fh.close()
        eval_fh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
