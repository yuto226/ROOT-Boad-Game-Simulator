"""放浪部族(ヴァガボンド)ロジック(第9章)。

合法手生成・フェイズ開始処理・放浪部族固有アクションの適用を担う。
共通アクション(戦闘・クラフト)の本体は engine 側にあり、ここは「いつ・
何回・どのコストで使えるか」を差す(DESIGN.md 3.4 / 8章)。

放浪者コマは兵士コマではない(9.2.2): 支配に無関与・除去されない・移動時の
支配条件無視(9.2.3)。コマ位置は VagabondState.pawn_clearing/pawn_forest の
排他。アイテムは ItemTile 列(3ゾーン+表裏, 9.2.5)。戦闘の読み替え(9.2.4/
9.2.6/9.2.7/9.2.2.I)は battle.py 側のフックで、関係処理(9.2.9)は remove_piece
から on_vagabond_removes フックで行う。

既知の簡略化(DESIGN.md 8.1 / レビュー確認点):
- 配置枠(T/X/B)への配置は「置けるとき常に置く」自動処理(9.2.5.I)。
- アイテムコストの支払いはどのタイルを exhaust するか自動選択(配置枠優先)。
- 共闘軍(9.2.8)・同盟同時移動/攻撃/肩代わり(9.2.9.II.b〜d)は対象外。
"""
from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import replace
from typing import List, Optional, Tuple

from ..actions import (
    Action,
    DeclareBattle,
    DiscardDecision,
    EndPhase,
    ItemDamageDecision,
    ItemLimitDecision,
    RefreshDecision,
    VagabondAid,
    VagabondBattle,
    VagabondChooseCharacter,
    VagabondChooseForest,
    VagabondExplore,
    VagabondItemChoice,
    VagabondMove,
    VagabondQuest,
    VagabondRepair,
    VagabondSlip,
    VagabondSpecial,
    VagabondStrike,
)
from ..crafting import legal_crafts
from ..mechanics import award_vp, draw_cards
from ..state import GameState, ItemTile, VagabondState
from ..types import FactionId, ItemKind, Phase, Suit
from . import FactionLogic, register

VAGABOND = FactionId.VAGABOND

# アイテム記号 → ItemKind 値(9.6.4 の記号対応: M=boots,S=sword,C=crossbow,
# F=torch,H=hammer,T=tea,X=coins,B=bag)
BOOTS = ItemKind.BOOTS.value
SWORD = ItemKind.SWORD.value
CROSSBOW = ItemKind.CROSSBOW.value
TORCH = ItemKind.TORCH.value
HAMMER = ItemKind.HAMMER.value
TEA = ItemKind.TEA.value
COINS = ItemKind.COINS.value
BAG = ItemKind.BAG.value

#: 配置枠を持つ種類(T/X/B)。他は常にかばんエリア(9.2.5)
TRACK_KINDS = (TEA, COINS, BAG)
TRACK_SLOTS = 3


# ============================================================
#  クエスト定義のロード(quests.json)
# ============================================================
_QUESTS_CACHE = None


def _load_quests():
    global _QUESTS_CACHE
    if _QUESTS_CACHE is None:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "data", "quests.json")
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        _QUESTS_CACHE = {q["id"]: q for q in raw}
    return _QUESTS_CACHE


def quest_ids() -> List[str]:
    """全クエストIDを json 記載順で返す(セットアップのシャッフル対象, 9.3.3)。"""
    return list(_load_quests().keys())


def _quest_def(qid: str) -> dict:
    return _load_quests()[qid]


# ============================================================
#  アイテムタイルのゾーン操作(9.2.5)
# ============================================================
def _sig(t: ItemTile) -> Tuple:
    """タイルの正規化シグネチャ(選択肢の同一視・照合に使う)。"""
    return (t.kind, t.exhausted, t.damaged, t.on_track)


def _auto_place(items: Tuple[ItemTile, ...]) -> Tuple[ItemTile, ...]:
    """表向き・非損傷の T/X/B を空き配置枠へ自動配置する(9.2.5.I の簡略化)。"""
    out = list(items)
    counts = {}
    for t in out:
        if t.on_track:
            counts[t.kind] = counts.get(t.kind, 0) + 1
    for i, t in enumerate(out):
        if (t.kind in TRACK_KINDS and not t.damaged and not t.exhausted
                and not t.on_track and counts.get(t.kind, 0) < TRACK_SLOTS):
            out[i] = replace(t, on_track=True)
            counts[t.kind] = counts.get(t.kind, 0) + 1
    return tuple(out)


def _add_item(items: Tuple[ItemTile, ...], kind: str) -> Tuple[ItemTile, ...]:
    """アイテム1枚を表向きで獲得しかばんエリアへ(可能なら配置枠へ自動配置)。"""
    items = items + (ItemTile(kind=kind, exhausted=False, damaged=False, on_track=False),)
    return _auto_place(items)


