"""行動カタログ: 固定インデックス行動空間+合法手マスク(DESIGN.md 12.2)。

PPO(6c)の行動空間は**固定長**が必要。全 :class:`~engine.actions.Action` を
「正準キー」に写し、キーの全列挙に不変なインデックスを振る。

- :func:`action_key` : Action → hashable キー。**不変条件: 同一 legal_actions 内で
  キーが衝突する2アクションは交換可能(どちらを適用しても同値)。**
- :class:`ActionCatalog` : 全キーの決定的列挙。静的データ
  (map_autumn.json / cards.json / quests.json / enum 定義)のみから構築し、
  set 反復・dict 順に依存しない(エンジン 10.2 の決定性制約と同じ)。
- :func:`legal_mask` / :func:`action_for` : 状態依存のマスクとインデックス→Action 解決。

死にインデックス(実現不能なキー)は許容する — マスクが常に False になるだけで
学習に無害(12.2)。numpy への依存は :func:`legal_mask` の内部のみに閉じ込め、
カタログ構築・キー算出は標準ライブラリだけで動く。
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

from engine.board import load_map
from engine.cards import load_card_defs
from engine.crafting import _EFFECT_WHITELIST
from engine.legal import legal_actions
from engine.types import (
    B_BASE,
    B_ROOST,
    Corner,
    EYRIE_LEADERS,
    FactionId,
    ItemKind,
    LOYAL_VIZIER,
    MARQUISE_BUILDINGS,
    Suit,
    T_KEEP,
    T_SYMPATHY,
    T_WOOD,
)

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "engine", "data")

#: カタログのバージョン。キー空間(catalog.size)が変わる変更のたびに増やす。
#: ckpt に保存し resume 時の非互換を検出する(14.7。旧 ckpt を無言で壊さない)。
#: v5(19.4): 支払い選択のデシジョン化で MarquiseChooseWood 12 +
#: AllianceSpendSupporter 4 + VagabondExhaustItem 8 + VagabondRepairItem 8
#: = 32 キー追加。
CATALOG_VERSION = 5


# ============================================================
#  静的ドメイン(すべて定義順・リスト/タプルで決定的に列挙する)
# ============================================================
_MAP = load_map()
#: 広場IDの昇順(map_autumn.json 定義順, 0..11)
CLEARINGS: Tuple[int, ...] = tuple(c.id for c in _MAP.clearings)
#: 樹林IDの昇順(0..6)
FORESTS: Tuple[int, ...] = tuple(f.id for f in _MAP.forests)
#: 隣接ペア(有向・両方向)。clearings[].adjacent の記載順(12.2 の根拠)。
ADJ_PAIRS: Tuple[Tuple[int, int], ...] = tuple(
    (c.id, dst) for c in _MAP.clearings for dst in c.adjacent
)

_CARD_DEFS, _ = load_card_defs()
#: カードの base_id(cards.json = CardIndex.defs 定義順)。インスタンスの "#n" は付かない。
CARD_BASE_IDS: Tuple[str, ...] = tuple(d.id for d in _CARD_DEFS)

#: 圧倒カードの base_id 4種(cards.json 定義順, is_dominance で抽出, 14.7)。
#: ActivateDominance の base_id ドメイン、TakeDominance の dominance_base_id ドメイン、
#: VagabondCoalition の base_id ドメインに使う。
DOMINANCE_BASE_IDS: Tuple[str, ...] = tuple(d.id for d in _CARD_DEFS if d.is_dominance)

#: 継続効果カード(persistent×ホワイトリスト, 18.2)の base_id 10種
#: (cards.json 定義順, 18.5)。UseCraftedEffect の card_key ドメイン。
#: immediate(Favor三種)はクラフト時に即時解決され UseCraftedEffect
#: アクションにならないため含めない。
USE_EFFECT_KEYS: Tuple[str, ...] = tuple(
    d.id for d in _CARD_DEFS
    if d.effect is not None and d.effect.get("type") == "persistent"
    and d.id in _EFFECT_WHITELIST)


def _load_quest_ids() -> Tuple[str, ...]:
    """quests.json の定義順のクエストID(9.3.3)。"""
    with open(os.path.join(_DATA_DIR, "quests.json"), "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return tuple(q["id"] for q in raw)


QUEST_IDS: Tuple[str, ...] = _load_quest_ids()
QUEST_REWARDS: Tuple[str, ...] = ("vp", "cards")

#: 動物種(Suit enum 定義順: fox/rabbit/mouse/bird)。勅令系は suit に縮約(4種)。
SUITS: Tuple[Suit, ...] = tuple(Suit)
#: 防御側/対象派閥(FactionId enum 定義順の全メンバー, 死にインデックス許容, 12.2)
DEFENDERS: Tuple[FactionId, ...] = tuple(FactionId)
#: 隅(Corner enum 定義順)の value 文字列(SetupChooseKeep/EyrieChooseCorner の corner)
CORNER_VALUES: Tuple[str, ...] = tuple(c.value for c in Corner)
#: 君主4種(types.EYRIE_LEADERS)
LEADERS: Tuple[str, ...] = tuple(EYRIE_LEADERS)
#: キャラクター3種(vagabond.character_options と同順)
CHARACTERS: Tuple[str, ...] = ("thief", "tinker", "ranger")
#: アイテム種8種(ItemKind 定義順)の value 文字列
ITEM_KIND_VALUES: Tuple[str, ...] = tuple(k.value for k in ItemKind)
#: 猫の建設可能な建物3種
MARQUISE_BUILD_KINDS: Tuple[str, ...] = tuple(MARQUISE_BUILDINGS)
#: 勅令の列 0=募兵 1=移動 2=戦闘 3=建設(7.5.2)
DECREE_COLUMNS: Tuple[int, ...] = (0, 1, 2, 3)

#: 狙撃/ヒット割り振りの target 列挙(building5種+token3種+soldier, 12.2)。
#:   building: 猫3(sawmill/workshop/recruiter)+鷲巣(roost)+連合(base)
#:   token: keep/wood/sympathy
_BUILDING_KINDS: Tuple[str, ...] = MARQUISE_BUILDINGS + (B_ROOST, B_BASE)
_TOKEN_KINDS: Tuple[str, ...] = (T_KEEP, T_WOOD, T_SYMPATHY)
STRIKE_TARGETS: Tuple[Tuple, ...] = (
    (("soldier",),)
    + tuple(("building", k) for k in _BUILDING_KINDS)
    + tuple(("token", k) for k in _TOKEN_KINDS)
)
#: 援助で取得するアイテム(ItemKind 8種の value + None=取らない)
_AID_TAKE: Tuple[Optional[str], ...] = ITEM_KIND_VALUES + (None,)

#: count 上限(サプライ上限=死にインデックス安全な上界, state.MAX_SOLDIERS 由来)
_MARCH_MAX = 25       # 猫兵士25(6.3.1)
_DECREE_MOVE_MAX = 20  # 鷲巣兵士20(7.3.1)
_OP_MOVE_MAX = 10     # 連合兵士10(8.3.1)

#: パラメータなしのアクション型名(キー=(型名,))
_PARAMLESS = (
    "EndPhase", "MarquiseRecruit", "EyrieSkipDecree", "EyrieTurmoil",
    "AllianceEndOps", "VagabondExplore", "MarquiseSkipMove",
    "SkipBattleEffects",
)
#: キー=(型名, base_id) のアクション型名(手札を離れるカードは銘柄が戦略価値を持つ)
_BASEID_ACTIONS = (
    "CraftCard", "DiscardCard", "MarquisePlayBirdCard",
    "AllianceMobilize", "AllianceTrain", "AllianceDiscardSupporter",
)
#: キー=(型名, clearing) の連合アクション型名
_ALLIANCE_CLEARING = (
    "AllianceRevolt", "AllianceSpreadSympathy",
    "AllianceOpRecruit", "AllianceOpOrganize",
)


def _suit_of(state, card_id: str) -> Suit:
    """カードの動物種を返す(勅令の忠臣カードは山札に無いため鳥に読み替え)。"""
    base = state.cards.base_id(card_id)
    if base == LOYAL_VIZIER:
        return Suit.BIRD  # 忠臣(7.3.4)は動物種=鳥
    return state.cards.suit_of(card_id)


def action_key(state, action) -> Tuple:
    """Action を正準キー(hashable タプル)に写す(12.2)。

    先頭要素は必ずアクションのクラス名。カード実体は base_id に正規化する
    (state.cards.base_id: インスタンスIDの "#n" を除去)。
    """
    name = type(action).__name__
    if name in _PARAMLESS:
        return (name,)
    if name in _BASEID_ACTIONS:
        return (name, state.cards.base_id(action.card_id))
    if name in ("AmbushChoice", "OutragePay", "MarquiseFieldHospital"):
        cid = action.card_id
        return (name, None if cid is None else state.cards.base_id(cid))
    if name in ("DeclareBattle", "AllianceOpBattle"):
        return (name, action.clearing, action.defender)
    if name == "MarquiseBuild":
        return (name, action.clearing, action.kind)
    if name == "MarquiseMarch":
        return (name, action.src, action.dst, action.count)
    if name == "MarquiseLabor":
        return (name, action.clearing, state.cards.base_id(action.card_id))
    if name in ("SetupChooseKeep", "EyrieChooseCorner"):
        return (name, action.corner)
    if name == "EyrieChooseLeader":
        return (name, action.leader)
    if name == "EyrieAddToDecree":
        return (name, state.cards.base_id(action.card_id), action.column)
    if name == "EyriePlaceRoost":
        return (name, action.clearing)
    if name in ("EyrieDecreeBuild", "EyrieRecruit"):
        # 勅令系: カードがボードに残り銘柄が無意味 → suit に縮約(12.2)
        return (name, _suit_of(state, action.card_id), action.clearing)
    if name == "EyrieDecreeMove":
        return (name, _suit_of(state, action.card_id), action.src, action.dst, action.count)
    if name == "EyrieDecreeBattle":
        return (name, _suit_of(state, action.card_id), action.clearing, action.defender)
    if name in _ALLIANCE_CLEARING:
        return (name, action.clearing)
    if name == "AllianceOpMove":
        return (name, action.src, action.dst, action.count)
    if name == "VagabondChooseCharacter":
        return (name, action.character)
    if name == "VagabondChooseForest":
        return (name, action.forest)
    if name == "VagabondSlip":
        return (name, action.dst, action.dst_forest)
    if name == "VagabondMove":
        return (name, action.dst)
    if name == "VagabondBattle":
        return (name, action.defender)
    if name == "VagabondAid":
        return (name, action.faction, state.cards.base_id(action.card_id), action.take_item)
    if name == "VagabondQuest":
        return (name, action.quest_id, action.reward)
    if name == "VagabondStrike":
        return (name, action.faction, action.target)
    if name in ("VagabondRepair", "VagabondExhaustItem", "VagabondRepairItem"):
        return (name, action.kind)
    if name == "MarquiseChooseWood":
        return (name, action.clearing)
    if name == "AllianceSpendSupporter":
        return (name, action.suit)
    if name == "VagabondSpecial":
        base = None if action.card_id is None else state.cards.base_id(action.card_id)
        return (name, action.target, base)
    if name == "AllocateHit":
        return (name, action.target)
    if name == "VagabondItemChoice":
        # key はすでに (kind, exhausted, damaged, on_track) のタプル(actions.py)
        return (name,) + tuple(action.key)
    if name == "ActivateDominance":
        return (name, state.cards.base_id(action.card_id))
    if name == "TakeDominance":
        return (name, state.cards.base_id(action.spend_card_id),
                state.cards.base_id(action.dominance_id))
    if name == "VagabondCoalition":
        return (name, state.cards.base_id(action.card_id), action.partner)
    if name == "UseCraftedEffect":
        # card_key はすでに base_id(18.3/18.4)
        return (name, action.card_key, action.target_faction, action.target_clearing)
    raise KeyError("action_key: unknown action type %s" % name)


def _build_keys() -> List[Tuple]:
    """全キーの決定的列挙(DESIGN.md 12.2 のキー設計表の順序)。"""
    keys: List[Tuple] = []
    add = keys.append

    # パラメータなし
    for n in _PARAMLESS:
        add((n,))
    # (型名, base_id)
    for n in _BASEID_ACTIONS:
        for b in CARD_BASE_IDS:
            add((n, b))
    # AmbushChoice / OutragePay / MarquiseFieldHospital : (型名, base_id or None)
    for n in ("AmbushChoice", "OutragePay", "MarquiseFieldHospital"):
        add((n, None))
        for b in CARD_BASE_IDS:
            add((n, b))
    # DeclareBattle / AllianceOpBattle : (型名, clearing, defender)
    for n in ("DeclareBattle", "AllianceOpBattle"):
        for c in CLEARINGS:
            for d in DEFENDERS:
                add((n, c, d))
    # MarquiseBuild : (型名, clearing, kind)
    for c in CLEARINGS:
        for k in MARQUISE_BUILD_KINDS:
            add(("MarquiseBuild", c, k))
    # MarquiseMarch : (型名, src, dst, count)
    for (s, d) in ADJ_PAIRS:
        for cnt in range(1, _MARCH_MAX + 1):
            add(("MarquiseMarch", s, d, cnt))
    # MarquiseLabor : (型名, clearing, base_id)
    for c in CLEARINGS:
        for b in CARD_BASE_IDS:
            add(("MarquiseLabor", c, b))
    # SetupChooseKeep / EyrieChooseCorner : (型名, corner)
    for n in ("SetupChooseKeep", "EyrieChooseCorner"):
        for cn in CORNER_VALUES:
            add((n, cn))
    # EyrieChooseLeader : (型名, leader)
    for l in LEADERS:
        add(("EyrieChooseLeader", l))
    # EyrieAddToDecree : (型名, base_id, column)
    for b in CARD_BASE_IDS:
        for col in DECREE_COLUMNS:
            add(("EyrieAddToDecree", b, col))
    # EyriePlaceRoost : (型名, clearing)
    for c in CLEARINGS:
        add(("EyriePlaceRoost", c))
    # EyrieDecreeBuild / EyrieRecruit : (型名, suit, clearing)
    for n in ("EyrieDecreeBuild", "EyrieRecruit"):
        for s in SUITS:
            for c in CLEARINGS:
                add((n, s, c))
    # EyrieDecreeMove : (型名, suit, src, dst, count)
    for s in SUITS:
        for (a, b) in ADJ_PAIRS:
            for cnt in range(1, _DECREE_MOVE_MAX + 1):
                add(("EyrieDecreeMove", s, a, b, cnt))
    # EyrieDecreeBattle : (型名, suit, clearing, defender)
    for s in SUITS:
        for c in CLEARINGS:
            for d in DEFENDERS:
                add(("EyrieDecreeBattle", s, c, d))
    # AllianceRevolt / SpreadSympathy / OpRecruit / OpOrganize : (型名, clearing)
    for n in _ALLIANCE_CLEARING:
        for c in CLEARINGS:
            add((n, c))
    # AllianceOpMove : (型名, src, dst, count)
    for (a, b) in ADJ_PAIRS:
        for cnt in range(1, _OP_MOVE_MAX + 1):
            add(("AllianceOpMove", a, b, cnt))
    # VagabondChooseCharacter : (型名, character)
    for ch in CHARACTERS:
        add(("VagabondChooseCharacter", ch))
    # VagabondChooseForest : (型名, forest)
    for f in FORESTS:
        add(("VagabondChooseForest", f))
    # VagabondSlip : (型名, dst, dst_forest)。広場12(False)+樹林7(True)
    for c in CLEARINGS:
        add(("VagabondSlip", c, False))
    for f in FORESTS:
        add(("VagabondSlip", f, True))
    # VagabondMove : (型名, dst)
    for c in CLEARINGS:
        add(("VagabondMove", c))
    # VagabondBattle : (型名, defender)
    for d in DEFENDERS:
        add(("VagabondBattle", d))
    # VagabondAid : (型名, faction, base_id, take_item or None)
    for f in DEFENDERS:
        for b in CARD_BASE_IDS:
            for it in _AID_TAKE:
                add(("VagabondAid", f, b, it))
    # VagabondQuest : (型名, quest_id, reward)
    for q in QUEST_IDS:
        for r in QUEST_REWARDS:
            add(("VagabondQuest", q, r))
    # VagabondStrike : (型名, faction, target)
    for f in DEFENDERS:
        for t in STRIKE_TARGETS:
            add(("VagabondStrike", f, t))
    # VagabondRepair : (型名, kind)
    for k in ITEM_KIND_VALUES:
        add(("VagabondRepair", k))
    # VagabondSpecial : (型名, target or None, base_id or None)
    #   盗み=(faction,None) / 日常業務=(None,base) / 隠れ家=(None,None)
    for f in DEFENDERS:
        add(("VagabondSpecial", f, None))
    for b in CARD_BASE_IDS:
        add(("VagabondSpecial", None, b))
    add(("VagabondSpecial", None, None))
    # AllocateHit : (型名, target)。VagabondStrike と同じ target 列挙
    for t in STRIKE_TARGETS:
        add(("AllocateHit", t))
    # VagabondItemChoice : (型名, kind, exhausted, damaged, on_track)
    for k in ITEM_KIND_VALUES:
        for ex in (False, True):
            for dm in (False, True):
                for ot in (False, True):
                    add(("VagabondItemChoice", k, ex, dm, ot))
    # ActivateDominance : (型名, base_id[圧倒4種のみ])(14.7)
    for b in DOMINANCE_BASE_IDS:
        add(("ActivateDominance", b))
    # TakeDominance : (型名, spend_base_id[全カード], dominance_base_id[圧倒4種])(14.7)
    for spend_b in CARD_BASE_IDS:
        for dom_b in DOMINANCE_BASE_IDS:
            add(("TakeDominance", spend_b, dom_b))
    # VagabondCoalition : (型名, base_id[圧倒4種], partner[FactionId全メンバー])(14.7)
    for b in DOMINANCE_BASE_IDS:
        for partner in DEFENDERS:
            add(("VagabondCoalition", b, partner))
    # UseCraftedEffect : (型名, card_key, target_faction?, target_clearing?)(18.5)。
    #   パラメータなし系(royal-claim/command-warren/cobbler/戦闘効果3種)=(key,None,None)、
    #   対象派閥系(stand-and-deliver/better-burrow-bank)=(key,faction,None)、
    #   tax-collector=(key,None,clearing)。(key,None,None) の死にキーは許容(12.2)。
    for k in USE_EFFECT_KEYS:
        add(("UseCraftedEffect", k, None, None))
    for k in ("stand-and-deliver", "better-burrow-bank"):
        for f in DEFENDERS:
            add(("UseCraftedEffect", k, f, None))
    for c in CLEARINGS:
        add(("UseCraftedEffect", "tax-collector", None, c))
    # --- catalog v5(19.4): 支払い選択のデシジョン化 ---
    # MarquiseChooseWood : (型名, clearing)(19.1)
    for c in CLEARINGS:
        add(("MarquiseChooseWood", c))
    # AllianceSpendSupporter : (型名, suit)(19.2)
    for s in SUITS:
        add(("AllianceSpendSupporter", s))
    # VagabondExhaustItem / VagabondRepairItem : (型名, kind)(19.3)
    for n in ("VagabondExhaustItem", "VagabondRepairItem"):
        for k in ITEM_KIND_VALUES:
            add((n, k))
    return keys


class ActionCatalog:
    """全キーの決定的列挙とインデックス。`index_of`/`key_at`/`size`(12.2)。"""

    def __init__(self) -> None:
        keys = _build_keys()
        self._keys: Tuple[Tuple, ...] = tuple(keys)
        self._index: Dict[Tuple, int] = {k: i for i, k in enumerate(self._keys)}
        # 交換可能でないキーの衝突(=列挙バグ)を早期に検出する。
        assert len(self._index) == len(self._keys), (
            "catalog has duplicate keys: %d unique / %d total"
            % (len(self._index), len(self._keys)))
        self.size: int = len(self._keys)

    def index_of(self, key: Tuple) -> int:
        return self._index[key]

    def get_index(self, key: Tuple) -> Optional[int]:
        """キーが存在すればインデックス、無ければ None(死にキー照会用)。"""
        return self._index.get(key)

    def key_at(self, index: int) -> Tuple:
        return self._keys[index]

    def __len__(self) -> int:
        return self.size


def legal_mask(state, catalog: ActionCatalog):
    """合法手マスク ``np.bool_[size]`` を返す(12.2)。numpy はここでのみ使用。"""
    import numpy as np

    mask = np.zeros(catalog.size, dtype=np.bool_)
    for a in legal_actions(state):
        # 全合法手はカタログに載っている設計(12.2)。載っていなければ列挙バグ
        # なので黙って落とさず即座に失敗させる(学習中の無言劣化を防ぐ)。
        mask[catalog.index_of(action_key(state, a))] = True
    return mask


def action_for(state, index: int, catalog: ActionCatalog, actions=None):
    """インデックス→Action(12.2)。

    合法手のうちキー一致の**最初**(legal_actions 順)を決定的に返す。
    一致が無い(=マスク False のインデックス)場合は None。``actions`` に
    現在の legal_actions を渡せば再計算を省ける(env の高速化用)。
    """
    key = catalog.key_at(index)
    if actions is None:
        actions = legal_actions(state)
    for a in actions:
        if action_key(state, a) == key:
            return a
    return None
