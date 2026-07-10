"""評価関数(DESIGN.md 11.3)。

evaluate(state, me) = faction_score(state, me) - max(faction_score(state, f) for f in 他派閥)

相手項は「首位の他派閥」のみを引く(妨害の照準をリーダーに合わせる)。
faction_score = 共通項 + 派閥固有項。DUMMY は 0 固定。
重みはすべて 11.3 の初期値。
"""
from __future__ import annotations

from engine.state import GameState
from engine.types import FactionId

from bots.heuristic import alliance as _alliance
from bots.heuristic import eyrie as _eyrie
from bots.heuristic import marquise as _marquise

#: 派閥固有項のディスパッチ表(DESIGN.md 11.3)。
_FACTION_TERMS = {
    FactionId.MARQUISE: _marquise.faction_term,
    FactionId.EYRIE: _eyrie.faction_term,
    FactionId.ALLIANCE: _alliance.faction_term,
}


def _common_score(state: GameState, f: FactionId) -> float:
    """共通項(DESIGN.md 11.3)。全派閥に適用。"""
    fs = state.fs(f)
    score = 0.0
    # vp*100(30VP 到達勝ちなので VP を支配的に)
    score += fs.vp * 100
    # 支配クリアリング数*6(controller は森の王者ルール込み, 2.5)
    controlled = sum(1 for cs in state.clearings if state.controller(cs.cid) == f)
    score += controlled * 6
    # 兵士がいるクリアリング数*2 + 盤上兵士総数*1
    clearings_with = sum(1 for cs in state.clearings if cs.soldier_count(f) > 0)
    total_soldiers = sum(cs.soldier_count(f) for cs in state.clearings)
    score += clearings_with * 2 + total_soldiers * 1
    # 手札枚数*2(ただし 5 枚まで。抱えすぎに報酬を与えない)
    score += min(len(fs.hand), 5) * 2
    return score


def faction_score(state: GameState, f: FactionId) -> float:
    """派閥 f の評価スコア = 共通項 + 派閥固有項(DESIGN.md 11.3)。DUMMY は 0 固定。"""
    if f == FactionId.DUMMY:
        return 0.0
    score = _common_score(state, f)
    term = _FACTION_TERMS.get(f)
    if term is not None:
        score += term(state)
    return score


def evaluate(state: GameState, me: FactionId) -> float:
    """me 視点の評価値(DESIGN.md 11.3)。首位の他派閥スコアを引く。"""
    mine = faction_score(state, me)
    others = [faction_score(state, f) for f in state.factions if f != me]
    top_other = max(others) if others else 0.0
    return mine - top_other
