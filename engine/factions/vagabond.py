"""放浪部族(スタブ)。フェーズ2で実装。"""
from __future__ import annotations

from ..types import FactionId
from . import FactionLogic, register


class VagabondLogic(FactionLogic):
    faction = FactionId.VAGABOND

    def setup(self, state, rng):
        raise NotImplementedError("Vagabond は未実装(フェーズ2)")

    def legal_actions(self, state):
        raise NotImplementedError("Vagabond は未実装(フェーズ2)")


register(VagabondLogic())
