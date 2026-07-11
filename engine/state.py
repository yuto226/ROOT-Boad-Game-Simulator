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
    B_BASE,
    B_ROOST,
    CLEARING_SUITS,
    FactionId,
    ItemKind,
    LOYAL_VIZIER,
    MARQUISE_BUILDINGS,
    Phase,
    Piece,
    Suit,
    T_KEEP,
    T_SYMPATHY,
    T_WOOD,
)

# --- 派閥ごとの兵士サプライ上限(サプライ+盤上の合計 ≤ 上限, 9.4) ---
# engine/game.py の _initial_faction_state の初期サプライ値と同期させること。
# 出典: Law of Root 6.3.1(猫25)・7.3.1(鷲巣20)・8.3.1(連合10)。
# DUMMY/VAGABOND 等の未対応派閥は当面チェック対象外(None 扱い)。
MAX_SOLDIERS: Dict[FactionId, int] = {
    FactionId.MARQUISE: 25,
    FactionId.EYRIE: 20,
    FactionId.ALLIANCE: 10,
}
#: 木材トークン上限(猫)。出典: game.py _initial_faction_state の wood_supply=8(6.3.1)。
MAX_WOOD = 8
#: 支持トークン上限(連合)。出典: AllianceState docstring "0..10"(支持エリアトラック, 8.2)。
MAX_SYMPATHY = 10
#: 城砦トークン上限(猫)。出典: 6.2.2(城砦は1個のみ)。
MAX_KEEP = 1

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
    #: 手元の継続効果カード(immediate/persistent クラフト効果, 4.1.3/18.1)。
    #: 要素は base_id(コピー枚数の区別は落とす。クラフト時にカードは手札から
    #: 出て捨て山に行かない)。重複禁止(4.1.4)は crafting.legal_crafts が強制。
    crafted_effects: Tuple[str, ...] = ()
    #: 「1ターン1回」系の継続効果カードの使用済み base_id(18.1)。stand-and-deliver
    #: / better-burrow-bank / tax-collector / command-warren / cobbler が対象。
    #: 自ターンの鳥歌 begin_phase でリセット(既存の潜入リセットと同じ場所)。
    effects_used: Tuple[str, ...] = ()
    items: Tuple[ItemKind, ...] = ()      # 作成済みアイテム
    soldiers_supply: int = 0              # サプライにある兵士コマ数
    #: 発動して手元に公開中の圧倒カードID(3.3.1/3.3.2)。None→非Noneの一方向。
    #: 非None の間は VP 凍結(mechanics.award_vp が no-op, 3.3.1)。
    dominance_card: Optional[str] = None


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
class EyrieState(FactionState):
    """鷲巣王朝の派閥ボード状態(第7章)。

    勅令(decree)は4列(募兵/移動/戦闘/建設, 7.5.2 の I〜IV 順)の
    カードIDタプル。忠臣カード(7.3.4)は山札に存在しない擬似ID
    ``LOYAL_VIZIER`` で表現する(動物種=鳥、捨て山に行かない)。
    """

    leader: Optional[str] = None            # 現在の君主(7.3.3 / 7.7.3)
    used_leaders: Tuple[str, ...] = ()      # 裏向きの君主(7.7.3)。全裏で新世代(7.7.3.I)
    #: 勅令4列(左から募兵→移動→戦闘→建設, 7.5.2)
    decree: Tuple[Tuple[str, ...], ...] = ((), (), (), ())
    # --- 昼光の勅令進行状態(ターンごとに decree からリセット) ---
    #: 現在ターンの未実行勅令カード(列ごと)。先頭の非空列が現在の列。
    decree_remaining: Tuple[Tuple[str, ...], ...] = ((), (), (), ())
    decree_started: bool = False            # 実行開始後はクラフト不可(7.5.1)
    #: 起動済みクラフトツール=止まり木の広場ID(1ターン1回, 4.1.1)
    used_roost_clearings: Tuple[int, ...] = ()
    built_roosts: int = 0                   # マップ上の止まり木数(0..7, 7.6.1)
    despot_awarded: bool = False            # 独裁者VPの1戦闘1回制御(7.8.4)


