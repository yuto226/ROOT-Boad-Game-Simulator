"""「何もしない」スタブ派閥。戦闘機構の手動テスト用の対戦相手。

盤上に兵士コマ等を持つが、自ターンでは即フェイズ終了する。
"""
from __future__ import annotations

from typing import List

from ..actions import Action, EndPhase
from ..types import FactionId
from . import FactionLogic, register


class DummyLogic(FactionLogic):
    faction = FactionId.DUMMY

    def setup(self, state, rng):
        return state

    def legal_actions(self, state) -> List[Action]:
        # 何もしない: フェイズを終えるのみ。
        return [EndPhase(player=FactionId.DUMMY)]

    def begin_phase(self, state, rng):
        return state


register(DummyLogic())
