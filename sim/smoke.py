"""スモークテスト: 猫野侯国ソロゲームを N 試合回す。

使い方: ``python3 -m sim.smoke --games 20 --seed 0``

ソロでは戦闘相手がいないため、勝利条件は 30VP 到達 or max_turns 打ち切り。
クラッシュゼロが合格条件(DESIGN.md 7 フェーズ1)。
"""
from __future__ import annotations

import argparse
import sys
from typing import List

from engine.game import GameResult, run_game
from engine.types import FactionId
from bots.random_bot import RandomBot


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Marquise solo smoke test")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-turns", type=int, default=300)
    args = parser.parse_args(argv)

    bot = RandomBot()
    results: List[GameResult] = []
    for i in range(args.games):
        seed = args.seed + i
        result = run_game(
            factions=(FactionId.MARQUISE,),
            policies={FactionId.MARQUISE: bot},
            seed=seed,
            max_turns=args.max_turns,
        )
        results.append(result)
        vp = result.vps[FactionId.MARQUISE]
        outcome = "WIN(30VP)" if result.winner == FactionId.MARQUISE else "timeout"
        print("game %2d seed=%d: turns=%3d vp=%2d %s" % (i, seed, result.turns, vp, outcome))

    wins = sum(1 for r in results if r.winner is not None)
    turns = [r.turns for r in results]
    vps = [r.vps[FactionId.MARQUISE] for r in results]
    print("---")
    print("games=%d wins=%d timeouts=%d" % (len(results), wins, len(results) - wins))
    print("turns: min=%d avg=%.1f max=%d" % (min(turns), sum(turns) / len(turns), max(turns)))
    print("vp:    min=%d avg=%.1f max=%d" % (min(vps), sum(vps) / len(vps), max(vps)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