@dataclass(frozen=True)
class AllianceState(FactionState):
    """森林連合(ウッドランド・アライアンス)の派閥ボード状態(第8章)。

    支援者ボックス(8.2.3)は手札とは別枠の「第2の手札」。上限は
    マップ上の拠点タイル枚数が0か否かで切り替わる(8.2.3.I / 8.2.4)。
    拠点タイルの動物種は配置広場の suit と常に一致するため、``bases_placed``
    には動物種文字列("fox"等)だけを保持する。未配置拠点=3種との差集合。
    """

    #: 支援者ボックスのカードID(8.2.3。手札とは別、動物種のみ意味を持つ)
    supporters: Tuple[str, ...] = ()
    #: マップ上の支持トークン数(0..10)。支持エリアトラックのインデックスに使う
    placed_sympathy: int = 0
    #: マップに配置済み拠点の動物種("fox"/"rabbit"/"mouse")。空=全拠点未配置
    bases_placed: Tuple[str, ...] = ()
    #: 指揮官ボックスの兵士数(8.6.1。夕闇の作戦行動回数の上限)
    officers: int = 0
    #: 当ターンに実行済みの作戦行動回数(8.6.1。夕闇開始でリセット)
    ops_used: int = 0
    #: 作戦行動を終えて手札調整(8.6.2)まで済ませたか(夕闇開始でリセット)
    ops_done: bool = False
    #: 起動済みクラフトツール=支持トークンの広場ID(1ターン1回, 4.1.1)
    used_sympathy_clearings: Tuple[int, ...] = ()


@dataclass(frozen=True)
class ItemTile:
    """放浪部族のアイテムタイル1枚(9.2.5)。

    3ゾーン + 表裏でモデル化する:
    - ``damaged=True`` → 損傷アイテムボックス
    - ``on_track=True`` → 配置枠(T/X/B のみ・表向き時)
    - それ以外 → かばんエリア
    ``exhausted`` は裏向き(使用済み)。M/S/C/F/H は ``on_track`` を持たない
    (常に False)。
    """

    kind: str                 # ItemKind の値("boots"等)
    exhausted: bool = False   # 裏向き(使用済み)
    damaged: bool = False     # 損傷アイテムボックスにある
    on_track: bool = True     # T/X/B が配置枠にある(表向き時のみ)


