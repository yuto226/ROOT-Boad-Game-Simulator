"""ヒューリスティックbot(1手先読み greedy + 派閥別評価関数, DESIGN.md 11)。

公開シンボル:
  HeuristicBot  — Policy 実装(11.2)
  evaluate      — 評価関数(11.3)
"""
from __future__ import annotations

from bots.heuristic.bot import HeuristicBot
from bots.heuristic.evaluate import evaluate, faction_score

__all__ = ["HeuristicBot", "evaluate", "faction_score"]
