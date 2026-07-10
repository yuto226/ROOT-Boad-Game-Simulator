"""HeuristicBot: 1手先読み greedy(DESIGN.md 11.2)。

各候補アクションを apply でシミュレート実行し、結果状態を評価関数(11.3)で
スコアリングして argmax を選ぶ。ルールベースの種別網羅(if 文)は採らない。
"""
from __future__ import annotations

import random
from typing import List

from engine.actions import Action
from engine.apply import apply
from engine.state import GameState

from bots.heuristic.evaluate import evaluate

#: 終端ショートカットのスコア(DESIGN.md 11.2 step 3)。
_WIN = 1e9
_LOSE = -1e9


class HeuristicBot:
    """Policy 実装(DESIGN.md 11.2)。

    samples: 各候補を何回シミュレートしてスコアを平均するか(戦闘ダイス・
             ドローの乱数ノイズを均すため)。既定 3。
    """

    def __init__(self, samples: int = 3) -> None:
        self.samples = samples

    def choose(self, state: GameState, actions: List[Action],
               rng: random.Random) -> Action:
        # step 1: メイン rng の消費は choose 1回につきこの1回だけ(決定性 10.2)。
        base = rng.getrandbits(32)

        # 候補が1つなら評価不要(rng は上で1回消費済み=消費列は不変)。
        if len(actions) == 1:
            return actions[0]

        me = state.to_act()  # choose 時点の手番/デシジョン actor
        best_idx = 0
        best_score = None
        for i, action in enumerate(actions):
            # step 2: samples 回シミュレートしてスコアを平均する。
            total = 0.0
            for j in range(self.samples):
                sim_rng = random.Random((base << 16) ^ (i << 8) ^ j)
                next_state = apply(state, action, sim_rng)
                # step 3: 終端ショートカット。
                if next_state.finished and next_state.winner is not None:
                    total += _WIN if next_state.winner == me else _LOSE
                else:
                    total += evaluate(next_state, me)
            avg = total / self.samples
            # step 4: argmax。同点は先頭優先(strict > で先頭を保持)。
            if best_score is None or avg > best_score:
                best_score = avg
                best_idx = i
        return actions[best_idx]
