"""鷲巣王朝(スタブ)。フェーズ2で実装。"""
from __future__ import annotations

from ..types import FactionId
from . import FactionLogic, register


class EyrieLogic(FactionLogic):
    faction = FactionId.EYRIE

    def setup(self, state, rng):
        raise NotImplementedError("Eyrie は未実装(フェーズ2)")

    def legal_actions(self, state):
        raise NotImplementedError("Eyrie は未実装(フェーズ2)")


register(EyrieLogic())
