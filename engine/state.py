"""ゲーム状態(すべて frozen dataclass, 3.1)。

更新は :func:`dataclasses.replace` を包んだヘルパで行い、入力状態は
変更しない。コレクションは tuple を用いる。
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .board import MapData
from .cards import CardIndex
from .types import (
    FactionId,
    ItemKind,
    Phase,
    Piece,
    Suit,
    T_KEEP,
    T_WOOD,
)

# --- 兵士数の内部表現ヘルパ(FactionId -> int のタプル対) ---
SoldierMap = Tuple[Tuple[FactionId, int], ...]


def _sm_get(pairs: SoldierMap, faction: FactionId) -> int:
    for f, n in pairs:
        if f == faction:
            return n
    return 0


def _sm_set(pairs: SoldierMap, faction: FactionId, value: int) -> SoldierMap:
    out = []
    found = False
    for f, n in pairs:
        if f == faction:
            found = True
            if value > 0:
                out.append((f, value))
        else:
            out.append((f, n))
    if not found and value > 0:
        out.append((faction, value))
    return tuple(out)


@dataclass(frozen=True)
class ClearingState:
    """1広場の動的状態。"""

    cid: int
    ruin: bool = False
    soldiers: SoldierMap = ()
    buildings: Tuple[Piece, ...] = ()
    tokens: Tuple[Piece, ...] = ()

    # --- 参照 ---
    def soldier_count(self, faction: FactionId) -> int:
        return _sm_get(self.soldiers, faction)

    def total_soldiers(self) -> int:
        return sum(n for _, n in self.soldiers)

    def buildings_of(self, faction: FactionId) -> Tuple[Piece, ...]:
        return tuple(p for p in self.buildings if p.faction == faction)

    def tokens_of(self, faction: FactionId) -> Tuple[Piece, ...]:
        return tuple(p for p in self.tokens if p.faction == faction)

    def has_token(self, faction: FactionId, kind: str) -> bool:
        return any(p.faction == faction and p.kind == kind for p in self.tokens)

    def wood_count(self, faction: FactionId) -> int:
        return sum(1 for p in self.tokens if p.faction == faction and p.kind == T_WOOD)

    def occupied_slots(self) -> int:
        """埋まっている建物枠数(建物タイル + 遺跡が1枠を占有, 2.2.4)。"""
        return len(self.buildings) + (1 if self.ruin else 0)

    # --- 更新(新インスタンスを返す) ---
    def with_soldiers(self, faction: FactionId, value: int) -> "ClearingState":
        return dataclasses.replace(self, soldiers=_sm_set(self.soldiers, faction, value))

    def add_soldiers(self, faction: FactionId, delta: int) -> "ClearingState":
        return self.with_soldiers(faction, self.soldier_count(faction) + delta)

    def add_building(self, piece: Piece) -> "ClearingState":
        return dataclasses.replace(self, buildings=self.buildings + (piece,))

    def remove_building(self, piece: Piece) -> "ClearingState":
        bs = list(self.buildings)
        bs.remove(piece)
        return dataclasses.replace(self, buildings=tuple(bs))

    def add_token(self, piece: Piece) -> "ClearingState":
        return dataclasses.replace(self, tokens=self.tokens + (piece,))

    def remove_one_token(self, faction: FactionId, kind: str) -> "ClearingState":
        ts = list(self.tokens)
        for i, p in enumerate(ts):
            if p.faction == faction and p.kind == kind:
                del ts[i]
                return dataclasses.replace(self, tokens=tuple(ts))
        raise ValueError("no token %s/%s to remove" % (faction, kind))


@dataclass(frozen=True)
class FactionState:
    """派閥ボード共通状態。派閥固有フィールドはサブクラスで追加。"""

    faction: FactionId
    vp: int = 0
    hand: Tuple[str, ...] = ()
    crafted_cards: Tuple[str, ...] = ()   # 手元の継続効果カード(4.1.3)
    items: Tuple[ItemKind, ...] = ()      # 作成済みアイテム
    soldiers_supply: int = 0              # サプライにある兵士コマ数


@dataclass(frozen=True)
class MarquiseState(FactionState):
    """猫野侯国の派閥ボード状態(第6章)。"""

    wood_supply: int = 0
    # マップ上に配置済みの建物数(0..6)。cost/VP のインデックスに使う(6.5.4)。
    built_sawmill: int = 0
    built_workshop: int = 0
    built_recruiter: int = 0
    # 昼光フェイズの状態
    actions_left: int = 0
    recruited_this_turn: bool = False
    workshop_used: bool = False   # クラフトツール起動フラグ(6.2.1, 4.1.1)
    keep_corner: Optional[str] = None

    def built_count(self, kind: str) -> int:
        return {"sawmill": self.built_sawmill,
                "workshop": self.built_workshop,
                "recruiter": self.built_recruiter}[kind]


@dataclass(frozen=True)
class DummyState(FactionState):
    """戦闘テスト用の「何もしない」スタブ派閥。"""


@dataclass(frozen=True)
class GameState:
    """ゲーム全体の不変状態。"""

    map: MapData
    cards: CardIndex
    board_defs: Dict
    factions: Tuple[FactionId, ...]          # 席順(5.1.1)
    faction_states: Tuple[FactionState, ...]  # factions と同順
    clearings: Tuple[ClearingState, ...]      # cid 昇順
    turn_index: int = 0                       # 手番プレイヤー(factions のインデックス)
    phase: Phase = Phase.BIRDSONG
    turn_count: int = 0                       # 経過ターン数(安全弁, 3.8)
    deck: Tuple[str, ...] = ()
    discard: Tuple[str, ...] = ()
    supply_items: Tuple[Tuple[ItemKind, int], ...] = ()  # サプライのアイテム残数
    pending: Tuple = ()                        # 保留デシジョンスタック(3.2)
    winner: Optional[FactionId] = None
    finished: bool = False

    # --- 参照 ---
    def current_faction(self) -> FactionId:
        return self.factions[self.turn_index]

    def to_act(self) -> FactionId:
        """次に選択すべきプレイヤー(3.2)。"""
        if self.pending:
            return self.pending[-1].actor
        return self.current_faction()

    def fs(self, faction: FactionId) -> FactionState:
        for s in self.faction_states:
            if s.faction == faction:
                return s
        raise KeyError(faction)

    def marquise(self) -> MarquiseState:
        s = self.fs(FactionId.MARQUISE)
        assert isinstance(s, MarquiseState)
        return s

    def clearing(self, cid: int) -> ClearingState:
        return self.clearings[cid]

    # --- 支配(2.5) ---
    def controller(self, cid: int) -> Optional[FactionId]:
        """広場の支配プレイヤー。兵士コマ+建物タイルの合計最大, 同点は None。

        放浪者コマ・トークンは不算入(2.5, 9.2.2)。
        """
        cs = self.clearings[cid]
        counts: Dict[FactionId, int] = {}
        for f, n in cs.soldiers:
            counts[f] = counts.get(f, 0) + n
        for p in cs.buildings:
            counts[p.faction] = counts.get(p.faction, 0) + 1
        if not counts:
            return None
        best = max(counts.values())
        leaders = [f for f, c in counts.items() if c == best]
        if len(leaders) == 1:
            return leaders[0]
        return None

    def controls(self, faction: FactionId, cid: int) -> bool:
        return self.controller(cid) == faction

    # --- 更新ヘルパ ---
    def replace(self, **kwargs) -> "GameState":
        return dataclasses.replace(self, **kwargs)

    def with_clearing(self, cs: ClearingState) -> "GameState":
        cl = list(self.clearings)
        cl[cs.cid] = cs
        return dataclasses.replace(self, clearings=tuple(cl))

    def with_faction_state(self, fs: FactionState) -> "GameState":
        out = [fs if s.faction == fs.faction else s for s in self.faction_states]
        return dataclasses.replace(self, faction_states=tuple(out))

    def push_pending(self, *decisions) -> "GameState":
        """デシジョンをスタック末尾(先頭処理)に積む。

        引数は「処理したい順」で渡し、内部では逆順に積む(末尾=次に処理)。
        """
        new = self.pending + tuple(reversed(decisions))
        return dataclasses.replace(self, pending=new)

    def pop_pending(self) -> "GameState":
        return dataclasses.replace(self, pending=self.pending[:-1])

    # --- サプライアイテム ---
    def item_available(self, item: ItemKind) -> bool:
        return any(k == item and n > 0 for k, n in self.supply_items)

    def take_item(self, item: ItemKind) -> "GameState":
        out = []
        for k, n in self.supply_items:
            if k == item:
                out.append((k, n - 1))
            else:
                out.append((k, n))
        return dataclasses.replace(self, supply_items=tuple(out))

    # --- デバッグ用不変量チェック(6 テスト戦略) ---
    def validate(self) -> None:
        for cs in self.clearings:
            cl = self.map.clearing(cs.cid)
            assert cs.occupied_slots() <= cl.slots, (
                "clearing %d over slots: %d/%d" % (cs.cid, cs.occupied_slots(), cl.slots))
            assert cs.total_soldiers() >= 0
        for fs in self.faction_states:
            assert fs.vp >= 0, "negative VP for %s" % fs.faction
