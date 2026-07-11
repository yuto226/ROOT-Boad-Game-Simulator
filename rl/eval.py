"""学習済みネットの単独評価コマンド+評価ヘルパ(DESIGN.md 13.4)。

``NNPolicy`` を既存 ``run_game`` に差し込み、vs RandomBot / vs HeuristicBot の
勝率を測る。train.py の ``--eval-every`` からも同じ関数を再利用する。

  python -m rl.eval --ckpt rl_runs/smoke/ckpt_10.pt --games 32 --opponent random
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional, Tuple

import torch

from bots.heuristic import HeuristicBot
from bots.random_bot import RandomBot
from engine.game import run_game
from engine.types import FactionId

from .catalog import CATALOG_VERSION, ActionCatalog
from .encoder import ObservationSpec
from .net import build_net
from .nn_policy import NNPolicy


# ------------------------------------------------------------
def select_device(name: str) -> torch.device:
    """``--device`` 文字列を torch.device に解決する(13.6: auto=cuda>mps>cpu)。"""
    if name == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(name)


def parse_factions(spec: str) -> Tuple[FactionId, ...]:
    """"marquise,eyrie" → FactionId タプル。"""
    return tuple(FactionId(v.strip()) for v in spec.split(","))


def _make_opponent(name: str):
    """対戦相手 bot を構築する(13.4)。"""
    if name == "heuristic":
        return HeuristicBot()
    if name == "random":
        return RandomBot()
    raise ValueError("未知の opponent: %r(random/heuristic)" % name)


# ------------------------------------------------------------
def load_checkpoint(ckpt_path: str, device: torch.device
                    ) -> Tuple[object, ObservationSpec, ActionCatalog,
                               Tuple[FactionId, ...], Dict]:
    """チェックポイントを読み、(net, spec, catalog, factions, meta) を返す(13.3)。

    catalog_version が現在と不一致なら明示エラーで落とす(14.7。行動空間の
    サイズが変わった旧 ckpt を無言で壊さないため)。
    """
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    ckpt_catalog_version = ckpt.get("catalog_version")
    if ckpt_catalog_version != CATALOG_VERSION:
        raise RuntimeError(
            "load_checkpoint failed: checkpoint %s has catalog_version=%r but current "
            "rl.catalog.CATALOG_VERSION=%d. Action catalog changed incompatibly "
            "(e.g. dominance-card actions added in 14.7) — old checkpoints are "
            "incompatible with the current action space."
            % (ckpt_path, ckpt_catalog_version, CATALOG_VERSION))
    factions = tuple(FactionId(v) for v in ckpt["factions"])
    spec = ObservationSpec(factions)
    catalog = ActionCatalog()
    ckpt_action_size = ckpt.get("action_size")
    if ckpt_action_size != catalog.size:
        raise RuntimeError(
            "load_checkpoint failed: checkpoint %s has action_size=%r but current "
            "ActionCatalog().size=%d. This should not happen when catalog_version "
            "matches — check rl/catalog.py for nondeterminism."
            % (ckpt_path, ckpt_action_size, catalog.size))
    net = build_net(spec.obs_dim, catalog.size, device)
    net.load_state_dict(ckpt["model"])
    net.eval()
    return net, spec, catalog, factions, ckpt


# ------------------------------------------------------------
def evaluate_matchup(net, spec: ObservationSpec, catalog: ActionCatalog,
                     device: torch.device, factions: Tuple[FactionId, ...],
                     opponent: str, games: int, learn_seat: int,
                     base_seed: int = 0, greedy: bool = True) -> Dict[str, float]:
    """学習席=``learn_seat`` に NNPolicy、他席に opponent を置き games 試合(13.4)。

    seed は base_seed からの固定列(再現性)。返り値は勝率など。
    """
    learn_fid = factions[learn_seat]
    nn_policy = NNPolicy(net, spec, catalog, device, greedy=greedy)
    opp = _make_opponent(opponent)
    policies = {}
    for i, fid in enumerate(factions):
        policies[fid] = nn_policy if i == learn_seat else opp

    wins = 0
    draws = 0
    vp_sum = 0
    for g in range(games):
        res = run_game(factions=factions, policies=policies,
                       seed=base_seed + g, max_turns=300)
        vp_sum += res.vps[learn_fid]
        if res.winner is None:
            draws += 1
        elif res.winner == learn_fid:
            wins += 1
    return {
        "opponent": opponent,
        "learn_seat": learn_seat,
        "games": games,
        "wins": wins,
        "draws": draws,
        "winrate": wins / games if games else 0.0,
        "vp_mean": vp_sum / games if games else 0.0,
    }


def evaluate_both_seats(net, spec, catalog, device, factions, opponent,
                        games: int, base_seed: int = 0, greedy: bool = True
                        ) -> List[Dict[str, float]]:
    """学習席=先手/後手それぞれで評価する(13.4)。2人戦なら seat 0,1。"""
    results = []
    for seat in range(len(factions)):
        results.append(evaluate_matchup(
            net, spec, catalog, device, factions, opponent, games, seat,
            base_seed=base_seed + seat * 10_000, greedy=greedy))
    return results


# ------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Root RL ネット単独評価(DESIGN.md 13.4)")
    parser.add_argument("--ckpt", type=str, required=True)
    parser.add_argument("--games", type=int, default=32)
    parser.add_argument("--opponent", type=str, default="random",
                         choices=("random", "heuristic"))
    parser.add_argument("--seat", type=int, default=-1,
                         help="学習席 index。-1=両席それぞれで評価")
    parser.add_argument("--base-seed", type=int, default=0)
    parser.add_argument("--device", type=str, default="auto")
    parser.add_argument("--sample", action="store_true",
                         help="argmax でなく分布サンプルで評価(既定は greedy)")
    args = parser.parse_args(argv)

    device = select_device(args.device)
    net, spec, catalog, factions, meta = load_checkpoint(args.ckpt, device)
    greedy = not args.sample

    print("ckpt=%s factions=%s device=%s update=%s total_steps=%s"
          % (args.ckpt, [f.value for f in factions], device,
             meta.get("update"), meta.get("total_steps")))

    if args.seat >= 0:
        rows = [evaluate_matchup(net, spec, catalog, device, factions,
                                 args.opponent, args.games, args.seat,
                                 base_seed=args.base_seed, greedy=greedy)]
    else:
        rows = evaluate_both_seats(net, spec, catalog, device, factions,
                                   args.opponent, args.games,
                                   base_seed=args.base_seed, greedy=greedy)
    for r in rows:
        print("vs %-9s seat=%d(%s) games=%d wins=%d draws=%d winrate=%.3f vp_mean=%.2f"
              % (r["opponent"], r["learn_seat"], factions[r["learn_seat"]].value,
                 r["games"], r["wins"], r["draws"], r["winrate"], r["vp_mean"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
