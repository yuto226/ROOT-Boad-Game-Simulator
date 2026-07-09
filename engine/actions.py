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


# --- 鷲巣王朝固有(第7章) ---
@dataclass(frozen=True)
class EyrieChooseCorner(Action):
    """開始時広場の隅選択(7.3.2)。"""

    corner: str


@dataclass(frozen=True)
class EyrieChooseLeader(Action):
    """君主カードの選択(7.3.3 セットアップ / 7.7.3 失脚)。"""

    leader: str


@dataclass(frozen=True)
class EyrieAddToDecree(Action):
    """勅令追加(7.4.2)。column: 0=募兵 1=移動 2=戦闘 3=建設。"""

    card_id: str
    column: int


@dataclass(frozen=True)
class EyrieSkipDecree(Action):
    """勅令追加の2枚目を追加しない(7.4.2, 1枚目は強制)。"""


@dataclass(frozen=True)
class EyriePlaceRoost(Action):
    """止まり木確保(7.4.3): 止まり木1+兵士3の配置先。"""

    clearing: int


@dataclass(frozen=True)
class EyrieRecruit(Action):
    """勅令の募兵(7.5.2.I)。カリスマは兵士2個(7.8.2)。"""

    card_id: str
    clearing: int


@dataclass(frozen=True)
class EyrieDecreeMove(Action):
    """勅令の移動(7.5.2.II, 4.2)。"""

    card_id: str
    src: int
    dst: int
    count: int


@dataclass(frozen=True)
class EyrieDecreeBattle(Action):
    """勅令の戦闘(7.5.2.III, 4.3)。"""

    card_id: str
    clearing: int
    defender: FactionId


@dataclass(frozen=True)
class EyrieDecreeBuild(Action):
    """勅令の建設(7.5.2.IV): 止まり木タイル1枚を配置。"""

    card_id: str
    clearing: int


@dataclass(frozen=True)
class EyrieTurmoil(Action):
    """内乱(7.7)。実行不能な勅令の発生時の強制アクション。"""


# --- 森林連合固有(第8章) ---
@dataclass(frozen=True)
class AllianceRevolt(Action):
    """反乱(8.4.1)。支持広場に拠点を設立する。"""

    clearing: int


@dataclass(frozen=True)
class AllianceSpreadSympathy(Action):
    """支持拡大(8.4.2)。非支持広場へ支持トークンを配置する。"""

    clearing: int


@dataclass(frozen=True)
class AllianceMobilize(Action):
    """動員(8.5.2)。手札1枚を支援者ボックスへ。"""

    card_id: str


@dataclass(frozen=True)
class AllianceTrain(Action):
    """訓練(8.5.3)。拠点動物種と一致する手札1枚を捨て、指揮官1個を得る。"""

    card_id: str


@dataclass(frozen=True)
class AllianceOpMove(Action):
    """作戦行動・移動(8.6.1.I, 4.2)。"""

    src: int
    dst: int
    count: int


@dataclass(frozen=True)
class AllianceOpBattle(Action):
    """作戦行動・戦闘(8.6.1.II, 4.3)。"""

    clearing: int
    defender: FactionId


@dataclass(frozen=True)
class AllianceOpRecruit(Action):
    """作戦行動・募兵(8.6.1.III)。拠点のある広場に兵士1個を配置。"""

    clearing: int


@dataclass(frozen=True)
class AllianceOpOrganize(Action):
    """作戦行動・組織(8.6.1.IV)。非支持広場の自兵士1個を除去し支持トークン配置。"""

    clearing: int


@dataclass(frozen=True)
class AllianceEndOps(Action):
    """作戦行動を終え手札調整(8.6.2)へ進む宣言。"""


@dataclass(frozen=True)
class OutragePay(Action):
    """蜂起の支払い(8.2.6)。card_id=None は一致カードなしで山札トップ補充。"""

    card_id: Optional[str] = None


@dataclass(frozen=True)
class AllianceDiscardSupporter(Action):
    """全拠点喪失時の支援者5枚調整(8.2.4)での1枚破棄。"""

    card_id: str


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


@dataclass(frozen=True)
class EyrieSetupCornerDecision(Decision):
    """開始時広場の隅を選ぶ(7.3.2)。"""


@dataclass(frozen=True)
class EyrieLeaderDecision(Decision):
    """君主カードを選ぶ(7.3.3 セットアップ / 7.7.3 失脚)。

    turmoil=True なら選択後に休止(7.7.4)で夕闇フェイズへ直行する。
    """

    turmoil: bool = False


@dataclass(frozen=True)
class EyrieDecreeDecision(Decision):
    """勅令への追加(7.4.2)。first=True は1枚目(追加は強制)。

    bird_added: 1枚目に鳥カードを追加済みか(鳥2枚同時は不可)。
    """

    first: bool = True
    bird_added: bool = False


@dataclass(frozen=True)
class EyrieRoostDecision(Decision):
    """止まり木確保(7.4.3)の配置先選択。"""


@dataclass(frozen=True)
class OutrageDecision(Decision):
    """蜂起の支払い先選択(8.2.6)。actor=支払う他派閥。

    clearing の動物種と一致する手札カード(鳥含む)から1枚を支援者ボックスへ。
    一致カードがなければ山札トップ1枚が自動で支援者ボックスへ入る。
    """

    clearing: int = 0


@dataclass(frozen=True)
class SupportersLimitDecision(Decision):
    """全拠点喪失時の支援者ボックス5枚調整(8.2.4)。actor=森林連合。"""