def _count_payable(items: Tuple[ItemTile, ...], kind: str) -> int:
    """コストに使える(未使用・非損傷)当該種タイル数。"""
    return sum(1 for t in items if t.kind == kind and not t.exhausted and not t.damaged)


def _can_pay(items: Tuple[ItemTile, ...], kind: str) -> bool:
    return _count_payable(items, kind) > 0


def _pay(items: Tuple[ItemTile, ...], kind: str) -> Tuple[ItemTile, ...]:
    """未使用・非損傷の当該種1枚を exhaust する(配置枠のものを優先)。"""
    idx = None
    for i, t in enumerate(items):
        if t.kind == kind and not t.exhausted and not t.damaged:
            if t.on_track:
                idx = i
                break
            if idx is None:
                idx = i
    assert idx is not None, "no payable %s" % kind
    out = list(items)
    out[idx] = replace(out[idx], exhausted=True, on_track=False)
    # 配置枠が空いたら、かばんの表向きT/X/Bを詰める(9.2.5.Iの常時配置)
    return _auto_place(tuple(out))


def _can_pay_any(items: Tuple[ItemTile, ...]) -> bool:
    return any(not t.exhausted and not t.damaged for t in items)


def _pay_any(items: Tuple[ItemTile, ...]) -> Tuple[ItemTile, ...]:
    """任意アイテム1枚を exhaust する(9.5.4。どれを払うかは自動=簡略化)。"""
    for i, t in enumerate(items):
        if not t.exhausted and not t.damaged:
            out = list(items)
            out[i] = replace(t, exhausted=True, on_track=False)
            return _auto_place(tuple(out))
    raise AssertionError("no payable item")


def _can_pay_items(items: Tuple[ItemTile, ...], kinds: List[str]) -> bool:
    """指定種のアイテム列(同種の重複あり)をすべて払えるか(クエスト 9.5.5)。"""
    tmp = items
    for k in kinds:
        if not _can_pay(tmp, k):
            return False
        tmp = _pay(tmp, k)
    return True


def _face_up_track_count(items: Tuple[ItemTile, ...], kind: str) -> int:
    """配置枠に表向きで置かれた当該種の数(回復/ドロー/上限の計算, 9.4.1/9.6.2/9.6.4)。"""
    return sum(1 for t in items if t.kind == kind and t.on_track)


def _nondamaged_sword(items: Tuple[ItemTile, ...]) -> int:
    """非損傷Sの枚数(出目上限9.2.6・無防備判定9.2.4。exhausted は問わない)。"""
    return sum(1 for t in items if t.kind == SWORD and not t.damaged)


def _has_nondamaged(items: Tuple[ItemTile, ...]) -> bool:
    return any(not t.damaged for t in items)


def _damage_one(items: Tuple[ItemTile, ...], key: Tuple) -> Tuple[ItemTile, ...]:
    """key に一致する非損傷タイル1枚を損傷ボックスへ(9.2.7)。"""
    for i, t in enumerate(items):
        if not t.damaged and _sig(t) == key:
            out = list(items)
            out[i] = replace(t, damaged=True, on_track=False)
            return _auto_place(tuple(out))
    raise AssertionError("no non-damaged tile matching %r" % (key,))


def _refresh_one(items: Tuple[ItemTile, ...], key: Tuple) -> Tuple[ItemTile, ...]:
    """key に一致する裏向きタイル1枚を表に返す(9.4.1)。"""
    for i, t in enumerate(items):
        if t.exhausted and _sig(t) == key:
            out = list(items)
            out[i] = replace(t, exhausted=False)
            return _auto_place(tuple(out))
    raise AssertionError("no face-down tile matching %r" % (key,))


def _repair_one(items: Tuple[ItemTile, ...], kind: str) -> Tuple[ItemTile, ...]:
    """当該種の損傷タイル1枚をかばんへ(裏表維持, 9.5.7)。表T/X/Bは配置枠へ。"""
    for i, t in enumerate(items):
        if t.kind == kind and t.damaged:
            out = list(items)
            out[i] = replace(t, damaged=False, on_track=False)
            return _auto_place(tuple(out))
    raise AssertionError("no damaged %s to repair" % kind)


def _remove_one(items: Tuple[ItemTile, ...], key: Tuple) -> Tuple[ItemTile, ...]:
    """key に一致するタイル1枚をゲームから除外する(9.6.4)。"""
    for i, t in enumerate(items):
        if _sig(t) == key:
            out = list(items)
            del out[i]
            return tuple(out)
    raise AssertionError("no tile matching %r" % (key,))


# ============================================================
#  派閥関係(9.2.9)のトラック操作
# ============================================================
def _rel_get(vs: VagabondState, faction: FactionId) -> int:
    for f, v in vs.relationships:
        if f == faction:
            return v
    return 0


def _rel_set(vs: VagabondState, faction: FactionId, value: int):
    out = []
    found = False
    for f, v in vs.relationships:
        if f == faction:
            out.append((f, value))
            found = True
        else:
            out.append((f, v))
    if not found:
        out.append((faction, value))
    return tuple(out)


