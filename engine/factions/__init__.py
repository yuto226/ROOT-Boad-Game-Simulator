"""派閥ロジックのプロトコルと registry(3.4)。

共通アクション(移動・戦闘・クラフト)の本体は engine 側にあり、派閥
モジュールは「いつ・何回・どのコストで使えるか」だけを差す。
"""
from __future__ import annotations

from typing import Dict, List, TYPE_CHECKING

from ..types import FactionId

if TYPE_CHECKING:  # 循環回避
    from ..actions import Action
    from ..state import GameState


class FactionLogic:
    """派閥ロジックの基底(プロトコル相当)。

    オプションのルール読み替えフックはデフォルト実装(共通動作)を持つ。
    未実装のフックはここで NotImplemented にせず素通りさせる。
    """

    faction: FactionId

    def setup(self, state: "GameState", rng) -> "GameState":
        """派閥固有の準備(5.1.7)。"""
        raise NotImplementedError

    def legal_actions(self, state: "GameState") -> "List[Action]":
        """自派閥ターンの現フェイズの合法手(EndPhase を含む)。"""
        raise NotImplementedError

    def begin_phase(self, state: "GameState", rng) -> "GameState":
        """フェイズ開始時の強制処理(木材配置 6.4, ドロー 6.6 等)。"""
        return state


_REGISTRY: Dict[FactionId, FactionLogic] = {}


def register(logic: FactionLogic) -> None:
    _REGISTRY[logic.faction] = logic


def get_logic(faction: FactionId) -> FactionLogic:
    return _REGISTRY[faction]


def _install() -> None:
    """全派閥ロジックを import して registry に登録する。"""
    from . import marquise  # noqa: F401
    from . import eyrie     # noqa: F401
    from . import alliance  # noqa: F401
    from . import vagabond  # noqa: F401
    from . import dummy     # noqa: F401


_install()
