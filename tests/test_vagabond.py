"""放浪部族(第9章)の合法/違法テスト(DESIGN.md 8.3 / 9.3)。

DESIGN.md 8.8 の7シナリオ(探索・援助と関係強化・敵対化と悪名・戦闘読み替え・
反乱 vs 放浪者コマ・夕闇・クエスト)は engine/selftest.py の test_vagabond_* 7関数が
既にカバーしており、tests/test_selftest.py の薄いラッパーで取り込み済みなので
ここでは書かない。

このファイルでは、それらと重複しない観点を4件だけ検証する:
  1. 援助(9.5.4): 相手の作成アイテムボックスにアイテムがあるとき take_item=None
     は違法・take_item指定は合法(engine/factions/vagabond.py の _aid_options。
     今回のFableレビュー修正で入った仕様)。
  2. 移動(9.5.1): 敵対派閥の兵士がいる広場への移動は M(boots) 2枚必要。1枚だけ
     では違法(_move_options の need=2分岐)。
  3. 移動(9.5.1): 樹林への移動アクションは存在しない(VagabondMove の選択肢に
     樹林IDが出ない。樹林からの移動先も隣接広場のみ)。
  4. クラフト(9.5.8): 樹林にいるときはクラフト不可(legal_actions に CraftCard
     が出ない。crafting.craft_tool_suits が放浪部族×樹林で空リストを返すため)。

盤面の組み立ては engine/selftest.py の _setup_marquise_vagabond / _set_vagabond /
_tile / _clear ヘルパーをそのまま再利用する。conftest.make_state はセットアップ
Decision を「最初の合法手」で解決するだけで放浪部族の初期配置(樹林・キャラ)を
制御できないため、盤面制御が必要なこのファイルでは selftest 側のヘルパーを使う
(conftest に同等のヘルパーは無い)。
"""
from __future__ import annotations

import dataclasses
import random

from engine.actions import CraftCard, VagabondAid, VagabondMove
from engine.selftest import _clear, _set_vagabond, _setup_marquise_vagabond, _tile
from engine.types import FactionId, ItemKind, Suit

from conftest import assert_illegal, assert_legal, find_card, legal_of

M = FactionId.MARQUISE
V = FactionId.VAGABOND


# ---------------- 1. 援助 9.5.4: アイテム取得の強制(Fableレビュー修正) ----------------
def test_aid_take_item_forced_when_target_has_items():
    """相手(猫)の作成アイテムボックスにアイテムがあるとき、take_item=None の
    VagabondAid は違法。take_item を指定したものは合法(9.5.4)。"""
    rng = random.Random(101)
    state = _setup_marquise_vagabond(rng)
    c = 3  # mouse(test_vagabond_aid_relationship と同じ広場)
    state = _clear(state, c)
    state = state.with_clearing(state.clearing(c).add_soldiers(M, 1))
    card = find_card(state, suit=Suit.MOUSE)
    state = _set_vagabond(state, pawn_forest=None, pawn_clearing=c,
                          hand=(card,), items=(_tile("boots"),))
    state = state.with_faction_state(dataclasses.replace(state.fs(M), items=(ItemKind.TEA,)))

    assert_illegal(state, VagabondAid(player=V, faction=M, card_id=card, take_item=None))
    assert_legal(state, VagabondAid(player=V, faction=M, card_id=card, take_item="tea"))


# ---------------- 2. 移動 9.5.1: 敵対広場は boots 2枚必要 ----------------
def test_move_into_hostile_clearing_needs_two_boots():
    """敵対派閥(rel=-1)の兵士がいる広場への移動は boots 2枚必要。1枚のみでは違法。"""
    rng = random.Random(102)
    state = _setup_marquise_vagabond(rng)
    c = 3
    nb = state.map.clearing(c).adjacent[0]
    state = _clear(state, c)
    state = _clear(state, nb)
    state = state.with_clearing(state.clearing(nb).add_soldiers(M, 1))
    state = _set_vagabond(state, pawn_forest=None, pawn_clearing=c,
                          relationships=((M, -1),), items=(_tile("boots"),))

    # boots1枚では敵対広場への移動(必要M2)は違法
    assert_illegal(state, VagabondMove(player=V, dst=nb))

    # boots2枚あれば合法
    state = _set_vagabond(state, items=(_tile("boots"), _tile("boots")))
    assert_legal(state, VagabondMove(player=V, dst=nb))


# ---------------- 3. 移動 9.5.1: 樹林は移動先に出ない ----------------
def test_move_never_targets_forest():
    """VagabondMove の選択肢は常に広場IDのみ。樹林(現在位置が樹林でも)は
    移動先に出ない(9.5.1: 樹林へは移動不可・樹林からは隣接広場のみ)。"""
    rng = random.Random(103)
    state = _setup_marquise_vagabond(rng)  # 既定で樹林0にいる(8.6)
    assert state.vagabond().pawn_forest == 0 and state.vagabond().pawn_clearing is None
    state = _set_vagabond(state, items=tuple(_tile("boots") for _ in range(2)))

    dsts = {a.dst for a in legal_of(state, VagabondMove)}
    expected = set(state.map.forest(0).adjacent_clearings)
    assert dsts == expected, (
        "樹林からの移動先は隣接広場のみのはず: dsts=%r expected=%r" % (dsts, expected))
    clearing_ids = {cs.id for cs in state.map.clearings}
    assert dsts <= clearing_ids, "移動先はすべて広場IDのはず(樹林IDは出ない)"


# ---------------- 4. クラフト 9.5.8: 樹林ではクラフト不可 ----------------
def test_craft_illegal_in_forest():
    """樹林にいる間は CraftCard が合法手に出ない(craft_tool_suits が
    放浪部族×樹林で空リストを返すため。9.5.8/DESIGN.md 8.3)。"""
    rng = random.Random(104)
    state = _setup_marquise_vagabond(rng)  # 樹林0にいる
    card = find_card(state, item=ItemKind.BOOTS)
    state = _set_vagabond(state, hand=(card,),
                          items=(_tile("hammer"), _tile("hammer")))

    assert not legal_of(state, CraftCard), (
        "樹林にいる間はクラフト可能なはずのカードがあっても CraftCard は違法のはず")
