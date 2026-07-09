"""カード定義(2.1)のロードと山札ユーティリティ。

``engine/data/cards.json`` が存在すればそれを優先する。存在しない/壊れて
いる場合は動物種のみの54枚フォールバックデッキ(クラフト不可)を用いる。

フォールバック構成(2.1.2 奇襲 / 2.1.3 圧倒):
- 動物種別枚数: fox13 / rabbit13 / mouse13 / bird15 = 54
- 奇襲(Ambush)計5枚: mouse/rabbit/fox 各1 + bird2
- 圧倒(Dominance)計4枚: 動物種ごと1枚
- 残りはクラフト能力なしの素のカード
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .types import Suit

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# カード種別
KIND_CRAFTABLE = "craftable"
KIND_AMBUSH = "ambush"
KIND_DOMINANCE = "dominance"
KIND_PLAIN = "plain"  # フォールバック用: クラフト能力なし


@dataclass(frozen=True)
class CardDef:
    """カードの静的定義(4.2)。"""

    id: str
    name: str
    suit: Suit
    kind: str
    cost: Tuple[str, ...] = ()          # 要素: fox|rabbit|mouse|bird|any
    effect: Optional[Dict] = None       # {"type": "item"|"immediate"|"persistent", ...}
    copies: int = 1
    text: str = ""

    @property
    def is_craftable(self) -> bool:
        return self.kind == KIND_CRAFTABLE

    @property
    def is_ambush(self) -> bool:
        return self.kind == KIND_AMBUSH

    @property
    def is_dominance(self) -> bool:
        return self.kind == KIND_DOMINANCE


def _fallback_defs() -> List[CardDef]:
    """cards.json 非存在時の54枚(動物種のみ)。"""
    defs: List[CardDef] = []
    plain_counts = {Suit.FOX: 11, Suit.RABBIT: 11, Suit.MOUSE: 11, Suit.BIRD: 12}
    ambush_counts = {Suit.FOX: 1, Suit.RABBIT: 1, Suit.MOUSE: 1, Suit.BIRD: 2}
    for suit in (Suit.FOX, Suit.RABBIT, Suit.MOUSE, Suit.BIRD):
        # 圧倒 1枚ずつ(3.3)
        defs.append(CardDef(id="dom_%s" % suit.value, name="Dominance",
                            suit=suit, kind=KIND_DOMINANCE, copies=1,
                            text="Dominance (%s)" % suit.value))
        # 奇襲(2.1.2)
        for i in range(ambush_counts[suit]):
            defs.append(CardDef(id="ambush_%s_%d" % (suit.value, i), name="Ambush!",
                                suit=suit, kind=KIND_AMBUSH, copies=1,
                                text="Ambush! (%s)" % suit.value))
        # 素のカード(クラフト不可)
        for i in range(plain_counts[suit]):
            defs.append(CardDef(id="plain_%s_%d" % (suit.value, i), name="Card",
                                suit=suit, kind=KIND_PLAIN, copies=1,
                                text="plain %s" % suit.value))
    total = sum(d.copies for d in defs)
    assert total == 54, "fallback deck must be 54 cards, got %d" % total
    return defs


def _parse_defs(raw: List[Dict]) -> List[CardDef]:
    defs = []
    for c in raw:
        defs.append(CardDef(
            id=c["id"],
            name=c.get("name", c["id"]),
            suit=Suit(c["suit"]),
            kind=c["kind"],
            cost=tuple(c.get("cost") or ()),
            effect=c.get("effect"),
            copies=int(c.get("copies", 1)),
            text=c.get("text", ""),
        ))
    total = sum(d.copies for d in defs)
    assert total == 54, "cards.json copies must sum to 54, got %d" % total
    return defs


def load_card_defs(path: Optional[str] = None) -> Tuple[Tuple[CardDef, ...], bool]:
    """カード定義をロードする。

    Returns: (定義タプル, from_json フラグ)。cards.json が使えなければ
    フォールバックを返す(from_json=False)。
    """
    if path is None:
        path = os.path.join(_DATA_DIR, "cards.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        defs = _parse_defs(raw)
        return tuple(defs), True
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        return tuple(_fallback_defs()), False


class CardIndex:
    """カード定義への索引。id -> CardDef。"""

    def __init__(self, defs: Tuple[CardDef, ...], from_json: bool):
        self.defs = defs
        self.from_json = from_json
        self._by_id = {d.id: d for d in defs}

    def get(self, card_id: str) -> CardDef:
        return self._by_id[self.base_id(card_id)]

    def suit_of(self, card_id: str) -> Suit:
        return self.get(card_id).suit

    def build_deck(self, two_player: bool) -> List[str]:
        """copies を展開したカードID列(未シャッフル)。

        2人戦では圧倒カード4枚を除く(5.1.3)。
        """
        deck: List[str] = []
        for d in self.defs:
            if two_player and d.is_dominance:
                continue
            for i in range(d.copies):
                deck.append(d.id if d.copies == 1 else "%s#%d" % (d.id, i))
        return deck

    def base_id(self, card_id: str) -> str:
        return card_id.split("#", 1)[0]


def shuffled_deck(index: CardIndex, two_player: bool, rng) -> List[str]:
    """シャッフル済み山札を返す(2.1 / 5.1.3)。乱数は注入(3.1)。"""
    deck = index.build_deck(two_player)
    rng.shuffle(deck)
    return deck
