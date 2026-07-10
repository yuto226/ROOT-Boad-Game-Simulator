"""フェーズ2テストの共通ヘルパー(DESIGN.md 9.2)。

``tests/`` 配下のテストは、このファイルの関数を pytest の自動 conftest 検出により
そのまま名前で参照できる(``import`` 不要。fixture ではなく素のヘルパー関数群)。

selftest.py の ``_setup_two_faction`` / ``_set_alliance`` / ``_clear`` の書き方を
一般化したもの。selftest.py 自体は変更していない。

主な関数(後続の派閥別テストが使う想定):
  make_state(factions, seed=42) -> (GameState, rng)
  put(state, cid, *, soldiers=None, buildings=None, tokens=None) -> GameState
  set_hand(state, faction, card_ids) -> GameState
  find_card(state, *, suit=None, is_ambush=None, item=None) -> card_id
  legal_of(state, cls) -> list[Action]
  assert_legal(state, action) -> None
  assert_illegal(state, action) -> None
"""
from __future__ import annotations

import dataclasses
import random
from typing import Dict, List, Optional, Tuple, Type

from engine.actions import (
    EyrieChooseCorner,
    EyrieChooseLeader,
    EyrieLeaderDecision,
    EyrieSetupCornerDecision,
    SetupChooseKeep,
    SetupKeepDecision,
)
from engine.apply import apply
from engine.game import new_game
from engine.legal import legal_actions
from engine.state import ClearingState, FactionState, GameState
from engine.types import FactionId, Piece, Suit

# セットアップで優先的に選ぶ既定値(選択肢に含まれない場合は legal[0] にフォールバック)。
_PREFERRED_KEEP_CORNER = "NW"        # 猫の城砦の隅(6.3.2)
_PREFERRED_EYRIE_LEADER = "commander"  # 鷲巣の初期君主(7.3.3)


def make_state(factions: Tuple[FactionId, ...],
               seed: int = 42) -> Tuple[GameState, random.Random]:
    """``factions`` の初期状態を、セットアップ Decision まで解決して返す。

    猫・鷲巣・連合の任意の2〜3派閥の組み合わせに対応する(DUMMY は含めない想定)。
    - 猫: 城砦の隅を NW(不可なら legal[0])に置く(6.3.2)。
    - 鷲巣: 隅選択(7.3.2)→ 君主 commander(不可なら legal[0])を選ぶ(7.3.3)。
    - 連合: セットアップ選択なし(支援者3枚は new_game で自動配置, 8.3.4)。

    Returns:
        (pending が空の GameState, 同じ乱数列を引き継ぐ rng)。
        rng は make_state 内のセットアップ適用と同一インスタンス。テスト側で
        以降の apply に渡せば決定的に再現できる。
    """
    rng = random.Random(seed)
    state = new_game(factions, rng)
    # セットアップ Decision を種類別に解決する。
    while state.pending:
        dec = state.pending[-1]
        acts = legal_actions(state)
        assert acts, "no setup actions for pending %r" % (dec,)
        action = acts[0]
        if isinstance(dec, SetupKeepDecision):
            action = _prefer(acts, SetupChooseKeep, "corner", _PREFERRED_KEEP_CORNER)
        elif isinstance(dec, EyrieSetupCornerDecision):
            # 隅は城砦位置により1択に強制されることがある(7.3.2)。legal[0] で十分。
            action = acts[0]
        elif isinstance(dec, EyrieLeaderDecision):
            action = _prefer(acts, EyrieChooseLeader, "leader",
                             _PREFERRED_EYRIE_LEADER)
        state = apply(state, action, rng)
    return state, rng


def _prefer(actions, cls, attr, value):
    """``actions`` から ``cls`` かつ ``getattr(a, attr)==value`` を優先選択する。"""
    for a in actions:
        if isinstance(a, cls) and getattr(a, attr) == value:
            return a
    return actions[0]


def put(state: GameState, cid: int, *,
        soldiers: Optional[Dict[FactionId, int]] = None,
        buildings: Optional[List[Piece]] = None,
        tokens: Optional[List[Piece]] = None) -> GameState:
    """広場 ``cid`` に駒を手動配置した新しい状態を返す(``with_clearing`` ラッパー)。

    指定したカテゴリのみ上書き・追加する。既存の内容は保持する。
    - soldiers: {faction: n} を絶対値でセット(``with_soldiers``)。n=0 は除去。
    - buildings / tokens: 既存の並びへ追加する(``add_building`` / ``add_token``)。

    例: put(state, 5, soldiers={M: 3}, buildings=[Piece(M, B_SAWMILL)])
    """
    cs = state.clearing(cid)
    if soldiers:
        for faction, n in soldiers.items():
            cs = cs.with_soldiers(faction, n)
    if buildings:
        for p in buildings:
            cs = cs.add_building(p)
    if tokens:
        for p in tokens:
            cs = cs.add_token(p)
    return state.with_clearing(cs)


def set_hand(state: GameState, faction: FactionId,
             card_ids: Tuple[str, ...]) -> GameState:
    """派閥 ``faction`` の手札を ``card_ids`` に差し替えた状態を返す。

    山札・捨札は変更しない。カード保存則(9.4.4)を厳密に保つ必要があるテスト
    では、差し替えるカードの出所/行き先を呼び出し側で調整すること。
    """
    fs = state.fs(faction)
    return state.with_faction_state(dataclasses.replace(fs, hand=tuple(card_ids)))


def find_card(state: GameState, *,
              suit: Optional[Suit] = None,
              is_ambush: Optional[bool] = None,
              item: Optional[object] = None) -> str:
    """山札(deck)から条件に合致する最初のカードIDを返す。

    条件(いずれも省略可、AND 結合):
      suit: 動物種(Suit)一致。
      is_ambush: 奇襲カードか否か(bool)。
      item: クラフトで得られる ItemKind 一致(effect が item 型のもの)。

    見つからなければ AssertionError。圧倒カードは常に対象外(2人戦の山札に
    存在しないため / テストで扱いにくいため)。
    """
    for card_id in state.deck:
        d = state.cards.get(card_id)
        if d.is_dominance:
            continue
        if suit is not None and d.suit != suit:
            continue
        if is_ambush is not None and d.is_ambush != is_ambush:
            continue
        if item is not None:
            eff = d.effect or {}
            if eff.get("type") != "item" or eff.get("item") != getattr(
                    item, "value", item):
                continue
        return card_id
    raise AssertionError(
        "no deck card matches suit=%r is_ambush=%r item=%r" % (suit, is_ambush, item))


def legal_of(state: GameState, cls: Type) -> List:
    """``legal_actions(state)`` を型 ``cls`` でフィルタしたリストを返す。"""
    return [a for a in legal_actions(state) if isinstance(a, cls)]


def assert_legal(state: GameState, action) -> None:
    """``action`` が現在の合法手に含まれることを表明する。"""
    acts = legal_actions(state)
    assert action in acts, (
        "expected %r to be legal; legal actions=%r" % (action, acts))


def assert_illegal(state: GameState, action) -> None:
    """``action`` が現在の合法手に含まれないことを表明する。"""
    acts = legal_actions(state)
    assert action not in acts, (
        "expected %r to be illegal; legal actions=%r" % (action, acts))
