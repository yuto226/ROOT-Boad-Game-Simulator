"""森林連合の派閥固有評価項(DESIGN.md 11.3)。

共感トークン・拠点・オフィサーが盤面支配と作戦行動の源泉。支援者は資源だが
抱えすぎ(上限超過廃棄)には報酬を与えないため 7 枚でクリップする。
"""
from __future__ import annotations

from engine.state import GameState


def faction_term(state: GameState) -> float:
    """森林連合固有の加点(DESIGN.md 11.3)。"""
    al = state.alliance()
    score = 0.0
    # 盤上の共感トークン*8 + 拠点*12 + officers*5
    score += al.placed_sympathy * 8
    score += len(al.bases_placed) * 12
    score += al.officers * 5
    # 支援者枚数*2(7 枚まで)
    score += min(len(al.supporters), 7) * 2
    return score
