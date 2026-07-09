"""アクション(純データ, 3.3)とデシジョン(保留スタック要素, 3.2)。

Action はプレイヤーIDと必要パラメータのみを持つ。適用ロジックは
:mod:`engine.apply` にある。docstring に原文番号を併記する。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .types import FactionId


# ============================================================
#  Action(手番/デシジョンに対する選択)
# ============================================================
@dataclass(frozen=True)
class Action:
    """全アクションの基底。"""

    player: FactionId


@dataclass(frozen=True)
class EndPhase(Action):
    """現フェイズを終了し次フェイズ(or 次プレイヤー)へ(1.4.1)。"""


@dataclass(frozen=True)
class CraftCard(Action):
    """クラフトアクション(4.1)。"""

    card_id: str


@dataclass(frozen=True)
class DeclareBattle(Action):
    """戦闘を宣言(4.3)。"""

    clearing: int
    defender: FactionId


# --- 猫野侯国固有(第6章) ---
@dataclass(frozen=True)
class MarquiseBuild(Action):
    """建設アクション(6.5.4)。"""

    clearing: int
    kind: str  # sawmill|workshop|recruiter


@dataclass(frozen=True)
class MarquiseRecruit(Action):
    """募兵アクション(6.5.3)。1ターン1回。"""


@dataclass(frozen=True)
class MarquiseMarch(Action):
    """行軍アクションの1移動(6.5.2, 4.2)。

    フェーズ1簡略化: 行軍1回につき1移動のみ(本来は2移動まで)。
    """

    src: int
    dst: int
    count: int


@dataclass(frozen=True)
class MarquiseLabor(Action):
    """労働アクション(6.5.5)。製材所広場と一致するカードを消費し木材1配置。"""

    clearing: int
    card_id: str


@dataclass(frozen=True)
class MarquisePlayBirdCard(Action):
    """鳥カード消費による追加アクション権の獲得(6.5)。"""

    card_id: str


# --- デシジョン応答アクション ---
@dataclass(frozen=True)
class AmbushChoice(Action):
    """奇襲する/しない、または妨害する/しない(4.3.1)。card_id=None で「しない」。"""

    card_id: Optional[str] = None


@dataclass(frozen=True)
class AllocateHit(Action):
    """ヒット1つの割り振り(4.3.4)。

    target: ("soldier",) / ("building", kind) / ("token", kind)
    """

    target: Tuple


@dataclass(frozen=True)
class DiscardCard(Action):
    """手札上限超過分の破棄(6.6)。"""

    card_id: str


@dataclass(frozen=True)
class SetupChooseKeep(Action):
    """城砦の隅選択(6.3.2)。"""

    corner: str


# ============================================================
#  Decision(保留スタック要素, 3.2)。各 Decision は actor を持つ。
# ============================================================
@dataclass(frozen=True)
class BattleCtx:
    """戦闘コンテキスト(不変, 3.6)。"""

    attacker: FactionId
    defender: FactionId
    clearing: int
    ambush_used: bool = False


@dataclass(frozen=True)
class Decision:
    """全デシジョンの基底。actor が選択の担当プレイヤー。"""

    actor: FactionId


@dataclass(frozen=True)
class SetupKeepDecision(Decision):
    """城砦の隅を選ぶ(6.3.2)。"""


@dataclass(frozen=True)
class AmbushDefenderDecision(Decision):
    """防御側の奇襲(4.3.1 第1ステップ)。"""

    ctx: BattleCtx = None


@dataclass(frozen=True)
class AmbushAttackerDecision(Decision):
    """攻撃側の奇襲妨害(4.3.1.I)。"""

    ctx: BattleCtx = None


@dataclass(frozen=True)
class AllocateHitsDecision(Decision):
    """ヒットの割り振り(4.3.4)。actor=victim が自コマを除去する。"""

    victim: FactionId = None
    hits: int = 0
    source: FactionId = None    # ヒットを与えた側(建物/トークン除去VPの受け手)
    clearing: int = 0


@dataclass(frozen=True)
class DiscardDecision(Decision):
    """手札を5枚に減らす(6.6)。"""
