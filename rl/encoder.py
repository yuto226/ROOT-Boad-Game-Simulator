"""観測エンコーダ(DESIGN.md 12.3)。

:class:`ObservationSpec` が ``factions`` からレイアウトを決定し、
:meth:`ObservationSpec.encode` が ``np.float32[obs_dim]`` を返す。

方針(6c 初期):
- **完全情報**: 相手の手札もエンコードする。山札の並び・遺跡アイテム内訳は
  入れない(枚数のみ)。
- perspective はブロックの並べ替えではなく **onehot** で示す(レイアウト固定。
  self-play で両側を同一ネットにするため)。
- 全特徴を概ね [0,1] に正規化する。``describe() -> {ブロック名: slice}`` を提供。
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from engine.state import (
    AllianceState,
    EyrieState,
    GameState,
    MarquiseState,
    VagabondState,
)
from engine.types import (
    CLEARING_SUITS,
    EYRIE_LEADERS,
    FactionId,
    ItemKind,
    LOYAL_VIZIER,
    Phase,
    Suit,
)

from .catalog import CARD_BASE_IDS, DOMINANCE_BASE_IDS, SUITS

# --- 固定次元の静的定数 ---
_N_CLEARINGS = 12
_N_FORESTS = 7
_N_CARD_BASE = len(CARD_BASE_IDS)          # 42
_ITEM_KINDS: Tuple[ItemKind, ...] = tuple(ItemKind)  # 8
_CHARACTERS: Tuple[str, ...] = ("thief", "tinker", "ranger")
_PHASES: Tuple[Phase, ...] = (Phase.BIRDSONG, Phase.DAYLIGHT, Phase.EVENING)

#: pending 先頭 Decision 型の onehot 順(actions.py の Decision 全型)
_DECISION_TYPES: Tuple[str, ...] = (
    "SetupKeepDecision", "AmbushDefenderDecision", "AmbushAttackerDecision",
    "AllocateHitsDecision", "DiscardDecision", "EyrieSetupCornerDecision",
    "EyrieLeaderDecision", "EyrieDecreeDecision", "EyrieRoostDecision",
    "OutrageDecision", "SupportersLimitDecision", "VagabondSetupCharacterDecision",
    "VagabondSetupForestDecision", "RefreshDecision", "ItemDamageDecision",
    "ItemLimitDecision",
)

# 正規化スケール(概ね [0,1] に収める分母)。上界超過は describe 時に clip する。
_VP_SCALE = 30.0
_TURN_SCALE = 300.0
_DECK_SCALE = 54.0
_SOLDIER_SCALE = 25.0
_SLOT_SCALE = 3.0
_BUILDING_SCALE = 6.0
_TOKEN_SCALE = 10.0
_HAND_SCALE = 5.0
_HITS_SCALE = 10.0


def _faction_specific_size(fid: FactionId, n_fac: int) -> int:
    """派閥固有ブロックの次元(fid で確定)。"""
    if fid == FactionId.MARQUISE:
        return 8
    if fid == FactionId.EYRIE:
        return 25
    if fid == FactionId.ALLIANCE:
        return 11
    if fid == FactionId.VAGABOND:
        # kind×4(32)+relationships(n_fac)+coalition_with onehot(n_fac)+quests(2)+pawn(19)+character(3)
        return 32 + n_fac + n_fac + 2 + _N_FORESTS + _N_CLEARINGS + 3
    return 0  # DUMMY 等は共通部のみ


class ObservationSpec:
    """観測レイアウトを ``factions`` から確定する(12.3)。"""

    def __init__(self, factions: Tuple[FactionId, ...]) -> None:
        self.factions: Tuple[FactionId, ...] = tuple(factions)
        f = len(self.factions)
        # 各ブロックのサイズ(下の encode と同順)
        self._global_size = 3 + 1 + f + f + 2 + len(_DECISION_TYPES) + f + 2 + len(DOMINANCE_BASE_IDS)
        self._clearing_size = 3 + 1 + 2 + 3 * f + (f + 1)
        # ブロック境界を記録
        blocks: Dict[str, slice] = {}
        cur = 0
        blocks["global"] = slice(cur, cur + self._global_size)
        cur += self._global_size
        clearings_start = cur
        for c in range(_N_CLEARINGS):
            blocks["clearing_%d" % c] = slice(cur, cur + self._clearing_size)
            cur += self._clearing_size
        blocks["clearings"] = slice(clearings_start, cur)
        for fid in self.factions:
            # 共通(vp 1 + 手札 base_id カウント + soldiers_supply 1)+ 派閥固有
            size = 1 + _N_CARD_BASE + 1 + len(DOMINANCE_BASE_IDS) + _faction_specific_size(fid, f)
            blocks["faction_%s" % fid.value] = slice(cur, cur + size)
            cur += size
        self.blocks = blocks
        self.obs_dim = cur

    def describe(self) -> Dict[str, slice]:
        """{ブロック名: slice}(12.3)。"""
        return dict(self.blocks)

    # ------------------------------------------------------------
    def encode(self, state: GameState, perspective: FactionId) -> "np.ndarray":
        """状態を ``np.float32[obs_dim]`` に符号化する(12.3)。"""
        feats: List[float] = []
        factions = self.factions
        f = len(factions)

        def onehot(idx: int, size: int) -> None:
            row = [0.0] * size
            if 0 <= idx < size:
                row[idx] = 1.0
            feats.extend(row)

        def fac_index(fid) -> int:
            return factions.index(fid) if fid in factions else -1

        # ============ global ============
        onehot(_PHASES.index(state.phase), 3)
        feats.append(min(state.turn_count / _TURN_SCALE, 1.0))
        onehot(fac_index(state.current_faction()), f)
        onehot(fac_index(perspective), f)
        feats.append(min(len(state.deck) / _DECK_SCALE, 1.0))
        feats.append(min(len(state.discard) / _DECK_SCALE, 1.0))
        if state.pending:
            dec = state.pending[-1]
            dname = type(dec).__name__
            didx = _DECISION_TYPES.index(dname) if dname in _DECISION_TYPES else -1
            onehot(didx, len(_DECISION_TYPES))
            onehot(fac_index(dec.actor), f)
            feats.append(min(getattr(dec, "hits", 0) / _HITS_SCALE, 1.0))
            feats.append(min(getattr(dec, "remaining", 0) / _HITS_SCALE, 1.0))
        else:
            onehot(-1, len(_DECISION_TYPES))
            onehot(-1, f)
            feats.append(0.0)
            feats.append(0.0)

        # dominance_aside の4フラグ(圧倒4種が盤脇にあるか, 14.7)
        aside_bases = {state.cards.base_id(cid) for cid in state.dominance_aside}
        for b in DOMINANCE_BASE_IDS:
            feats.append(1.0 if b in aside_bases else 0.0)

        # ============ clearing×12 ============
        for cid in range(_N_CLEARINGS):
            cs = state.clearings[cid]
            cl = state.map.clearing(cid)
            # suit onehot(広場は fox/rabbit/mouse のいずれか)
            sidx = CLEARING_SUITS.index(cl.suit) if cl.suit in CLEARING_SUITS else -1
            onehot(sidx, 3)
            feats.append(1.0 if cl.ruin else 0.0)
            feats.append(min(cl.slots / _SLOT_SCALE, 1.0))
            feats.append(min(cs.occupied_slots() / _SLOT_SCALE, 1.0))
            for fid in factions:
                feats.append(min(cs.soldier_count(fid) / _SOLDIER_SCALE, 1.0))
                feats.append(min(len(cs.buildings_of(fid)) / _BUILDING_SCALE, 1.0))
                feats.append(min(len(cs.tokens_of(fid)) / _TOKEN_SCALE, 1.0))
            onehot(fac_index(state.controller(cid)), f + 1)  # 末尾=支配者なし

        # ============ faction×参加派閥 ============
        for fid in factions:
            fs = state.fs(fid)
            feats.append(min(fs.vp / _VP_SCALE, 1.0))
            # 手札の base_id 別カウント(完全情報)
            counts = {}
            for cid in fs.hand:
                b = state.cards.base_id(cid)
                counts[b] = counts.get(b, 0) + 1
            for b in CARD_BASE_IDS:
                feats.append(min(counts.get(b, 0) / _HAND_SCALE, 1.0))
            feats.append(min(fs.soldiers_supply / _SOLDIER_SCALE, 1.0))
            # 発動中の圧倒 suit onehot(4)(14.7)。fs.dominance_card は手札を離れた
            # インスタンスID(base_id 化しない。suit_of は instance/base どちらでも動く)。
            dom_suit = (state.cards.suit_of(fs.dominance_card)
                       if fs.dominance_card is not None else None)
            didx = SUITS.index(dom_suit) if dom_suit in SUITS else -1
            drow = [0.0] * len(SUITS)
            if 0 <= didx < len(SUITS):
                drow[didx] = 1.0
            feats.extend(drow)
            # --- 派閥固有 ---
            if isinstance(fs, MarquiseState):
                self._encode_marquise(feats, fs)
            elif isinstance(fs, EyrieState):
                self._encode_eyrie(feats, state, fs)
            elif isinstance(fs, AllianceState):
                self._encode_alliance(feats, state, fs)
            elif isinstance(fs, VagabondState):
                self._encode_vagabond(feats, state, fs, factions)
            # DUMMY 等は固有ブロックなし

        arr = np.asarray(feats, dtype=np.float32)
        assert arr.shape[0] == self.obs_dim, (
            "encode produced %d feats, spec obs_dim=%d" % (arr.shape[0], self.obs_dim))
        return arr

    # ---- 派閥固有ブロック ----
    @staticmethod
    def _encode_marquise(feats: List[float], ms: MarquiseState) -> None:
        feats.append(min(ms.wood_supply / 8.0, 1.0))
        feats.append(min(ms.built_sawmill / _BUILDING_SCALE, 1.0))
        feats.append(min(ms.built_workshop / _BUILDING_SCALE, 1.0))
        feats.append(min(ms.built_recruiter / _BUILDING_SCALE, 1.0))
        feats.append(1.0 if ms.workshop_used else 0.0)
        feats.append(min(ms.actions_left / _HITS_SCALE, 1.0))
        feats.append(1.0 if ms.recruited_this_turn else 0.0)
        feats.append(1.0 if ms.keep_corner is not None else 0.0)

    @staticmethod
    def _encode_eyrie(feats: List[float], state: GameState, es: EyrieState) -> None:
        # 勅令 column(4)×suit(4)カウント = 16
        for col in es.decree:
            per_suit = {s: 0 for s in SUITS}
            for cid in col:
                base = state.cards.base_id(cid)
                suit = Suit.BIRD if base == LOYAL_VIZIER else state.cards.suit_of(cid)
                per_suit[suit] = per_suit.get(suit, 0) + 1
            for s in SUITS:
                feats.append(min(per_suit[s] / _BUILDING_SCALE, 1.0))
        # 君主 onehot(4)
        lidx = EYRIE_LEADERS.index(es.leader) if es.leader in EYRIE_LEADERS else -1
        row = [0.0] * len(EYRIE_LEADERS)
        if 0 <= lidx < len(EYRIE_LEADERS):
            row[lidx] = 1.0
        feats.extend(row)
        # 忠臣が勅令に存在するか
        has_vizier = any(LOYAL_VIZIER in col for col in es.decree)
        feats.append(1.0 if has_vizier else 0.0)
        # 止まり木: 配置数/7・残/7
        feats.append(min(es.built_roosts / float(_N_FORESTS), 1.0))
        feats.append(min((_N_FORESTS - es.built_roosts) / float(_N_FORESTS), 1.0))
        feats.append(1.0 if es.decree_started else 0.0)
        feats.append(min(len(es.used_leaders) / float(len(EYRIE_LEADERS)), 1.0))

    @staticmethod
    def _encode_alliance(feats: List[float], state: GameState, als: AllianceState) -> None:
        # 支援者 suit 別カウント(4)
        per_suit = {s: 0 for s in SUITS}
        for cid in als.supporters:
            suit = state.cards.suit_of(cid)
            per_suit[suit] = per_suit.get(suit, 0) + 1
        for s in SUITS:
            feats.append(min(per_suit[s] / _TOKEN_SCALE, 1.0))
        feats.append(min(als.officers / _TOKEN_SCALE, 1.0))
        # 拠点(fox/rabbit/mouse)の設置有無 onehot 3
        for s in CLEARING_SUITS:
            feats.append(1.0 if s.value in als.bases_placed else 0.0)
        feats.append(min(als.placed_sympathy / _TOKEN_SCALE, 1.0))
        feats.append(min((10 - als.placed_sympathy) / _TOKEN_SCALE, 1.0))
        feats.append(min(als.ops_used / _TOKEN_SCALE, 1.0))

    @staticmethod
    def _encode_vagabond(feats: List[float], state: GameState, vs: VagabondState,
                         factions: Tuple[FactionId, ...]) -> None:
        # ItemTile kind×(総数/裏向き/損傷/枠)カウント = 32。総数がないと
        # 「かばん内の表向き・非損傷」タイル(3フラグ全て0)が不可視になる
        for kind in _ITEM_KINDS:
            n_all = sum(1 for t in vs.items if t.kind == kind.value)
            n_ex = sum(1 for t in vs.items if t.kind == kind.value and t.exhausted)
            n_dm = sum(1 for t in vs.items if t.kind == kind.value and t.damaged)
            n_ot = sum(1 for t in vs.items if t.kind == kind.value and t.on_track)
            feats.append(min(n_all / 4.0, 1.0))
            feats.append(min(n_ex / 2.0, 1.0))
            feats.append(min(n_dm / 2.0, 1.0))
            feats.append(min(n_ot / 2.0, 1.0))
        # 派閥関係(9.2.9): level -1..3 → (level+1)/4
        rel = {fac: lvl for fac, lvl in vs.relationships}
        for fid in factions:
            feats.append((rel.get(fid, 0) + 1) / 4.0)
        # 共闘相手 onehot(n_fac)(9.2.8, 14.7)
        coalition_idx = (factions.index(vs.coalition_with)
                         if vs.coalition_with in factions else -1)
        coalition_row = [0.0] * len(factions)
        if 0 <= coalition_idx < len(factions):
            coalition_row[coalition_idx] = 1.0
        feats.extend(coalition_row)
        # クエスト公開/解決
        feats.append(min(len(vs.quests_open) / 3.0, 1.0))
        feats.append(min(len(vs.quests_done) / 15.0, 1.0))
        # コマ位置 onehot(広場12 + 樹林7)
        pawn = [0.0] * (_N_CLEARINGS + _N_FORESTS)
        if vs.pawn_clearing is not None and 0 <= vs.pawn_clearing < _N_CLEARINGS:
            pawn[vs.pawn_clearing] = 1.0
        elif vs.pawn_forest is not None and 0 <= vs.pawn_forest < _N_FORESTS:
            pawn[_N_CLEARINGS + vs.pawn_forest] = 1.0
        feats.extend(pawn)
        # キャラ onehot(3)
        cidx = _CHARACTERS.index(vs.character) if vs.character in _CHARACTERS else -1
        crow = [0.0] * 3
        if 0 <= cidx < 3:
            crow[cidx] = 1.0
        feats.extend(crow)


def encode(state: GameState, spec: ObservationSpec, perspective: FactionId):
    """モジュールレベルの薄いラッパ(spec.encode に委譲)。"""
    return spec.encode(state, perspective)
