"""スモークテスト: ランダムbot対戦を N 試合回す。

使い方:
  python3 -m sim.smoke --games 20 --seed 0                       # 猫ソロ(既定)
  python3 -m sim.smoke --games 30 --seed 0 --factions marquise,eyrie

勝利条件は 30VP 到達(3.1) or max_turns 打ち切り(timeout)。
クラッシュゼロが合格条件(DESIGN.md 7)。
"""
from __future__ import annotations

import argparse
import sys
from typing import List

from engine.game import GameResult, run_game
from engine.types import FactionId
from bots.random_bot import RandomBot


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Root random-bot smoke test")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-turns", type=int, default=300)
    parser.add_argument("--factions", type=str, default="marquise",
                        help="カンマ区切りの派閥リスト(例: marquise,eyrie)。既定はソロ猫")
    args = parser.parse_args(argv)

    factions = tuple(FactionId(name.strip()) for name in args.factions.split(","))
    bot = RandomBot()
    policies = {f: bot for f in factions}

    results: List[GameResult] = []
    for i in range(args.games):
        seed = args.seed + i
        result = run_game(
            factions=factions,
            policies=policies,
            seed=seed,
            max_turns=args.max_turns,
        )
        results.append(result)
        vps = " ".join("%s=%d" % (f.value, result.vps[f]) for f in factions)
        outcome = "WIN:%s" % result.winner.value if result.winner else "timeout"
        print("game %2d seed=%d: turns=%3d vp[%s] %s"
              % (i, seed, result.turns, vps, outcome))

    print("---")
    win_counts = {}
    for r in results:
        if r.winner is not None:
            win_counts[r.winner] = win_counts.get(r.winner, 0) + 1
    timeouts = sum(1 for r in results if r.winner is None)
    wins_str = " ".join("%s=%d" % (f.value, win_counts.get(f, 0)) for f in factions)
    turns = [r.turns for r in results]
    print("games=%d wins[%s] timeouts=%d" % (len(results), wins_str, timeouts))
    print("turns: min=%d avg=%.1f max=%d"
          % (min(turns), sum(turns) / len(turns), max(turns)))
    for f in factions:
        vps = [r.vps[f] for r in results]
        print("vp %-8s: min=%d avg=%.1f max=%d"
              % (f.value, min(vps), sum(vps) / len(vps), max(vps)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
