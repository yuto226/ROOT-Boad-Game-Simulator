"""Policy プロトコル(DESIGN.md 2)。

将来の MCTS/RL(フェーズ6)を見据え、差し替え可能なインターフェース。
"""
from __future__ import annotations

import random
from typing import List, Protocol

from engine.actions import Action
from engine.state import GameState


class Policy(Protocol):
    """choose(state, legal_actions, rng) -> Action。"""

    def choose(self, state: GameState, actions: List[Action],
               rng: random.Random) -> Action:
        ...