@dataclass(frozen=True)
class VagabondState(FactionState):
    """放浪部族の派閥ボード状態(第9章)。

    放浪者コマの位置は ``pawn_clearing`` か ``pawn_forest`` のどちらか一方
    (排他, 9.2.2)。アイテムは :class:`ItemTile` の列で保持する(fs.items は
    未使用)。派閥関係(9.2.9)はトラック位置(0=無関心〜3=同盟, -1=敵対)を
    他派閥ごとに保持する。
    """

    character: Optional[str] = None          # "thief"/"tinker"/"ranger"(9.3.1)
    pawn_clearing: Optional[int] = None       # 広場 or 樹林のどちらか一方(排他)
    pawn_forest: Optional[int] = None
    items: Tuple[ItemTile, ...] = ()          # ← FactionState.items を上書き(ItemTile 列)
    #: 派閥関係(9.2.9): 0=無関心,1,2,3=同盟 / -1=敵対。他派閥全員分
    relationships: Tuple[Tuple[FactionId, int], ...] = ()
    #: 同一ターン中の派閥ごとの援助回数(9.2.9.I.a。ターン開始でリセット)
    aids_this_turn: Tuple[Tuple[FactionId, int], ...] = ()
    quest_deck: Tuple[str, ...] = ()          # 非公開の山(シャッフル済み)
    quests_open: Tuple[str, ...] = ()         # 公開3枚
    quests_done: Tuple[str, ...] = ()         # 解決済み(動物種カウントは quests.json 参照)
    #: 遺跡の隠匿アイテム(9.3.4)。(広場ID, ItemKind値)。探索で除去
    ruin_items: Tuple[Tuple[int, str], ...] = ()
    #: 鳥歌の潜入(9.4.2)を今ターン使ったか(begin_phase でリセット)
    slip_used: bool = False
    #: 戦闘中に自アイテム損傷で満たしたヒット数(9.2.9.II.d 用。宣言時リセット)
    damage_hits_this_battle: int = 0
    #: 共闘軍の相手派閥(9.2.8)。None→非Noneの一方向。非None の間は VP 凍結。
    coalition_with: Optional[FactionId] = None


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
    #: コスト消費でゲーム盤の横に置かれた圧倒カード(3.3.3)。捨て山ではない。
    #: 3.3.4 の回収対象。カード保存則(validate)の勘定に含める。
    dominance_aside: Tuple[str, ...] = ()
    supply_items: Tuple[Tuple[ItemKind, int], ...] = ()  # サプライのアイテム残数
    pending: Tuple = ()                        # 保留デシジョンスタック(3.2)
    winner: Optional[FactionId] = None
    finished: bool = False

    # --- 参照 ---
    def current_faction(self) -> FactionId:
        return self.factions[self.turn_index]

    @property
    def winners(self) -> Tuple[FactionId, ...]:
        """勝者の集合(3.1 / 9.2.8)。

        主勝者 ``winner`` に加え、共闘軍(9.2.8)を結成した放浪部族の共闘相手が
        主勝者なら放浪部族も勝者に含める。未確定なら空タプル。
        """
        if self.winner is None:
            return ()
        result = [self.winner]
        if FactionId.VAGABOND in self.factions:
            vs = self.vagabond()
            if (vs.coalition_with is not None
                    and vs.coalition_with == self.winner
                    and FactionId.VAGABOND not in result):
                result.append(FactionId.VAGABOND)
        return tuple(result)

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

    def eyrie(self) -> EyrieState:
        s = self.fs(FactionId.EYRIE)
        assert isinstance(s, EyrieState)
        return s

    def alliance(self) -> "AllianceState":
        s = self.fs(FactionId.ALLIANCE)
        assert isinstance(s, AllianceState)
        return s

    def vagabond(self) -> "VagabondState":
        s = self.fs(FactionId.VAGABOND)
        assert isinstance(s, VagabondState)
        return s

    def clearing(self, cid: int) -> ClearingState:
        return self.clearings[cid]

    # --- 支配(2.5) ---
    def controller(self, cid: int) -> Optional[FactionId]:
        """広場の支配プレイヤー。兵士コマ+建物タイルの合計最大, 同点は None。

        放浪者コマ・トークンは不算入(2.5, 9.2.2)。
        森の王者(7.2.2): 鷲巣王朝が同点1位に含まれる場合、その広場に
        鷲巣の配置物(兵士コマ/建物タイル)があれば鷲巣が支配する。
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
        # 森の王者(7.2.2): counts に載っている=配置物が1個以上ある
        if FactionId.EYRIE in leaders and counts.get(FactionId.EYRIE, 0) > 0:
            return FactionId.EYRIE
        return None

    def controls(self, faction: FactionId, cid: int) -> bool:
        return self.controller(cid) == faction

    # --- 城砦の配置禁止(6.2.2) ---
    def placement_blocked(self, faction: FactionId, cid: int) -> bool:
        """猫以外は城砦トークンのある広場に配置物を配置できない(6.2.2)。

        配置(placement)のみが禁止で、移動(4.2)は合法。候補生成側で
        「配置」の判定にのみ用いること(共通ルール0節 Q4)。
        """
        if faction == FactionId.MARQUISE:
            return False
        return self.clearing(cid).has_token(FactionId.MARQUISE, T_KEEP)

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

    # --- デバッグ用不変量チェック(6 テスト戦略 / 9.4) ---
    def validate(self) -> None:
        # --- 既存: 枠数・兵士非負・VP非負 ---
        for cs in self.clearings:
            cl = self.map.clearing(cs.cid)
            assert cs.occupied_slots() <= cl.slots, (
                "clearing %d over slots: %d/%d" % (cs.cid, cs.occupied_slots(), cl.slots))
            assert cs.total_soldiers() >= 0
        for fs in self.faction_states:
            assert fs.vp >= 0, "negative VP for %s" % fs.faction

        # --- 9.4.1: 派閥ごとの兵士総数(サプライ+盤上)≤ 上限 ---
        for fs in self.faction_states:
            limit = MAX_SOLDIERS.get(fs.faction)
            if limit is None:
                continue  # DUMMY/VAGABOND 等は未対応(チェック対象外)
            on_board = sum(cs.soldier_count(fs.faction) for cs in self.clearings)
            total = fs.soldiers_supply + on_board
            assert total <= limit, (
                "soldier total over limit for %s: %d/%d (supply=%d board=%d)"
                % (fs.faction, total, limit, fs.soldiers_supply, on_board))

        # --- 9.4.2: 建物種ごとの盤上数 ≤ 印刷数(boards.json 由来) ---
        building_limits: Dict[Tuple[FactionId, str], int] = {}
        if FactionId.MARQUISE in self.factions:
            bvp = self.board_defs["marquise"]["building_vp"]
            for kind in MARQUISE_BUILDINGS:
                building_limits[(FactionId.MARQUISE, kind)] = len(bvp[kind])
        if FactionId.EYRIE in self.factions:
            building_limits[(FactionId.EYRIE, B_ROOST)] = len(
                self.board_defs["eyrie"]["roost_vp"])
        if FactionId.ALLIANCE in self.factions:
            building_limits[(FactionId.ALLIANCE, B_BASE)] = len(CLEARING_SUITS)
        building_counts: Dict[Tuple[FactionId, str], int] = {}
        for cs in self.clearings:
            for p in cs.buildings:
                key = (p.faction, p.kind)
                building_counts[key] = building_counts.get(key, 0) + 1
        for key, lim in building_limits.items():
            got = building_counts.get(key, 0)
            assert got <= lim, (
                "building %s over limit: %d/%d" % (key, got, lim))

        # --- 9.4.3: トークン上限(木材≤8・共感≤10・城砦≤1) ---
        if FactionId.MARQUISE in self.factions:
            wood_board = sum(cs.wood_count(FactionId.MARQUISE) for cs in self.clearings)
            wood_supply = self.marquise().wood_supply
            assert wood_board + wood_supply <= MAX_WOOD, (
                "wood over limit: board=%d + supply=%d > %d"
                % (wood_board, wood_supply, MAX_WOOD))
            keep_board = sum(
                1 for cs in self.clearings for p in cs.tokens
                if p.faction == FactionId.MARQUISE and p.kind == T_KEEP)
            assert keep_board <= MAX_KEEP, (
                "keep tokens over limit: %d/%d" % (keep_board, MAX_KEEP))
        if FactionId.ALLIANCE in self.factions:
            symp_board = sum(
                1 for cs in self.clearings for p in cs.tokens
                if p.faction == FactionId.ALLIANCE and p.kind == T_SYMPATHY)
            assert symp_board <= MAX_SYMPATHY, (
                "sympathy tokens over limit: %d/%d" % (symp_board, MAX_SYMPATHY))

        # --- 9.4.4: カード保存則 ---
        # 全カード枚数(コピー込み)。2人戦は圧倒カードを山札から除く(5.1.3)ため、
        # それらは盤面のどこにも属さない → 期待枚数から差し引く。
        total_cards = sum(d.copies for d in self.cards.defs)
        dominance = sum(d.copies for d in self.cards.defs if d.is_dominance)
        expected = total_cards - (dominance if len(self.factions) == 2 else 0)
        count = len(self.deck) + len(self.discard)
        # 圧倒カードの2ゾーン(3.3.2 公開中 / 3.3.3 盤脇)を勘定に加える(14.1)
        count += len(self.dominance_aside)
        for fs in self.faction_states:
            count += len(fs.hand) + len(fs.crafted_effects)
            if fs.dominance_card is not None:
                count += 1
        if FactionId.ALLIANCE in self.factions:
            count += len(self.alliance().supporters)
        if FactionId.EYRIE in self.factions:
            # 忠臣(LOYAL_VIZIER)は山札に存在しない擬似ID → 54枚から除外する。
            for col in self.eyrie().decree:
                count += sum(1 for c in col if c != LOYAL_VIZIER)
        assert count == expected, (
            "card conservation broken: counted %d, expected %d" % (count, expected))

        # --- 9.4.5: pending の actor が state.factions に含まれる ---
        for dec in self.pending:
            assert dec.actor in self.factions, (
                "pending actor %s not in factions %s" % (dec.actor, self.factions))

        # --- 放浪部族(第9章)の不変量 ---
        # カード保存則(9.4.4)は放浪部族に影響しない: クエストは 54 枚とは別山
        # (quest_deck/quests_open/quests_done)であり、援助・盗み・日常業務・
        # クエスト報酬ドローはいずれも 54 枚のカードを他ゾーン(手札/捨て札/山札)
        # 間で移すだけ。アイテムタイル(ItemTile)はカードではない。よって上の
        # カード保存則で放浪部族の hand も自動的に数えられており追加補正は不要。
        if FactionId.VAGABOND in self.factions:
            vs = self.vagabond()
            # 放浪者コマは広場か樹林のどちらか一方のみ(9.2.2。セットアップ中は両 None)
            assert not (vs.pawn_clearing is not None and vs.pawn_forest is not None), (
                "vagabond pawn in both clearing and forest")
