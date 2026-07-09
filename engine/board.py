"""静的マップデータ(2.2 広場と道 / 2.4 樹林)。

``engine/data/map_autumn.json`` をロードする。当該データは暫定
(``_verified: false``)であり、動物種・枠数・接続は未検証。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .types import Corner, Suit

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


@dataclass(frozen=True)
class Clearing:
    """広場(2.2)。"""

    id: int
    suit: Suit
    slots: int          # 建物枠数(2.2.3)。遺跡枠も含む総数。
    ruin: bool          # 遺跡タイルの有無(2.2.4)
    corner: Optional[Corner]
    adjacent: Tuple[int, ...]


@dataclass(frozen=True)
class Forest:
    """樹林(2.4)。フェーズ1では放浪部族未実装のため接続のみ保持。"""

    id: int
    adjacent_forests: Tuple[int, ...] = ()


@dataclass(frozen=True)
class MapData:
    """静的マップ全体。"""

    clearings: Tuple[Clearing, ...]
    forests: Tuple[Forest, ...]
    verified: bool

    def clearing(self, cid: int) -> Clearing:
        return self.clearings[cid]

    def are_adjacent(self, a: int, b: int) -> bool:
        return b in self.clearings[a].adjacent

    def corners(self) -> Tuple[int, ...]:
        return tuple(c.id for c in self.clearings if c.corner is not None)

    def corner_clearing(self, corner: Corner) -> Optional[int]:
        for c in self.clearings:
            if c.corner == corner:
                return c.id
        return None


def load_map(path: Optional[str] = None) -> MapData:
    """map_autumn.json をロードして :class:`MapData` を返す。"""
    if path is None:
        path = os.path.join(_DATA_DIR, "map_autumn.json")
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    clearings = tuple(
        Clearing(
            id=c["id"],
            suit=Suit(c["suit"]),
            slots=c["slots"],
            ruin=c.get("ruin", False),
            corner=Corner(c["corner"]) if c.get("corner") else None,
            adjacent=tuple(c["adjacent"]),
        )
        for c in raw["clearings"]
    )
    forests = tuple(
        Forest(id=f["id"], adjacent_forests=tuple(f.get("adjacent_forests", ())))
        for f in raw.get("forests", [])
    )
    return MapData(clearings=clearings, forests=forests, verified=raw.get("_verified", False))


def load_board_defs(path: Optional[str] = None) -> Dict:
    """派閥ボード数列(boards.json, 4.4)。要検証データ。"""
    if path is None:
        path = os.path.join(_DATA_DIR, "boards.json")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
