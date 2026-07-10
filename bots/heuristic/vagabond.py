"""放浪部族の派閥固有評価項(DESIGN.md 11.6)。

放浪部族は兵士・建物を持たないため共通項(11.3)は実質 vp と手札のみ。ここでは
「次以降のターンの稼ぐ力」として、アイテム経済(かばん/配置枠/損傷回避)・
派閥関係(同盟トラックへの接近)・位置(広場滞在・遺跡探索の準備・接触機会)
を加点する。VP 獲得イベント自体は 1-ply の apply 結果に直接現れるため対象外。
"""
from __future__ import annotations

from engine.state import GameState
from engine.types import FactionId, ItemKind

SWORD = ItemKind.SWORD.value
TORCH = ItemKind.TORCH.value
TEA = ItemKind.TEA.value
COINS = ItemKind.COINS.value
BAG = ItemKind.BAG.value

#: 配置枠(on_track)の種類別加点(9.2.5)。回復・ドロー・上限のエンジン強化源。
_TRACK_BONUS = {TEA: 3, COINS: 3, BAG: 2}


def faction_term(state: GameState) -> float:
    """放浪部族固有の加点(DESIGN.md 11.6)。"""
    vb = state.vagabond()
    score = 0.0

    # --- アイテム経済 ---
    for t in vb.items:
        # 非損傷1枚につき+2、表向き(exhausted=False)なら+2(独立加算。
        # 表向き非損傷=+4。無駄なコスト消費・損傷選択への誘導)
        if not t.damaged:
            score += 2
        if not t.exhausted:
            score += 2
        # 非損傷Sにつき追加+2(出目上限9.2.6・無防備回避9.2.4の源泉)
        if t.kind == SWORD and not t.damaged:
            score += 2
        # 配置枠の表向きT/X/B(engine の不変条件上 on_track は常に表向き非損傷)
        if t.on_track:
            score += _TRACK_BONUS.get(t.kind, 0)

    # --- 派閥関係(9.2.9) ---
    # トラック位置 rel(0..3)の他派閥合計*3。敵対(-1)は0として加算=ペナルティなし。
    score += 3 * sum(max(0, rel) for _, rel in vb.relationships)

    # --- 位置(潜入9.4.2・移動9.5.1の行き先への信号) ---
    if vb.pawn_clearing is not None:
        # 広場にいる(樹林は夜の休息以外は何もできない)
        score += 3
        cs = state.clearing(vb.pawn_clearing)
        # 遺跡があり非損傷Fを持つ(探索9.5.3の直前状態)
        if cs.ruin and any(t.kind == TORCH and not t.damaged for t in vb.items):
            score += 2
        # 配置物を持つ他派閥数(援助・盗み・戦闘の機会)
        others = sum(
            1 for f in state.factions
            if f != FactionId.VAGABOND
            and (cs.soldier_count(f) > 0 or cs.buildings_of(f) or cs.tokens_of(f))
        )
        score += others * 2

    return score
