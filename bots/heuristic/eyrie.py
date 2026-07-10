"""鷲巣王朝の派閥固有評価項(DESIGN.md 11.3)。

止まり木はターン VP と募兵数の源泉。勅令の肥大は後日の内乱(7.7)リスクだが
1-ply では見えないため、遂行能力(盤上兵士・止まり木)を超えた勅令に事前ペナルティを課す。
"""
from __future__ import annotations

from engine.state import GameState
from engine.types import FactionId


def faction_term(state: GameState) -> float:
    """鷲巣王朝固有の加点(DESIGN.md 11.3)。"""
    es = state.eyrie()
    score = 0.0
    # built_roosts*10(ターン VP と募兵数の源泉)
    score += es.built_roosts * 10
    # 内乱リスクの代理指標:
    #   -6 * max(0, 勅令総カード数 - 盤上兵士数//2 - built_roosts - 2)
    # 勅令総カード数は decree 4列の合計(decree_remaining はターン内進捗なので使わない)。
    decree_total = sum(len(col) for col in es.decree)
    board_soldiers = sum(cs.soldier_count(FactionId.EYRIE) for cs in state.clearings)
    overload = max(0, decree_total - board_soldiers // 2 - es.built_roosts - 2)
    score += -6 * overload
    return score
