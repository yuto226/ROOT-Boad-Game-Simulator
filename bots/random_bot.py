"""一様ランダムに合法手を選ぶ bot。"""
from __future__ import annotations

import random
from typing import List

from engine.actions import Action
from engine.state import GameState


class RandomBot:
    """合法手から一様ランダムに選択する Policy 実装。"""

    def choose(self, state: GameState, actions: List[Action],
               rng: random.Random) -> Action:
        return rng.choice(actions)
