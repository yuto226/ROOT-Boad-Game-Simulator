"""基本的な列挙型と小型値オブジェクト。

原文番号は ``rules/common.md`` / ``rules/cat.md`` を参照。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Suit(str, Enum):
    """動物種(2.1)。広場は fox/rabbit/mouse のいずれか。bird はワイルド(2.1.1)。"""

    FOX = "fox"
    RABBIT = "rabbit"
    MOUSE = "mouse"
    BIRD = "bird"


#: 広場が取りうる動物種(bird を除く, 2.2.2)
CLEARING_SUITS = (Suit.FOX, Suit.RABBIT, Suit.MOUSE)


class FactionId(str, Enum):
    """派閥識別子。DUMMY は戦闘テスト用の「何もしないスタブ派閥」。"""

    MARQUISE = "marquise"
    EYRIE = "eyrie"
    ALLIANCE = "alliance"
    VAGABOND = "vagabond"
    DUMMY = "dummy"


class Phase(Enum):
    """ターンの3フェイズ(1.4.1)。"""

    BIRDSONG = 1
    DAYLIGHT = 2
    EVENING = 3


class Corner(str, Enum):
    """マップ四隅(6.3.2)。"""

    NW = "NW"
    NE = "NE"
    SW = "SW"
    SE = "SE"


#: 対角の隅(圧倒カード鳥 3.3.1.II / 猫の駐留部隊 6.3.3 で使用)
OPPOSITE_CORNER = {
    Corner.NW: Corner.SE,
    Corner.SE: Corner.NW,
    Corner.NE: Corner.SW,
    Corner.SW: Corner.NE,
}


class ItemKind(str, Enum):
    """アイテムタイル(5.1.5)。"""

    BOOTS = "boots"
    BAG = "bag"
    CROSSBOW = "crossbow"
    HAMMER = "hammer"
    SWORD = "sword"
    TEA = "tea"
    COINS = "coins"
    TORCH = "torch"


# --- 配置物の種類(建物・トークン)を表す文字列定数 ---
# 猫野侯国の建物(6.1)
B_SAWMILL = "sawmill"
B_WORKSHOP = "workshop"
B_RECRUITER = "recruiter"
MARQUISE_BUILDINGS = (B_SAWMILL, B_WORKSHOP, B_RECRUITER)

# 鷲巣王朝の建物(7.2.1 / 7.5.2.IV)
B_ROOST = "roost"    # 止まり木タイル(クラフトツールも兼ねる, 7.2.1)

#: 忠臣カードの擬似ID(7.3.4)。山札に存在しない。動物種=鳥。
#: 内乱の追放(7.7.2)でも捨て山に行かず勅令エリアに残る。
LOYAL_VIZIER = "loyal-vizier"

#: 君主カード4種(7.8)
EYRIE_LEADERS = ("builder", "charismatic", "commander", "despot")

# トークン
T_KEEP = "keep"      # 城砦(6.2.2)
T_WOOD = "wood"      # 木材(6.4)
T_SYMPATHY = "sympathy"  # 森林連合(スタブ用)


@dataclass(frozen=True)
class Piece:
    """盤上の非兵士配置物(建物タイル1枚 or トークン1個)。"""

    faction: FactionId
    kind: str