def _aids_get(vs: VagabondState, faction: FactionId) -> int:
    for f, v in vs.aids_this_turn:
        if f == faction:
            return v
    return 0


def _aids_set(vs: VagabondState, faction: FactionId, value: int):
    out = []
    found = False
    for f, v in vs.aids_this_turn:
        if f == faction:
            out.append((f, value))
            found = True
        else:
            out.append((f, v))
    if not found:
        out.append((faction, value))
    return tuple(out)


# ============================================================
#  戦闘・除去フック(battle.py / 他派閥から呼ばれる)
# ============================================================
def vagabond_in_clearing(state: GameState, cid: int) -> bool:
    """放浪者コマが cid にいるか(他派閥の戦闘対象列挙用, 4.3)。

    放浪者コマは兵士/建物/トークンではないため既存の防御側列挙に載らない。
    放浪部族参戦時のみ True になり得る(既存3派閥の挙動は不変)。
    """
    if VAGABOND not in state.factions:
        return False
    return state.vagabond().pawn_clearing == cid


def on_vagabond_removes(state: GameState, victim: FactionId,
                        is_soldier: bool, battle: bool) -> GameState:
    """放浪部族が配置物を除去したときの関係処理(9.2.9.III / III.a)。

    - 相手が既に敵対: 部族のターン中の戦闘除去なら悪名+1VP(9.2.9.III.a)。
    - 相手が非敵対で兵士除去: ただちに敵対化(このトリガー除去自体は悪名対象外)。
    - 建物/トークン除去では敵対化しない(DESIGN.md 8.4-6)。
    """
    vs = state.vagabond()
    rel = _rel_get(vs, victim)
    if rel == -1:  # 既に敵対
        if battle and state.current_faction() == VAGABOND:
            # 悪名 +1VP(9.2.9.III.a)は中央ヘルパ経由(VP凍結・非負, 14.2)
            return award_vp(state, VAGABOND, 1)
        return state
    if is_soldier:  # 非敵対の兵士除去 → 即敵対化
        return state.with_faction_state(replace(vs, relationships=_rel_set(vs, victim, -1)))
    return state


def on_area_removal(state: GameState, cid: int) -> GameState:
    """広場の全配置物除去(連合の反乱 8.4.1.III 等)が放浪者コマの広場を対象に
    したときの読み替え(9.2.2.I): コマは除去せずアイテム3損傷を積む。"""
    if VAGABOND not in state.factions:
        return state
    vs = state.vagabond()
    if vs.pawn_clearing != cid or not _has_nondamaged(vs.items):
        return state
    return state.push_pending(ItemDamageDecision(actor=VAGABOND, remaining=3))


# ============================================================
#  セットアップ用デシジョンの選択肢(legal.py から呼ばれる)
# ============================================================
def character_options(state: GameState) -> List[Action]:
    return [VagabondChooseCharacter(player=VAGABOND, character=c)
            for c in ("thief", "tinker", "ranger")]


def forest_options(state: GameState) -> List[Action]:
    return [VagabondChooseForest(player=VAGABOND, forest=f.id)
            for f in state.map.forests]


# ============================================================
#  アイテム選択デシジョンの選択肢(legal.py から呼ばれる)
# ============================================================
def refresh_options(state: GameState, dec: RefreshDecision) -> List[Action]:
    """回復(9.4.1): 裏向きタイルの種類/状態ごと。"""
    seen = set()
    out: List[Action] = []
    for t in state.vagabond().items:
        if t.exhausted:
            k = _sig(t)
            if k in seen:
                continue
            seen.add(k)
            out.append(VagabondItemChoice(player=VAGABOND, key=k))
    return out


def damage_options(state: GameState, dec: ItemDamageDecision) -> List[Action]:
    """損傷(9.2.7 / 9.2.2.I): 非損傷タイルの種類/状態ごと(表裏を区別)。"""
    seen = set()
    out: List[Action] = []
    for t in state.vagabond().items:
        if not t.damaged:
            k = _sig(t)
            if k in seen:
                continue
            seen.add(k)
            out.append(VagabondItemChoice(player=VAGABOND, key=k))
    return out


def limit_options(state: GameState, dec: ItemLimitDecision) -> List[Action]:
    """上限調整(9.6.4): かばん+損傷ボックス(配置枠は除外)のタイルごと。"""
    seen = set()
    out: List[Action] = []
    for t in state.vagabond().items:
        if t.on_track:
            continue  # 配置枠は上限カウントに含めない(9.6.4)
        k = _sig(t)
        if k in seen:
            continue
        seen.add(k)
        out.append(VagabondItemChoice(player=VAGABOND, key=k))
    return out


# ============================================================
#  昼光アクションの選択肢
# ============================================================
def _pawn_clearing(state: GameState) -> Optional[int]:
    return state.vagabond().pawn_clearing


