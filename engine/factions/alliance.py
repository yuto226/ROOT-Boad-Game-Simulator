"""森林連合(スタブ)。フェーズ2で実装。"""
from __future__ import annotations

from ..types import FactionId
from . import FactionLogic, register


class AllianceLogic(FactionLogic):
    faction = FactionId.ALLIANCE

    def setup(self, state, rng):
        raise NotImplementedError("Alliance は未実装(フェーズ2)")

    def legal_actions(self, state):
        raise NotImplementedError("Alliance は未実装(フェーズ2)")


register(AllianceLogic())
