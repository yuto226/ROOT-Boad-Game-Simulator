"""猫野侯国の派閥固有評価項(DESIGN.md 11.3)。

建物の VP は共通項(evaluate.py)で計上済み。ここでは「将来の収入源」を評価する:
製材所=木材収入、募兵所=兵士収入、工房=クラフト。盤上の木材トークンも資源として加点。
"""
from __future__ import annotations

from engine.state import GameState
from engine.types import FactionId


def faction_term(state: GameState) -> float:
    """猫野侯国固有の加点(DESIGN.md 11.3)。"""
    ms = state.marquise()
    score = 0.0
    # 盤上の製材所*8(木材収入)+ 募兵所*8(兵士収入)+ 工房*5(クラフト)
    score += ms.built_sawmill * 8
    score += ms.built_recruiter * 8
    score += ms.built_workshop * 5
    # 盤上の木材トークン*2
    wood = sum(cs.wood_count(FactionId.MARQUISE) for cs in state.clearings)
    score += wood * 2
    return score