def _clearing_has_hostile_soldier(state: GameState, cid: int) -> bool:
    """cid に敵対派閥(rel==-1)の兵士コマが1個でもあるか(9.2.9.III.b)。"""
    vs = state.vagabond()
    cs = state.clearing(cid)
    for f, n in cs.soldiers:
        if n > 0 and _rel_get(vs, f) == -1:
            return True
    return False


def _move_options(state: GameState) -> List[Action]:
    vs = state.vagabond()
    boots = _count_payable(vs.items, BOOTS)
    if boots <= 0:
        return []
    if vs.pawn_clearing is not None:
        neighbors = state.map.clearing(vs.pawn_clearing).adjacent
    elif vs.pawn_forest is not None:
        neighbors = state.map.forest(vs.pawn_forest).adjacent_clearings
    else:
        return []
    out: List[Action] = []
    for dst in neighbors:
        need = 2 if _clearing_has_hostile_soldier(state, dst) else 1
        if boots >= need:
            out.append(VagabondMove(player=VAGABOND, dst=dst))
    return out


def _battle_options(state: GameState) -> List[Action]:
    vs = state.vagabond()
    c = vs.pawn_clearing
    if c is None or not _can_pay(vs.items, SWORD):
        return []
    cs = state.clearing(c)
    defenders = set()
    for f, n in cs.soldiers:
        if f != VAGABOND and n > 0:
            defenders.add(f)
    for p in cs.buildings + cs.tokens:
        if p.faction != VAGABOND:
            defenders.add(p.faction)
    return [VagabondBattle(player=VAGABOND, defender=d)
            for d in sorted(defenders, key=lambda f: f.value)]


def _explore_options(state: GameState) -> List[Action]:
    vs = state.vagabond()
    c = vs.pawn_clearing
    if c is None or not _can_pay(vs.items, TORCH):
        return []
    if not any(cid == c for cid, _ in vs.ruin_items):
        return []
    return [VagabondExplore(player=VAGABOND)]


def _target_item_kinds(state: GameState, faction: FactionId) -> List[str]:
    """相手派閥の作成アイテムボックスの種類一覧(援助での取得候補, 9.5.4)。"""
    out = []
    seen = set()
    for it in state.fs(faction).items:
        iv = it.value if hasattr(it, "value") else it
        if iv in seen:
            continue
        seen.add(iv)
        out.append(iv)
    return out


def _aid_options(state: GameState) -> List[Action]:
    vs = state.vagabond()
    c = vs.pawn_clearing
    if c is None or not _can_pay_any(vs.items):
        return []
    suit = state.map.clearing(c).suit
    cards = []
    seen = set()
    for cid in vs.hand:
        s = state.cards.suit_of(cid)
        if s == suit or s == Suit.BIRD:
            b = state.cards.base_id(cid)
            if b in seen:
                continue
            seen.add(b)
            cards.append(cid)
    if not cards:
        return []
    cs = state.clearing(c)
    present = set()
    for f, n in cs.soldiers:
        if f != VAGABOND and n > 0:
            present.add(f)
    for p in cs.buildings + cs.tokens:
        if p.faction != VAGABOND:
            present.add(p.faction)
    out: List[Action] = []
    for f in sorted(present, key=lambda x: x.value):
        # アイテム取得は相手の作成アイテムボックスにあるなら強制(9.5.4
        # 「アイテムがあるなら、その中から1枚を選んで…配置する」)。
        # 取得なし(None)は相手ボックスが空のときのみ合法。
        items_avail = _target_item_kinds(state, f)
        for card in cards:
            if not items_avail:
                out.append(VagabondAid(player=VAGABOND, faction=f, card_id=card, take_item=None))
            for iv in items_avail:
                out.append(VagabondAid(player=VAGABOND, faction=f, card_id=card, take_item=iv))
    return out


def _quest_options(state: GameState) -> List[Action]:
    vs = state.vagabond()
    c = vs.pawn_clearing
    if c is None:
        return []
    suit = state.map.clearing(c).suit
    out: List[Action] = []
    for qid in vs.quests_open:
        qdef = _quest_def(qid)
        if Suit(qdef["suit"]) != suit:
            continue
        if not _can_pay_items(vs.items, qdef["items"]):
            continue
        out.append(VagabondQuest(player=VAGABOND, quest_id=qid, reward="vp"))
        out.append(VagabondQuest(player=VAGABOND, quest_id=qid, reward="cards"))
    return out


def _strike_options(state: GameState) -> List[Action]:
    vs = state.vagabond()
    c = vs.pawn_clearing
    if c is None or not _can_pay(vs.items, CROSSBOW):
        return []
    cs = state.clearing(c)
    out: List[Action] = []
    for f, n in sorted(cs.soldiers, key=lambda x: x[0].value):
        if f != VAGABOND and n > 0:
            out.append(VagabondStrike(player=VAGABOND, faction=f, target=("soldier",)))
    seen = set()
    for p in cs.buildings:
        if p.faction == VAGABOND or cs.soldier_count(p.faction) > 0:
            continue
        key = (p.faction, "building", p.kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(VagabondStrike(player=VAGABOND, faction=p.faction, target=("building", p.kind)))
    for p in cs.tokens:
        if p.faction == VAGABOND or cs.soldier_count(p.faction) > 0:
            continue
        key = (p.faction, "token", p.kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(VagabondStrike(player=VAGABOND, faction=p.faction, target=("token", p.kind)))
    return out


def _repair_options(state: GameState) -> List[Action]:
    vs = state.vagabond()
    if not _can_pay(vs.items, HAMMER):
        return []
    kinds = []
    seen = set()
    for t in vs.items:
        if t.damaged and t.kind not in seen:
            seen.add(t.kind)
            kinds.append(t.kind)
    return [VagabondRepair(player=VAGABOND, kind=k) for k in kinds]


def _special_options(state: GameState) -> List[Action]:
    vs = state.vagabond()
    if not _can_pay(vs.items, TORCH):
        return []
    ch = vs.character
    if ch == "ranger":  # 隠れ家: 場所を問わず可(9.5.9 / D.3.2)
        return [VagabondSpecial(player=VAGABOND)]
    c = vs.pawn_clearing
    if c is None:
        return []
    cs = state.clearing(c)
    if ch == "thief":  # 盗み(D.1.2)
        present = set()
        for f, n in cs.soldiers:
            if f != VAGABOND and n > 0:
                present.add(f)
        for p in cs.buildings + cs.tokens:
            if p.faction != VAGABOND:
                present.add(p.faction)
        return [VagabondSpecial(player=VAGABOND, target=f)
                for f in sorted(present, key=lambda x: x.value) if state.fs(f).hand]
    if ch == "tinker":  # 日常業務(D.2.2)
        suit = state.map.clearing(c).suit
        out: List[Action] = []
        seen = set()
        for cid in state.discard:
            s = state.cards.suit_of(cid)
            if s == suit or s == Suit.BIRD:
                b = state.cards.base_id(cid)
                if b in seen:
                    continue
                seen.add(b)
                out.append(VagabondSpecial(player=VAGABOND, card_id=cid))
        return out
    return []


def _slip_options(state: GameState) -> List[Action]:
    vs = state.vagabond()
    out: List[Action] = []
    if vs.pawn_clearing is not None:
        c = vs.pawn_clearing
        for nb in state.map.clearing(c).adjacent:
            out.append(VagabondSlip(player=VAGABOND, dst=nb, dst_forest=False))
        for fid in state.map.forests_adjacent_to_clearing(c):
            out.append(VagabondSlip(player=VAGABOND, dst=fid, dst_forest=True))
    elif vs.pawn_forest is not None:
        f = state.map.forest(vs.pawn_forest)
        for nb in f.adjacent_clearings:
            out.append(VagabondSlip(player=VAGABOND, dst=nb, dst_forest=False))
        for nf in f.adjacent_forests:
            out.append(VagabondSlip(player=VAGABOND, dst=nf, dst_forest=True))
    return out


# ============================================================
#  ロジック本体
# ============================================================
class VagabondLogic(FactionLogic):
    faction = VAGABOND

    def setup(self, state: GameState, rng) -> GameState:
        # セットアップ選択(9.3.1 キャラ / 9.3.2 樹林)は game.py が Decision と
        # して積む(3.9)。クエスト山・遺跡アイテム・関係マーカーも game.py 側。
        return state

    def begin_phase(self, state: GameState, rng) -> GameState:
        if state.phase == Phase.BIRDSONG:
            return self._birdsong(state, rng)
        if state.phase == Phase.EVENING:
            return self._evening(state, rng)
        return state

    def _birdsong(self, state: GameState, rng) -> GameState:
        """鳥歌(9.4): 援助回数リセット・潜入フラグリセット → 回復(9.4.1)。"""
        vs = state.vagabond()
        vs = replace(vs, aids_this_turn=(), slip_used=False)
        state = state.with_faction_state(vs)
        vs = state.vagabond()
        cfg = state.board_defs["vagabond"]
        total = cfg["refresh_base"] + cfg["refresh_per_tea"] * _face_up_track_count(vs.items, TEA)
        facedown = sum(1 for t in vs.items if t.exhausted)
        if facedown == 0:
            return state
        if facedown <= total:
            items = tuple(replace(t, exhausted=False) if t.exhausted else t for t in vs.items)
            items = _auto_place(items)
            return state.with_faction_state(replace(vs, items=items))
        return state.push_pending(RefreshDecision(actor=VAGABOND, remaining=total))

    def _evening(self, state: GameState, rng) -> GameState:
        """夕闇(9.6): 夜の休息 → ドロー → 手札調整 → アイテム上限確認。"""
        vs = state.vagabond()
        # 9.6.1 夜の休息: 樹林なら損傷全回復(表向きにして戻す)
        if vs.pawn_forest is not None and any(t.damaged for t in vs.items):
            items = tuple(replace(t, damaged=False, on_track=False, exhausted=False)
                          if t.damaged else t for t in vs.items)
            items = _auto_place(items)
            state = state.with_faction_state(replace(vs, items=items))
            vs = state.vagabond()
        # 9.6.2 ドロー(1 + 配置枠の表向きX数)
        cfg = state.board_defs["vagabond"]
        draw = cfg["draw_per_coin"] * _face_up_track_count(vs.items, COINS)
        draw += 1  # 基本1枚
        state = draw_cards(state, VAGABOND, draw, rng)
        decisions = []
        # 9.6.3 手札6枚以上なら5枚へ
        if len(state.vagabond().hand) > 5:
            decisions.append(DiscardDecision(actor=VAGABOND))
        # 9.6.4 アイテム上限
        if _over_limit(state):
            decisions.append(ItemLimitDecision(actor=VAGABOND))
        if decisions:
            state = state.push_pending(*decisions)
        return state

    def legal_actions(self, state: GameState) -> List[Action]:
        if state.phase == Phase.BIRDSONG:
            acts: List[Action] = []
            if not state.vagabond().slip_used:
                acts.extend(_slip_options(state))
            acts.append(EndPhase(player=VAGABOND))
            return acts
        if state.phase == Phase.DAYLIGHT:
            return self._daylight_actions(state)
        return [EndPhase(player=VAGABOND)]  # 夕闇は強制処理のみ

    def _daylight_actions(self, state: GameState) -> List[Action]:
        acts: List[Action] = []
        acts.extend(_move_options(state))      # 9.5.1
        acts.extend(_battle_options(state))    # 9.5.2
        acts.extend(_explore_options(state))   # 9.5.3
        acts.extend(_aid_options(state))       # 9.5.4
        acts.extend(_quest_options(state))     # 9.5.5
        acts.extend(_strike_options(state))    # 9.5.6
        acts.extend(_repair_options(state))    # 9.5.7
        acts.extend(legal_crafts(state, VAGABOND))  # 9.5.8
        acts.extend(_special_options(state))   # 9.5.9
        acts.append(EndPhase(player=VAGABOND))
        return acts


def _over_limit(state: GameState) -> bool:
    vs = state.vagabond()
    cfg = state.board_defs["vagabond"]
    limit = cfg["item_limit_base"] + cfg["item_limit_per_bag"] * _face_up_track_count(vs.items, BAG)
    held = sum(1 for t in vs.items if not t.on_track)
    return held > limit


# ============================================================
#  アクション適用(apply.py から呼ばれる)
# ============================================================
def apply_choose_character(state: GameState, action: VagabondChooseCharacter, rng) -> GameState:
    """キャラ確定(9.3.1)+開始時アイテム配置(9.3.5)。"""
    state = state.pop_pending()
    vs = state.vagabond()
    start = state.board_defs["vagabond"]["characters"][action.character]["start_items"]
    items: Tuple[ItemTile, ...] = ()
    for kind in start:
        items = _add_item(items, kind)
    return state.with_faction_state(replace(vs, character=action.character, items=items))


def apply_choose_forest(state: GameState, action: VagabondChooseForest, rng) -> GameState:
    """開始樹林の配置(9.3.2)。"""
    state = state.pop_pending()
    vs = state.vagabond()
    return state.with_faction_state(replace(vs, pawn_forest=action.forest, pawn_clearing=None))


def apply_slip(state: GameState, action: VagabondSlip, rng) -> GameState:
    """潜入(9.4.2)。無償・支配条件無視。蜂起(8.2.6)は放浪者移動では発火しない。"""
    vs = state.vagabond()
    if action.dst_forest:
        vs = replace(vs, pawn_forest=action.dst, pawn_clearing=None, slip_used=True)
    else:
        vs = replace(vs, pawn_clearing=action.dst, pawn_forest=None, slip_used=True)
    return state.with_faction_state(vs)


def apply_move(state: GameState, action: VagabondMove, rng) -> GameState:
    """移動(9.5.1)。M1(+敵対兵士のいる広場へは追加M1, 9.2.9.III.b)。蜂起なし。"""
    vs = state.vagabond()
    need = 2 if _clearing_has_hostile_soldier(state, action.dst) else 1
    items = vs.items
    for _ in range(need):
        items = _pay(items, BOOTS)
    return state.with_faction_state(
        replace(vs, items=items, pawn_clearing=action.dst, pawn_forest=None))


def apply_battle(state: GameState, action: VagabondBattle, rng) -> GameState:
    """戦闘(9.5.2)。S1を払い、現在広場で戦闘宣言(4.3)。"""
    from .. import battle as battle_mod
    vs = state.vagabond()
    c = vs.pawn_clearing
    items = _pay(vs.items, SWORD)
    state = state.with_faction_state(replace(vs, items=items, damage_hits_this_battle=0))
    decl = DeclareBattle(player=VAGABOND, clearing=c, defender=action.defender)
    return battle_mod.declare_battle(state, decl, rng)


def apply_explore(state: GameState, action: VagabondExplore, rng) -> GameState:
    """探索(9.5.3)。F1を払い、遺跡アイテム獲得+1VP。空になった遺跡を除去。"""
    vs = state.vagabond()
    c = vs.pawn_clearing
    items = _pay(vs.items, TORCH)
    ruin = list(vs.ruin_items)
    idx = next(i for i, (cid, _) in enumerate(ruin) if cid == c)
    _, kind = ruin.pop(idx)
    items = _add_item(items, kind)
    vs = replace(vs, items=items, ruin_items=tuple(ruin))
    state = state.with_faction_state(vs)
    # 探索の +1VP(9.5.3)は中央ヘルパ経由(VP凍結・非負, 14.2)
    state = award_vp(state, VAGABOND, 1)
    if not any(cid == c for cid, _ in ruin):
        cs = state.clearing(c)
        if cs.ruin:
            state = state.with_clearing(dataclasses.replace(cs, ruin=False))
    return state


def apply_aid(state: GameState, action: VagabondAid, rng) -> GameState:
    """援助(9.5.4)。任意アイテム1を払い、手札1枚を相手へ・相手作成アイテムを取得可。"""
    vs = state.vagabond()
    items = _pay_any(vs.items)
    hand = list(vs.hand)
    hand.remove(action.card_id)
    state = state.with_faction_state(replace(vs, items=items, hand=tuple(hand)))
    # 相手へカードを渡す
    tfs = state.fs(action.faction)
    state = state.with_faction_state(replace(tfs, hand=tfs.hand + (action.card_id,)))
    # 相手の作成アイテムを取得(任意)
    if action.take_item is not None:
        tfs = state.fs(action.faction)
        titems = list(tfs.items)
        titems.remove(ItemKind(action.take_item))
        state = state.with_faction_state(replace(tfs, items=tuple(titems)))
        vs = state.vagabond()
        state = state.with_faction_state(replace(vs, items=_add_item(vs.items, action.take_item)))
    return _adjust_relationship_on_aid(state, action.faction)


def _adjust_relationship_on_aid(state: GameState, faction: FactionId) -> GameState:
    """援助後の関係処理(8.5 / 9.2.9.I / II.a / III.c)。"""
    vs = state.vagabond()
    cfg = state.board_defs["vagabond"]
    rel = _rel_get(vs, faction)
    if rel == -1:  # 敵対: 関係は動かない(III.c)。アイテム取得は上で完了済み
        return state
    if rel >= 3:  # 同盟: 援助毎+2VP(II.a)。中央ヘルパ経由(VP凍結・非負, 14.2)
        return award_vp(state, VAGABOND, cfg["allied_aid_vp"])
    aids = _aids_get(vs, faction) + 1
    cost = cfg["relationship_aid_costs"][rel]
    if aids >= cost:  # 強化(I.b): 1マス進めて到達マスのVP、援助回数リセット
        gain = cfg["relationship_vp"][rel]
        vs = replace(vs, relationships=_rel_set(vs, faction, rel + 1),
                     aids_this_turn=_aids_set(vs, faction, 0))
        state = state.with_faction_state(vs)
        return award_vp(state, VAGABOND, gain)
    vs = replace(vs, aids_this_turn=_aids_set(vs, faction, aids))
    return state.with_faction_state(vs)


def apply_quest(state: GameState, action: VagabondQuest, rng) -> GameState:
    """クエスト(9.5.5)。2アイテム消費 → 報酬(VP or 2ドロー)→ 山から1枚補充。"""
    vs = state.vagabond()
    qdef = _quest_def(action.quest_id)
    items = vs.items
    for k in qdef["items"]:
        items = _pay(items, k)
    open_ = list(vs.quests_open)
    open_.remove(action.quest_id)
    deck = list(vs.quest_deck)
    if deck:
        open_.append(deck.pop())  # 山の上から1枚補充("Claim a quest and replace it.")
    done = vs.quests_done + (action.quest_id,)
    vs = replace(vs, items=items, quests_open=tuple(open_),
                 quest_deck=tuple(deck), quests_done=done)
    state = state.with_faction_state(vs)
    if action.reward == "vp":
        suit = qdef["suit"]
        n = sum(1 for q in done if _quest_def(q)["suit"] == suit)  # 今解決分を含む
        # クエスト報酬VP(9.5.5)は中央ヘルパ経由(VP凍結・非負, 14.2)
        state = award_vp(state, VAGABOND, n)
    else:  # cards: 2ドロー
        state = draw_cards(state, VAGABOND, 2, rng)
    return state


def apply_strike(state: GameState, action: VagabondStrike, rng) -> GameState:
    """狙撃(9.5.6)。C1を払い配置物1つを除去。戦闘ではないので悪名なし(敵対化はあり)。"""
    from .. import battle as battle_mod
    vs = state.vagabond()
    c = vs.pawn_clearing
    items = _pay(vs.items, CROSSBOW)
    state = state.with_faction_state(replace(vs, items=items))
    return battle_mod.remove_piece(state, c, action.faction, action.target, VAGABOND, battle=False)


def apply_repair(state: GameState, action: VagabondRepair, rng) -> GameState:
    """修理(9.5.7)。H1を払い、損傷1枚をかばんへ(表T/X/Bは配置枠へ)。"""
    vs = state.vagabond()
    items = _pay(vs.items, HAMMER)
    items = _repair_one(items, action.kind)
    return state.with_faction_state(replace(vs, items=items))


def apply_craft_vagabond(state: GameState, action, rng) -> GameState:
    """クラフト(9.5.8)。Hをコストシンボル数ぶん払い、アイテム獲得+VP。"""
    from ..mechanics import discard_card
    cdef = state.cards.get(action.card_id)
    item = ItemKind(cdef.effect["item"])
    vp = int(cdef.effect.get("vp", 0))
    vs = state.vagabond()
    items = vs.items
    for _ in range(len(cdef.cost)):
        items = _pay(items, HAMMER)
    items = _add_item(items, item.value)
    state = state.with_faction_state(replace(vs, items=items))
    # クラフトVP(3.2.2)は中央ヘルパ経由(VP凍結・非負, 14.2)
    state = award_vp(state, VAGABOND, vp)
    state = state.take_item(item)
    return discard_card(state, VAGABOND, action.card_id)


def apply_special(state: GameState, action: VagabondSpecial, rng) -> GameState:
    """特別アクション(9.5.9)。F1を払い、キャラクターのアクションを実行。"""
    vs = state.vagabond()
    items = _pay(vs.items, TORCH)
    state = state.with_faction_state(replace(vs, items=items))
    ch = state.vagabond().character
    if ch == "thief":
        return _do_steal(state, action.target, rng)
    if ch == "tinker":
        return _do_day_labor(state, action.card_id)
    if ch == "ranger":
        return _do_hideout(state, rng)
    return state


def _do_steal(state: GameState, target: FactionId, rng) -> GameState:
    """盗み(D.1.2): 対象の手札からランダム1枚を獲得。"""
    tfs = state.fs(target)
    if not tfs.hand:
        return state
    hand = list(tfs.hand)
    card = hand.pop(rng.randrange(len(hand)))
    state = state.with_faction_state(replace(tfs, hand=tuple(hand)))
    vs = state.vagabond()
    return state.with_faction_state(replace(vs, hand=vs.hand + (card,)))


def _do_day_labor(state: GameState, card_id: str) -> GameState:
    """日常業務(D.2.2): 捨て山の一致カード1枚を手札へ。"""
    discard = list(state.discard)
    discard.remove(card_id)
    state = state.replace(discard=tuple(discard))
    vs = state.vagabond()
    return state.with_faction_state(replace(vs, hand=vs.hand + (card_id,)))


def _do_hideout(state: GameState, rng) -> GameState:
    """隠れ家(D.3.2): 3枚まで修理し、ただちに昼光を終え夕闇へ(鷲巣の休止と同型)。"""
    vs = state.vagabond()
    out = []
    count = 0
    for t in vs.items:
        if t.damaged and count < 3:
            out.append(replace(t, damaged=False, on_track=False))  # 裏表は維持
            count += 1
        else:
            out.append(t)
    items = _auto_place(tuple(out))
    state = state.with_faction_state(replace(vs, items=items))
    state = state.replace(phase=Phase.EVENING)
    from . import get_logic
    return get_logic(VAGABOND).begin_phase(state, rng)


# ---- アイテム選択デシジョンへの応答 ----
def apply_refresh_choice(state: GameState, action: VagabondItemChoice, rng) -> GameState:
    dec = state.pending[-1]
    state = state.pop_pending()
    vs = state.vagabond()
    state = state.with_faction_state(replace(vs, items=_refresh_one(vs.items, action.key)))
    remaining = dec.remaining - 1
    if remaining > 0 and any(t.exhausted for t in state.vagabond().items):
        state = state.push_pending(replace(dec, remaining=remaining))
    return state


def apply_damage_choice(state: GameState, action: VagabondItemChoice, rng) -> GameState:
    from .. import battle as battle_mod
    dec = state.pending[-1]
    state = state.pop_pending()
    vs = state.vagabond()
    state = state.with_faction_state(replace(
        vs, items=_damage_one(vs.items, action.key),
        damage_hits_this_battle=vs.damage_hits_this_battle + 1))
    remaining = dec.remaining - 1
    if remaining > 0 and _has_nondamaged(state.vagabond().items):
        return state.push_pending(replace(dec, remaining=remaining))
    if dec.roll_after and dec.ctx is not None:  # 奇襲2ヒット後のロール継続(4.3.1.II)
        state = battle_mod.roll_battle(state, dec.ctx, rng)
    return state


def apply_limit_choice(state: GameState, action: VagabondItemChoice, rng) -> GameState:
    dec = state.pending[-1]
    state = state.pop_pending()
    vs = state.vagabond()
    state = state.with_faction_state(replace(vs, items=_remove_one(vs.items, action.key)))
    if _over_limit(state):
        state = state.push_pending(dec)
    return state


register(VagabondLogic())
