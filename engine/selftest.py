"""戦闘 pending スタック機構と鷲巣王朝の内乱(7.7)の自己テスト。

使い方: ``python3 -m engine.selftest``

1. 猫野侯国 + 「何もしないスタブ派閥」(DUMMY)の2派閥手動シナリオで、
   戦闘1回(4.3 の4ステップ)が保留デシジョンスタック(3.2)経由で
   解決できることを確認する。奇襲(4.3.1)パスも検証する。
2. 猫+鷲巣の2派閥シナリオで、実行不能な勅令による内乱(7.7)の
   VP喪失(クランプ含む)・忠臣残存・君主交代・夕闇直行を検証する。
"""
from __future__ import annotations

import dataclasses
import random
import sys

from .actions import (
    ActivateDominance,
    AllianceDiscardSupporter,
    AllianceRevolt,
    AllocateHit,
    AllocateHitsDecision,
    AmbushChoice,
    AmbushDefenderDecision,
    DeclareBattle,
    DiscardCard,
    DiscardDecision,
    EndPhase,
    EyrieChooseCorner,
    EyrieChooseLeader,
    EyrieTurmoil,
    ItemDamageDecision,
    ItemLimitDecision,
    MarquiseMarch,
    OutrageDecision,
    OutragePay,
    SetupChooseKeep,
    SupportersLimitDecision,
    TakeDominance,
    VagabondAid,
    VagabondBattle,
    VagabondChooseCharacter,
    VagabondChooseForest,
    VagabondCoalition,
    VagabondExplore,
    VagabondQuest,
    VagabondStrike,
)
from .apply import apply
from .battle import remove_piece
from .game import check_dominance_victory, new_game
from .legal import legal_actions
from .mechanics import award_vp, to_discard
from .state import GameState, ItemTile
from .types import (
    B_BASE,
    B_ROOST,
    B_SAWMILL,
    Corner,
    FactionId,
    ItemKind,
    LOYAL_VIZIER,
    Phase,
    Piece,
    Suit,
    T_SYMPATHY,
)

M = FactionId.MARQUISE
D = FactionId.DUMMY
E = FactionId.EYRIE
A = FactionId.ALLIANCE
V = FactionId.VAGABOND


def _setup_two_faction(rng: random.Random) -> GameState:
    """猫(城砦NW)+ダミーの2派閥状態を作り、広場1に対峙させる。"""
    state = new_game((M, D), rng)
    # セットアップ Decision(城砦の隅)を解決
    assert state.pending, "setup decision expected"
    state = apply(state, SetupChooseKeep(player=M, corner="NW"), rng)
    assert not state.pending

    # 手動シナリオ: 広場1に猫3・ダミー2+ダミー建物1を配置
    cs = state.clearing(1)
    cs = cs.with_soldiers(M, 3).with_soldiers(D, 2)
    cs = cs.add_building(Piece(D, B_SAWMILL))
    state = state.with_clearing(cs)
    return state


def test_battle_via_pending() -> None:
    """通常戦闘: DeclareBattle → ロール → AllocateHitsDecision 解決。"""
    rng = random.Random(42)
    state = _setup_two_faction(rng)
    # ダミーの手札から奇襲カードを除き、通常ロールに固定
    dfs = state.fs(D)
    hand = tuple(c for c in dfs.hand if not state.cards.get(c).is_ambush)
    state = state.with_faction_state(dataclasses.replace(dfs, hand=hand))

    before_m = state.clearing(1).soldier_count(M)
    before_d = state.clearing(1).soldier_count(D)

    state = apply(state, DeclareBattle(player=M, clearing=1, defender=D), rng)

    # ヒットが出ていれば AllocateHitsDecision が積まれている
    steps = 0
    while state.pending:
        steps += 1
        assert steps < 50, "pending loop did not terminate"
        dec = state.pending[-1]
        assert isinstance(dec, AllocateHitsDecision), "unexpected decision %r" % dec
        acts = legal_actions(state)
        assert acts, "no options for allocation"
        assert all(isinstance(a, AllocateHit) for a in acts)
        # 兵士が残る間は兵士のみが選択肢(4.3.4)
        if state.clearing(1).soldier_count(dec.victim) > 0:
            assert acts == [AllocateHit(player=dec.actor, target=("soldier",))]
        state = apply(state, acts[0], rng)

    after_m = state.clearing(1).soldier_count(M)
    after_d = state.clearing(1).soldier_count(D)
    removed = (before_m - after_m) + (before_d - after_d) + (
        1 - len(state.clearing(1).buildings_of(D)))
    assert removed >= 0
    # ダイスは 1..6 なので何かしらのヒットがほぼ必ず出るが、0 でも機構は成立
    print("  battle resolved: M %d->%d, D %d->%d, D buildings=%d, M vp=%d (steps=%d)"
          % (before_m, after_m, before_d, after_d,
             len(state.clearing(1).buildings_of(D)), state.fs(M).vp, steps))


def test_ambush_via_pending() -> None:
    """奇襲パス: 防御側に奇襲カードを持たせ AmbushDefenderDecision を解決。"""
    rng = random.Random(7)
    state = _setup_two_faction(rng)

    # 広場1(mouse)一致の奇襲カードをダミーの手札に強制注入
    ambush_id = None
    suit = state.map.clearing(1).suit
    for d in state.cards.defs:
        if d.is_ambush and d.suit == suit:
            ambush_id = d.id
            break
    assert ambush_id is not None, "no ambush card def found"
    dfs = state.fs(D)
    state = state.with_faction_state(dataclasses.replace(dfs, hand=dfs.hand + (ambush_id,)))
    # 攻撃側(猫)の手札から奇襲を除き、妨害選択肢を消す
    mfs = state.fs(M)
    state = state.with_faction_state(dataclasses.replace(
        mfs, hand=tuple(c for c in mfs.hand if not state.cards.get(c).is_ambush)))

    state = apply(state, DeclareBattle(player=M, clearing=1, defender=D), rng)
    assert state.pending and isinstance(state.pending[-1], AmbushDefenderDecision)

    acts = legal_actions(state)
    ambush_acts = [a for a in acts if isinstance(a, AmbushChoice) and a.card_id]
    assert ambush_acts, "ambush option missing"
    before_m = state.clearing(1).soldier_count(M)
    state = apply(state, ambush_acts[0], rng)

    # 奇襲2ヒットは兵士へ自動適用(4.3.1.II)済み → 残ヒットの割り振りを解決
    assert state.clearing(1).soldier_count(M) == before_m - 2, "ambush must deal 2 hits"
    steps = 0
    while state.pending:
        steps += 1
        assert steps < 50
        acts = legal_actions(state)
        state = apply(state, acts[0], rng)
    print("  ambush resolved: M soldiers %d->%d" % (before_m, state.clearing(1).soldier_count(M)))


# ---------------- 鷲巣王朝: 内乱(7.7) ----------------
def _setup_eyrie_pre_turmoil(rng: random.Random, used_leaders=()) -> GameState:
    """猫(城砦NW)+鷲巣(隅SE, 君主カリスマ)を作り、内乱直前まで進める。

    勅令の募兵列に鳥カード+キツネカードを追加した上で、マップ上の
    止まり木を全撤去して募兵(7.5.2.I)を実行不能にする。
    """
    state = new_game((M, E), rng)
    state = apply(state, SetupChooseKeep(player=M, corner="NW"), rng)

    # 7.3.2: 城砦が隅NWにあるので、鷲巣の隅は対角SEが強制される
    acts = legal_actions(state)
    assert acts == [EyrieChooseCorner(player=E, corner="SE")], (
        "対角の隅が強制されるはず(7.3.2): %r" % acts)
    state = apply(state, acts[0], rng)

    # 7.3.3: 君主4枚から選択 → カリスマ(忠臣は募兵・戦闘列, 7.8.2)
    acts = legal_actions(state)
    assert len(acts) == 4 and all(isinstance(a, EyrieChooseLeader) for a in acts)
    state = apply(state, EyrieChooseLeader(player=E, leader="charismatic"), rng)
    assert not state.pending
    es = state.fs(E)
    assert es.decree == ((LOYAL_VIZIER,), (), (LOYAL_VIZIER,), ())

    # 勅令に鳥1枚+キツネ1枚を注入(鳥計3枚: 忠臣2+鳥1)
    bird_card = fox_card = None
    for d in state.cards.defs:
        if d.is_dominance:
            continue  # 2人戦の山札に存在しないカードは避ける(5.1.3)
        if bird_card is None and d.suit == Suit.BIRD:
            bird_card = d.id
        if fox_card is None and d.suit == Suit.FOX:
            fox_card = d.id
    assert bird_card and fox_card
    decree = ((LOYAL_VIZIER, bird_card, fox_card), (), (LOYAL_VIZIER,), ())

    # マップ上の止まり木を全撤去 → 募兵列(最左)が実行不能
    corner_cid = state.map.corner_clearing(Corner.SE)
    state = state.with_clearing(
        state.clearing(corner_cid).remove_building(Piece(E, B_ROOST)))

    es = state.fs(E)
    es = dataclasses.replace(
        es, vp=1, hand=(), decree=decree, decree_remaining=decree,
        decree_started=False, built_roosts=0, used_leaders=tuple(used_leaders))
    state = state.with_faction_state(es)
    # 鷲巣の昼光フェイズにする
    return state.replace(turn_index=state.factions.index(E), phase=Phase.DAYLIGHT)


def test_eyrie_turmoil() -> None:
    """内乱: VP喪失(0にクランプ)・追放・忠臣残存・君主交代・夕闇直行。"""
    rng = random.Random(3)
    state = _setup_eyrie_pre_turmoil(rng)
    bird_card = state.fs(E).decree[0][1]
    fox_card = state.fs(E).decree[0][2]

    # 実行不能な勅令 → 合法手は内乱のみ(7.5.2)
    acts = legal_actions(state)
    assert acts == [EyrieTurmoil(player=E)], "内乱が強制されるはず: %r" % acts
    state = apply(state, acts[0], rng)

    es = state.fs(E)
    # 7.7.1 恥辱: VP1 - 鳥3枚(忠臣2+鳥1) → 0未満にはしない
    assert es.vp == 0, "VP must clamp at 0, got %d" % es.vp
    # 7.7.2 追放: 忠臣以外は捨て山へ、忠臣は捨て山に行かない
    assert bird_card in state.discard and fox_card in state.discard
    assert LOYAL_VIZIER not in state.discard
    # 7.7.3 失脚: カリスマは裏向きへ
    assert es.leader is None and es.used_leaders == ("charismatic",)

    # 君主交代 Decision: 表向きの3枚から選択
    acts = legal_actions(state)
    assert sorted(a.leader for a in acts) == ["builder", "commander", "despot"]
    state = apply(state, EyrieChooseLeader(player=E, leader="despot"), rng)

    es = state.fs(E)
    # 忠臣2枚が新君主の指定列(独裁者=移動・建設, 7.8.4)へ
    assert es.decree == ((), (LOYAL_VIZIER,), (), (LOYAL_VIZIER,))
    assert es.leader == "despot"
    # 7.7.4 休止: 昼光を即終了して夕闇へ(VP 0枚=0, ドロー1+0)
    assert state.phase == Phase.EVENING
    assert es.vp == 0
    assert len(es.hand) == 1, "evening draw of 1 expected, hand=%r" % (es.hand,)
    assert not state.pending
    assert legal_actions(state) == [EndPhase(player=E)]
    print("  turmoil resolved: vp=%d leader=%s phase=%s hand=%d"
          % (es.vp, es.leader, state.phase.name, len(es.hand)))


def test_eyrie_turmoil_new_generation() -> None:
    """新世代(7.7.3.I): 全君主が裏なら全て表に返してから選択。"""
    rng = random.Random(11)
    state = _setup_eyrie_pre_turmoil(
        rng, used_leaders=("builder", "commander", "despot"))
    state = apply(state, EyrieTurmoil(player=E), rng)
    es = state.fs(E)
    assert es.used_leaders == (), "all leaders must flip face-up (7.7.3.I)"
    acts = legal_actions(state)
    assert sorted(a.leader for a in acts) == [
        "builder", "charismatic", "commander", "despot"]
    print("  new generation: %d leaders selectable" % len(acts))


# ---------------- 森林連合(第8章) ----------------
class ScriptedRng:
    """randint を固定列で返すテスト用スタブ(ゲリラ戦のダイス固定)。"""

    def __init__(self, rolls):
        self.rolls = list(rolls)

    def randint(self, a, b):
        return self.rolls.pop(0)

    def shuffle(self, seq):
        pass

    def choice(self, seq):
        return seq[0]


def _clear(state: GameState, cid: int) -> GameState:
    cs = dataclasses.replace(state.clearing(cid), soldiers=(), buildings=(), tokens=())
    return state.with_clearing(cs)


def _clearings_of_suit(state: GameState, suit: Suit):
    return [cs.cid for cs in state.clearings if state.map.clearing(cs.cid).suit == suit]


def _cards_of_suit(state: GameState, suit: Suit, n: int):
    out = []
    for d in state.cards.defs:
        if d.is_dominance:
            continue
        if d.suit == suit:
            out.append(d.id)
        if len(out) >= n:
            break
    assert len(out) >= n, "need %d cards of suit %s" % (n, suit)
    return out


def _setup_marquise_alliance(rng: random.Random) -> GameState:
    """猫(城砦NW)+連合の2派閥。セットアップ(支援者3枚含む)を解決した状態。"""
    state = new_game((M, A), rng)
    state = apply(state, SetupChooseKeep(player=M, corner="NW"), rng)
    assert not state.pending
    assert len(state.alliance().supporters) == 3, "8.3.4: 支援者3枚"
    return state


def _set_alliance(state: GameState, **kw) -> GameState:
    return state.with_faction_state(dataclasses.replace(state.alliance(), **kw))


def test_outrage_pay_from_hand() -> None:
    """蜂起(8.2.6): 猫が支持広場へ行軍 → 一致カードで支払い、支援者+1。"""
    rng = random.Random(1)
    state = _setup_marquise_alliance(rng)
    # 隣接する2広場を選び、dst に支持トークンを置く
    src = 0
    dst = state.map.clearing(src).adjacent[0]
    state = _clear(state, src)
    state = _clear(state, dst)
    dst_suit = state.map.clearing(dst).suit
    state = state.with_clearing(state.clearing(dst).add_token(Piece(A, T_SYMPATHY)))
    state = _set_alliance(state, placed_sympathy=1, supporters=())
    # 猫: src に兵士2、手札に dst 一致カード1枚
    state = state.with_clearing(state.clearing(src).add_soldiers(M, 2))
    match_card = _cards_of_suit(state, dst_suit, 1)[0]
    state = state.with_faction_state(dataclasses.replace(state.fs(M), hand=(match_card,)))

    state = apply(state, MarquiseMarch(player=M, src=src, dst=dst, count=1), rng)
    assert state.pending and isinstance(state.pending[-1], OutrageDecision)
    assert state.pending[-1].actor == M and state.pending[-1].clearing == dst

    acts = legal_actions(state)
    pay = [a for a in acts if isinstance(a, OutragePay) and a.card_id == match_card]
    assert pay, "matching outrage payment expected: %r" % acts
    state = apply(state, pay[0], rng)
    assert not state.pending
    assert match_card not in state.fs(M).hand, "paid card leaves hand"
    assert state.alliance().supporters == (match_card,), "supporter box gains the card"
    print("  outrage(pay): supporters=%r" % (state.alliance().supporters,))


def test_outrage_auto_draw() -> None:
    """蜂起(8.2.6): 一致カードなし → 山札トップ1枚が自動で支援者ボックスへ。"""
    rng = random.Random(2)
    state = _setup_marquise_alliance(rng)
    src = 0
    dst = state.map.clearing(src).adjacent[0]
    state = _clear(state, src)
    state = _clear(state, dst)
    dst_suit = state.map.clearing(dst).suit
    state = state.with_clearing(state.clearing(dst).add_token(Piece(A, T_SYMPATHY)))
    state = _set_alliance(state, placed_sympathy=1, supporters=())
    state = state.with_clearing(state.clearing(src).add_soldiers(M, 2))
    # dst と一致しない、かつ鳥でない手札を1枚だけ持たせる
    other = next(s for s in (Suit.FOX, Suit.RABBIT, Suit.MOUSE) if s != dst_suit)
    state = state.with_faction_state(dataclasses.replace(
        state.fs(M), hand=(_cards_of_suit(state, other, 1)[0],)))
    deck_top = state.deck[-1]
    hand_before = state.fs(M).hand

    state = apply(state, MarquiseMarch(player=M, src=src, dst=dst, count=1), rng)
    # 一致カードがないので単一の自動補充 → ゲームループ相当で自動適用
    acts = legal_actions(state)
    assert acts == [OutragePay(player=M, card_id=None)], "auto-draw only: %r" % acts
    state = apply(state, acts[0], rng)
    assert not state.pending
    assert state.fs(M).hand == hand_before, "payer hand unchanged on auto-draw"
    assert state.alliance().supporters == (deck_top,), "deck top enters supporter box"
    print("  outrage(auto): supporters=%r" % (state.alliance().supporters,))


def test_revolt() -> None:
    """反乱(8.4.1): 敵除去+VP・拠点・兵士(一致支持広場数)・指揮官・支援者2枚消費。"""
    rng = random.Random(4)
    state = _setup_marquise_alliance(rng)
    fox_cids = _clearings_of_suit(state, Suit.FOX)
    c = next(cid for cid in fox_cids
             if state.map.clearing(cid).slots >= 1 and not state.clearing(cid).ruin)
    d = next(cid for cid in fox_cids if cid != c)
    state = _clear(state, c)
    state = _clear(state, d)
    # 支持広場 c(fox)+d(fox)。c に敵(猫)兵士2+建物1
    state = state.with_clearing(state.clearing(c).add_token(Piece(A, T_SYMPATHY))
                                .add_soldiers(M, 2).add_building(Piece(M, B_SAWMILL)))
    state = state.with_clearing(state.clearing(d).add_token(Piece(A, T_SYMPATHY)))
    supp = tuple(_cards_of_suit(state, Suit.FOX, 2))
    state = _set_alliance(state, placed_sympathy=2, supporters=supp,
                          bases_placed=(), officers=0, soldiers_supply=10)
    vp0 = state.alliance().vp

    state = apply(state, AllianceRevolt(player=A, clearing=c), rng)
    cs = state.clearing(c)
    als = state.alliance()
    assert cs.soldier_count(M) == 0 and not cs.buildings_of(M), "enemies removed"
    assert als.vp == vp0 + 1, "1VP for the removed building (soldiers give 0): %d" % als.vp
    assert any(p.faction == A and p.kind == B_BASE for p in cs.buildings), "base placed"
    assert als.bases_placed == ("fox",)
    assert cs.soldier_count(A) == 2, "soldiers = matching sympathetic clearings (c,d)"
    assert als.officers == 1, "one officer added"
    assert len(als.supporters) == 0, "2 supporters spent"
    assert als.soldiers_supply == 10 - 2 - 1, "supply spent on 2 soldiers + 1 officer"
    print("  revolt: vp=%d base=%r soldiers@c=%d officers=%d"
          % (als.vp, als.bases_placed, cs.soldier_count(A), als.officers))


def test_base_removed() -> None:
    """拠点除去(8.2.4): 一致支援者(鳥含む)全捨て・指揮官半減・全喪失で5枚調整。"""
    rng = random.Random(5)
    state = _setup_marquise_alliance(rng)
    c = _clearings_of_suit(state, Suit.FOX)[0]
    state = _clear(state, c)
    state = state.with_clearing(state.clearing(c).add_building(Piece(A, B_BASE)))
    fox = _cards_of_suit(state, Suit.FOX, 1)[0]
    bird = _cards_of_suit(state, Suit.BIRD, 1)[0]
    mouse = _cards_of_suit(state, Suit.MOUSE, 1)[0]
    supporters = (fox, bird) + (mouse,) * 6  # 一致=fox,bird / 非一致=mouse×6
    state = _set_alliance(state, bases_placed=("fox",), officers=3,
                          supporters=supporters, soldiers_supply=0)

    # 猫が拠点を除去(source=M → 1VP)。連鎖処理が走る
    state = remove_piece(state, c, A, ("building", B_BASE), M)
    als = state.alliance()
    assert als.bases_placed == (), "base species removed"
    assert fox not in als.supporters and bird not in als.supporters, "matching+bird discarded"
    assert als.officers == 1, "officers halved round-up (3 -> remove 2)"
    assert als.soldiers_supply == 2, "removed officers returned to supply"
    # 全拠点喪失かつ支援者6枚(>5) → 5枚調整デシジョン
    assert isinstance(state.pending[-1], SupportersLimitDecision)
    acts = legal_actions(state)
    assert acts and all(isinstance(a, AllianceDiscardSupporter) for a in acts)
    state = apply(state, acts[0], rng)
    assert not state.pending, "resolved once supporters == 5"
    assert len(state.alliance().supporters) == 5
    print("  base removed: bases=%r officers=%d supporters=%d"
          % (state.alliance().bases_placed, state.alliance().officers,
             len(state.alliance().supporters)))


def test_guerrilla_dice() -> None:
    """ゲリラ戦(8.2.2): 防御側=連合ならダイス大小の割当が反転する。"""
    rng = ScriptedRng([5, 2])  # hi=5, lo=2
    seed = random.Random(6)
    state = _setup_marquise_alliance(seed)
    c = 0
    state = _clear(state, c)
    state = state.with_clearing(state.clearing(c).add_soldiers(M, 5).add_soldiers(A, 5))
    # 奇襲を避けるため両者の手札を空に
    state = state.with_faction_state(dataclasses.replace(state.fs(M), hand=()))
    state = _set_alliance(state, hand=())

    state = apply(state, DeclareBattle(player=M, clearing=c, defender=A), rng)
    decs = {d.victim: d.hits for d in state.pending
            if isinstance(d, AllocateHitsDecision)}
    # ゲリラ: 防御側連合(victim=A)は攻撃側の小さい出目2、攻撃側(victim=M)は
    # 防御側連合の大きい出目5を受ける(通常なら A=5, M=2)。
    assert decs.get(A) == 2, "alliance defender takes small die (2): %r" % decs
    assert decs.get(M) == 5, "attacker takes alliance's large die (5): %r" % decs
    print("  guerrilla: hits victim A=%d, victim M=%d" % (decs[A], decs[M]))


# ---------------- 放浪部族(第9章, DESIGN.md 8.8) ----------------
def _tile(kind: str, exhausted: bool = False, damaged: bool = False,
          on_track: bool = False) -> ItemTile:
    """テスト用 ItemTile(既定=表向き・非損傷・かばんエリア)。"""
    return ItemTile(kind=kind, exhausted=exhausted, damaged=damaged, on_track=on_track)


def _set_vagabond(state: GameState, **kw) -> GameState:
    return state.with_faction_state(dataclasses.replace(state.vagabond(), **kw))


def _rel(state: GameState, faction: FactionId) -> int:
    from .factions.vagabond import _rel_get
    return _rel_get(state.vagabond(), faction)


def _setup_marquise_vagabond(rng: random.Random,
                             character: str = "thief") -> GameState:
    """猫(城砦NW)+放浪部族(樹林0)の2派閥。部族の昼光フェイズに設定する。"""
    state = new_game((M, V), rng)
    state = apply(state, SetupChooseKeep(player=M, corner="NW"), rng)
    state = apply(state, VagabondChooseCharacter(player=V, character=character), rng)
    state = apply(state, VagabondChooseForest(player=V, forest=0), rng)
    assert not state.pending
    return state.replace(turn_index=state.factions.index(V), phase=Phase.DAYLIGHT)


def test_vagabond_explore() -> None:
    """探索(9.5.3): 遺跡アイテム獲得+1VP、遺跡枯渇での除去(建物枠の解放)。"""
    rng = random.Random(21)
    state = _setup_marquise_vagabond(rng)
    cid, hidden_kind = state.vagabond().ruin_items[0]
    slots_before = state.clearing(cid).occupied_slots()
    state = _set_vagabond(state, pawn_forest=None, pawn_clearing=cid,
                          items=(_tile("torch"),), hand=())
    vp0 = state.vagabond().vp

    acts = legal_actions(state)
    exp = [a for a in acts if isinstance(a, VagabondExplore)]
    assert exp, "explore should be legal on a ruin clearing with a torch"
    state = apply(state, exp[0], rng)

    vs = state.vagabond()
    assert vs.vp == vp0 + 1, "1VP for the ruin item (9.5.3)"
    assert any(t.kind == hidden_kind and not t.damaged for t in vs.items), (
        "hidden item gained face up")
    assert next(t for t in vs.items if t.kind == "torch").exhausted, "F exhausted"
    assert not any(c == cid for c, _ in vs.ruin_items), "hidden item removed"
    assert not state.clearing(cid).ruin, "depleted ruin tile removed (9.5.3)"
    assert state.clearing(cid).occupied_slots() == slots_before - 1, "slot freed"
    print("  explore: got %s at clearing %d, vp=%d, ruin removed"
          % (hidden_kind, cid, vs.vp))


def test_vagabond_aid_relationship() -> None:
    """援助と関係強化(9.5.4 / 9.2.9.I/II.a): 1回→+1VP→2回→+2VP→3回→同盟
    (+2VP)、同盟後の援助+2VP、アイテム取得(相手の fs.items から移動)。"""
    rng = random.Random(22)
    state = _setup_marquise_vagabond(rng)
    c = 3  # mouse
    state = _clear(state, c)
    state = state.with_clearing(state.clearing(c).add_soldiers(M, 1))
    cards = _cards_of_suit(state, Suit.MOUSE, 7)
    state = _set_vagabond(state, pawn_forest=None, pawn_clearing=c,
                          hand=tuple(cards),
                          items=tuple(_tile("boots") for _ in range(7)))
    mfs = state.fs(M)
    state = state.with_faction_state(dataclasses.replace(
        mfs, items=(ItemKind.TEA,), hand=()))
    vp0 = state.vagabond().vp

    # 援助アクションが合法手に出る。相手ボックスにアイテムがあるなら
    # 取得は強制(9.5.4)なので take_item=None は出ない
    acts = legal_actions(state)
    aids = [a for a in acts if isinstance(a, VagabondAid)]
    assert any(a.take_item == "tea" for a in aids), "take_item option expected"
    assert not any(a.take_item is None for a in aids), \
        "no-take must be illegal while target has items (9.5.4)"

    # 1回目(コスト1): 無関心→マス1で+1VP。アイテム取得も行う
    state = apply(state, VagabondAid(player=V, faction=M, card_id=cards[0],
                                     take_item="tea"), rng)
    vs = state.vagabond()
    assert _rel(state, M) == 1 and vs.vp == vp0 + 1, "advance to 1: +1VP"
    assert ItemKind.TEA not in state.fs(M).items, "tea moved out of marquise box"
    assert any(t.kind == "tea" for t in vs.items), "tea gained by vagabond"
    assert cards[0] in state.fs(M).hand, "aid card given to marquise"

    # 2回で次のマスへ(コスト2): 1回目はVPなし、2回目で+2VP
    state = apply(state, VagabondAid(player=V, faction=M, card_id=cards[1]), rng)
    assert _rel(state, M) == 1 and state.vagabond().vp == vp0 + 1, "1/2: no VP yet"
    state = apply(state, VagabondAid(player=V, faction=M, card_id=cards[2]), rng)
    assert _rel(state, M) == 2 and state.vagabond().vp == vp0 + 3, "advance to 2: +2VP"

    # 3回で同盟へ(コスト3): +2VP
    state = apply(state, VagabondAid(player=V, faction=M, card_id=cards[3]), rng)
    state = apply(state, VagabondAid(player=V, faction=M, card_id=cards[4]), rng)
    assert state.vagabond().vp == vp0 + 3, "2/3: no VP yet"
    state = apply(state, VagabondAid(player=V, faction=M, card_id=cards[5]), rng)
    assert _rel(state, M) == 3 and state.vagabond().vp == vp0 + 5, "allied: +2VP"

    # 同盟後の援助: 毎回+2VP(9.2.9.II.a)
    state = apply(state, VagabondAid(player=V, faction=M, card_id=cards[6]), rng)
    assert _rel(state, M) == 3 and state.vagabond().vp == vp0 + 7, "allied aid: +2VP"
    print("  aid: relationship 0->3 (allied), vp +%d, item taken"
          % (state.vagabond().vp - vp0))


def test_vagabond_hostility_infamy() -> None:
    """敵対化と悪名(9.2.9.III/III.a): 戦闘で非敵対派閥の兵士除去→即敵対
    (トリガー除去はVPなし)、同一戦闘の後続除去で+1VP、狙撃では悪名なし。"""
    seed = random.Random(23)
    state = _setup_marquise_vagabond(seed)
    c = 3
    state = _clear(state, c)
    state = state.with_clearing(state.clearing(c).add_soldiers(M, 2))
    state = _set_vagabond(state, pawn_forest=None, pawn_clearing=c, hand=(),
                          items=(_tile("sword"), _tile("sword"), _tile("boots")))
    state = state.with_faction_state(dataclasses.replace(state.fs(M), hand=()))
    vp0 = state.vagabond().vp

    rng = ScriptedRng([3, 1])  # atk_roll=3, def_roll=1
    state = apply(state, VagabondBattle(player=V, defender=M), rng)
    # 出目上限=非損傷S 2枚(使用済みでも数える, 9.2.6) → 攻撃2ヒット
    dec = state.pending[-1]
    assert isinstance(dec, AllocateHitsDecision) and dec.victim == M and dec.hits == 2

    # 1体目の除去: 敵対化のトリガー(その除去自体は悪名VPなし)
    state = apply(state, legal_actions(state)[0], rng)
    assert _rel(state, M) == -1, "immediate hostility (9.2.9.III)"
    assert state.vagabond().vp == vp0, "trigger removal itself gives no VP"
    # 2体目の除去: 既に敵対 → 悪名+1VP(9.2.9.III.a)
    state = apply(state, legal_actions(state)[0], rng)
    assert state.vagabond().vp == vp0 + 1, "infamy +1VP for subsequent removal"
    # 部族の受け1ヒット: アイテム損傷(9.2.7)
    dec = state.pending[-1]
    assert isinstance(dec, ItemDamageDecision) and dec.remaining == 1
    state = apply(state, legal_actions(state)[0], rng)
    assert not state.pending
    assert sum(1 for t in state.vagabond().items if t.damaged) == 1

    # 狙撃(9.5.6)は戦闘ではない → 悪名なし(兵士除去のVPもなし)
    state = state.with_clearing(state.clearing(c).add_soldiers(M, 1))
    vs = state.vagabond()
    state = _set_vagabond(state, items=vs.items + (_tile("crossbow"),))
    vp1 = state.vagabond().vp
    state = apply(state, VagabondStrike(player=V, faction=M, target=("soldier",)), rng)
    assert state.clearing(c).soldier_count(M) == 0
    assert state.vagabond().vp == vp1, "strike is not battle: no infamy VP"
    print("  hostility/infamy: rel=-1, battle vp +1, strike vp +0")


def test_vagabond_battle_readings() -> None:
    """戦闘読み替え(9.2.4/9.2.6/9.2.7): 出目上限=非損傷S数、非損傷Sなしでの
    無防備+1、受けヒットのアイテム損傷、非損傷が尽きたら超過ヒット無視。"""
    # (a) 出目上限: 出目6でも非損傷S2枚 → 2ヒット
    seed = random.Random(24)
    state = _setup_marquise_vagabond(seed)
    c = 3
    state = _clear(state, c)
    state = state.with_clearing(state.clearing(c).add_soldiers(M, 5))
    state = _set_vagabond(state, pawn_forest=None, pawn_clearing=c, hand=(),
                          items=(_tile("sword"), _tile("sword"), _tile("boots")))
    state = state.with_faction_state(dataclasses.replace(state.fs(M), hand=()))
    rng = ScriptedRng([6, 1])
    state = apply(state, VagabondBattle(player=V, defender=M), rng)
    dec = state.pending[-1]
    assert isinstance(dec, AllocateHitsDecision) and dec.hits == 2, (
        "roll 6 capped at 2 non-damaged swords (9.2.6): %r" % (dec,))
    while state.pending:
        state = apply(state, legal_actions(state)[0], rng)

    # (b) 無防備+超過ヒット無視: 非損傷Sなしの部族を猫が攻撃
    seed = random.Random(25)
    state = _setup_marquise_vagabond(seed)
    c = 3
    state = _clear(state, c)
    state = state.with_clearing(state.clearing(c).add_soldiers(M, 3))
    # 非損傷S=0(損傷した剣のみ)、非損傷は boots+torch の2枚だけ
    state = _set_vagabond(state, pawn_forest=None, pawn_clearing=c, hand=(),
                          items=(_tile("sword", damaged=True), _tile("boots"),
                                 _tile("torch")))
    ms = state.fs(M)
    state = state.with_faction_state(dataclasses.replace(ms, hand=()))
    # 猫の昼光にして、部族への戦闘宣言が合法手に出ることも確認(9.2.2)
    state2 = state.replace(turn_index=state.factions.index(M), phase=Phase.DAYLIGHT)
    state2 = state2.with_faction_state(dataclasses.replace(
        state2.marquise(), actions_left=3))
    assert DeclareBattle(player=M, clearing=c, defender=V) in legal_actions(state2), (
        "marquise can battle the vagabond pawn")

    rng = ScriptedRng([2, 2])
    state = apply(state, DeclareBattle(player=M, clearing=c, defender=V), rng)
    # 攻撃 min(2,3)=2 + 無防備1(9.2.4) = 3ヒット。防御は非損傷S0 → 0ヒット
    dec = state.pending[-1]
    assert isinstance(dec, ItemDamageDecision) and dec.remaining == 3, (
        "defenseless +1: 3 hits as item damage: %r" % (dec,))
    state = apply(state, legal_actions(state)[0], rng)
    state = apply(state, legal_actions(state)[0], rng)
    # 非損傷が尽きた → 3ヒット目は無視され pending は空(9.2.7)
    assert not state.pending, "excess hits ignored when no non-damaged items"
    vs = state.vagabond()
    assert all(t.damaged for t in vs.items), "all 3 tiles damaged"
    print("  battle readings: cap=2 (roll 6), defenseless 3 hits, excess ignored")


def test_vagabond_revolt_damage() -> None:
    """反乱 vs 放浪者コマ(9.2.2.I): コマ残存+アイテム3損傷。"""
    rng = random.Random(26)
    state = new_game((M, A, V), rng)
    state = apply(state, SetupChooseKeep(player=M, corner="NW"), rng)
    state = apply(state, VagabondChooseCharacter(player=V, character="ranger"), rng)
    state = apply(state, VagabondChooseForest(player=V, forest=0), rng)
    assert not state.pending

    fox_cids = _clearings_of_suit(state, Suit.FOX)
    c = next(cid for cid in fox_cids if not state.clearing(cid).ruin)
    state = _clear(state, c)
    state = state.with_clearing(state.clearing(c).add_token(Piece(A, T_SYMPATHY)))
    supp = tuple(_cards_of_suit(state, Suit.FOX, 2))
    state = state.with_faction_state(dataclasses.replace(
        state.alliance(), placed_sympathy=1, supporters=supp))
    state = _set_vagabond(state, pawn_forest=None, pawn_clearing=c,
                          items=tuple(_tile(k) for k in
                                      ("boots", "sword", "torch", "hammer")))

    state = apply(state, AllianceRevolt(player=A, clearing=c), rng)
    dec = state.pending[-1]
    assert isinstance(dec, ItemDamageDecision) and dec.remaining == 3, (
        "revolt vs pawn: 3 item damage (9.2.2.I): %r" % (dec,))
    for _ in range(3):
        state = apply(state, legal_actions(state)[0], rng)
    assert not state.pending
    vs = state.vagabond()
    assert vs.pawn_clearing == c, "pawn never removed from the map (9.2.2)"
    assert sum(1 for t in vs.items if t.damaged) == 3
    print("  revolt vs pawn: pawn stays at %d, 3 tiles damaged" % c)


def test_vagabond_evening() -> None:
    """夕闇(9.6): 樹林での全回復、ドロー1+表X、上限6+2B超過時のゲーム除外。"""
    rng = random.Random(27)
    state = _setup_marquise_vagabond(rng)
    items = (
        _tile("sword", damaged=True),                 # 夜の休息で回復
        _tile("torch", exhausted=True, damaged=True),  # 〃(表に返る 9.6.1)
        _tile("coins", on_track=True),                 # ドロー+1(9.6.2)
        _tile("bag", on_track=True),                   # 上限+2(9.6.4)
    ) + tuple(_tile("boots") for _ in range(8))
    state = _set_vagabond(state, pawn_forest=0, pawn_clearing=None,
                          items=items, hand=())
    # 夕闇へ(昼光の EndPhase → begin_phase)
    state = apply(state, EndPhase(player=V), rng)
    assert state.phase == Phase.EVENING
    vs = state.vagabond()
    assert not any(t.damaged for t in vs.items), "forest rest repairs all (9.6.1)"
    assert not any(t.exhausted for t in vs.items), "repaired tiles turn face up"
    assert len(vs.hand) == 2, "draw 1 + 1 face-up coins (9.6.2): %d" % len(vs.hand)
    # 上限 = 6 + 2×表B(配置枠) = 8。かばん+損傷 = 10(sword,torch,boots×8)
    dec = state.pending[-1]
    assert isinstance(dec, ItemLimitDecision), "over item limit (9.6.4)"
    n_before = len(state.vagabond().items)
    steps = 0
    while state.pending:
        steps += 1
        assert steps < 10
        state = apply(state, legal_actions(state)[0], rng)
    vs = state.vagabond()
    assert len(vs.items) == n_before - 2, "2 tiles removed from the game"
    held = sum(1 for t in vs.items if not t.on_track)
    assert held == 8, "held items reduced to limit: %d" % held
    print("  evening: repaired all, drew 2, removed 2 tiles (limit 8)")


def test_vagabond_quest() -> None:
    """クエスト(9.5.5): 2アイテム消費、同種2枚目=2VP、補充で公開3枚に戻る。"""
    rng = random.Random(28)
    state = _setup_marquise_vagabond(rng)
    from .factions.vagabond import quest_ids
    all_q = quest_ids()
    open3 = ("errand-fox", "escort", "expel-bandits-rabbit")
    done = ("fundraising",)  # fox の解決済み1枚 → errand-fox 解決で同種2枚目
    deck = tuple(q for q in all_q if q not in open3 + done)
    c = _clearings_of_suit(state, Suit.FOX)[0]
    state = _set_vagabond(state, pawn_forest=None, pawn_clearing=c, hand=(),
                          quests_open=open3, quest_deck=deck, quests_done=done,
                          items=(_tile("tea", on_track=True), _tile("boots"),
                                 _tile("sword")))
    vp0 = state.vagabond().vp

    acts = legal_actions(state)
    qacts = [a for a in acts if isinstance(a, VagabondQuest)]
    assert sorted(a.reward for a in qacts if a.quest_id == "errand-fox") == \
        ["cards", "vp"], "errand-fox (tea+boots) offers both rewards: %r" % qacts
    assert not any(a.quest_id == "escort" for a in qacts), (
        "escort (mouse) does not match fox clearing")

    state = apply(state, VagabondQuest(player=V, quest_id="errand-fox",
                                       reward="vp"), rng)
    vs = state.vagabond()
    assert vs.vp == vp0 + 2, "2nd fox quest = 2VP: %d" % (vs.vp - vp0)
    assert next(t for t in vs.items if t.kind == "tea").exhausted, "tea spent"
    assert next(t for t in vs.items if t.kind == "boots").exhausted, "boots spent"
    assert not next(t for t in vs.items if t.kind == "sword").exhausted
    assert len(vs.quests_open) == 3, "replenished to 3 open quests"
    assert "errand-fox" in vs.quests_done
    assert len(vs.quest_deck) == len(deck) - 1
    print("  quest: errand-fox solved for 2VP, open quests back to 3")


# ============================================================
#  圧倒カード(3.3)+共闘軍(9.2.8)。DESIGN.md 14.8 の7シナリオ。
# ============================================================
def _resolve_setup(state: GameState, rng: random.Random) -> GameState:
    """セットアップ Decision を全解決する(城砦は NW 優先, 他は legal[0])。"""
    while state.pending:
        acts = legal_actions(state)
        act = acts[0]
        for a in acts:
            if isinstance(a, SetupChooseKeep) and a.corner == "NW":
                act = a
        state = apply(state, act, rng)
    return state


def _set_fs(state: GameState, faction: FactionId, **kw) -> GameState:
    return state.with_faction_state(dataclasses.replace(state.fs(faction), **kw))


def _sole_control(state: GameState, faction: FactionId, cids) -> GameState:
    """指定広場を全消去し faction の兵士1個ずつを置いて単独支配させる。"""
    for cid in cids:
        state = _clear(state, cid)
        state = state.with_clearing(state.clearing(cid).add_soldiers(faction, 1))
    return state


def _pull_from_deck(state: GameState, card_id: str) -> GameState:
    deck = list(state.deck)
    deck.remove(card_id)
    return state.replace(deck=tuple(deck))


def test_dominance_activation() -> None:
    """発動(3.3.1): VP9非合法・VP10合法、発動後は手札から消え VP 凍結(14.8-1)。"""
    rng = random.Random(101)
    state = _resolve_setup(new_game((M, E, A), rng), rng)
    idx = state.factions.index(M)
    dom = "dominance-mouse"
    state = state.replace(turn_index=idx, phase=Phase.DAYLIGHT)
    state = _set_fs(state, M, hand=(dom,), vp=9)
    assert not any(isinstance(a, ActivateDominance) for a in legal_actions(state)), \
        "VP9 では発動不可(3.3.1)"
    state = _set_fs(state, M, hand=(dom,), vp=10)
    acts = [a for a in legal_actions(state) if isinstance(a, ActivateDominance)]
    assert acts, "VP10 で発動可能(3.3.1)"
    state = apply(state, acts[0], rng)
    ms = state.fs(M)
    assert ms.dominance_card == dom and dom not in ms.hand, "発動→公開・手札から除去"
    assert award_vp(state, M, 5).fs(M).vp == ms.vp, "発動後は VP 凍結(award_vp no-op)"
    print("  dominance activate: 9->illegal, 10->legal, vp frozen at %d" % ms.vp)


def test_dominance_general_victory() -> None:
    """一般圧倒勝利(3.3.1.I): mouse 3広場支配で勝利、2広場では勝利しない(14.8-2)。"""
    rng = random.Random(102)
    base = _resolve_setup(new_game((M, E, A), rng), rng)
    idx = base.factions.index(M)
    base = _set_fs(base, M, hand=(), vp=10, dominance_card="dominance-mouse")
    mouse = [c.cid for c in base.clearings
             if base.map.clearing(c.cid).suit == Suit.MOUSE]

    def prep(control):
        s = base
        for cid in mouse:
            s = _clear(s, cid)
        s = _sole_control(s, M, control)
        return s.replace(turn_index=idx, phase=Phase.BIRDSONG)

    assert not check_dominance_victory(prep(mouse[:2])).finished, "2広場では勝利しない"
    win = check_dominance_victory(prep(mouse[:3]))
    assert win.finished and win.winner == M, "mouse3広場支配で圧倒勝利(3.3.1.I)"
    print("  general dominance: 2 clearings -> no, 3 clearings -> win")


def test_dominance_bird_victory() -> None:
    """鳥圧倒勝利(3.3.1.II): 対角隅 NW+SE で勝利、NW+NE では勝利しない(14.8-3)。"""
    rng = random.Random(103)
    base = _resolve_setup(new_game((M, E, A), rng), rng)
    idx = base.factions.index(M)
    base = _set_fs(base, M, hand=(), vp=10, dominance_card="dominance-bird")
    nw = base.map.corner_clearing(Corner.NW)
    ne = base.map.corner_clearing(Corner.NE)
    se = base.map.corner_clearing(Corner.SE)
    sw = base.map.corner_clearing(Corner.SW)

    def prep(control):
        s = _sole_control(base, M, [nw, ne, se, sw])  # 4隅を一旦消去して置換
        for cid in [nw, ne, se, sw]:
            s = _clear(s, cid)
        s = _sole_control(s, M, control)
        return s.replace(turn_index=idx, phase=Phase.BIRDSONG)

    assert not check_dominance_victory(prep([nw, ne])).finished, "隣接隅では勝利しない"
    win = check_dominance_victory(prep([nw, se]))
    assert win.finished and win.winner == M, "対角隅 NW+SE 支配で圧倒勝利(3.3.1.II)"
    print("  bird dominance: NW+NE -> no, NW+SE -> win")


def test_dominance_cost_and_recover() -> None:
    """コスト消費→盤脇→回収(3.3.3/3.3.4)。鳥圧倒は非鳥カードで回収不可(14.8-4)。"""
    rng = random.Random(104)
    base = _resolve_setup(new_game((M, E, A), rng), rng)
    idx = base.factions.index(M)

    # 3.3.3: 圧倒カードは捨て山でなく盤脇へ
    s = to_discard(base, "dominance-mouse")
    assert "dominance-mouse" in s.dominance_aside and "dominance-mouse" not in s.discard, \
        "圧倒カードは盤脇へ(3.3.3)"

    # 3.3.4: 盤脇の mouse 圧倒 + 手札の mouse カード → 回収が合法
    mouse_card = _cards_of_suit(base, Suit.MOUSE, 1)[0]
    s = _set_fs(base, M, hand=(mouse_card,)).replace(
        dominance_aside=("dominance-mouse",), turn_index=idx, phase=Phase.DAYLIGHT)
    takes = [a for a in legal_actions(s) if isinstance(a, TakeDominance)]
    assert takes, "一致動物種カードで回収が合法(3.3.4)"
    s2 = apply(s, takes[0], rng)
    assert "dominance-mouse" in s2.fs(M).hand, "圧倒カードを手札へ"
    assert not s2.dominance_aside and mouse_card not in s2.fs(M).hand, "盤脇除去・支払消費"

    # 3.3.4/2.1.1.II: 鳥圧倒は非鳥カードで回収不可、鳥カードなら可
    fox_card = _cards_of_suit(base, Suit.FOX, 1)[0]
    s3 = _set_fs(base, M, hand=(fox_card,)).replace(
        dominance_aside=("dominance-bird",), turn_index=idx, phase=Phase.DAYLIGHT)
    assert not any(isinstance(a, TakeDominance) for a in legal_actions(s3)), \
        "鳥圧倒は非鳥カードで回収不可(3.3.4)"
    bird_card = _cards_of_suit(base, Suit.BIRD, 1)[0]
    s4 = _set_fs(base, M, hand=(bird_card,)).replace(
        dominance_aside=("dominance-bird",), turn_index=idx, phase=Phase.DAYLIGHT)
    assert any(isinstance(a, TakeDominance) for a in legal_actions(s4)), "鳥カードで回収可"
    print("  cost/recover: aside not discard, mouse recovered, bird needs bird card")


def test_dominance_evening_discard() -> None:
    """夕闇の手札調整で圧倒カードを捨てると盤脇へ(捨て山に入らない, 14.8-5)。"""
    rng = random.Random(105)
    state = _resolve_setup(new_game((M, E, A), rng), rng)
    idx = state.factions.index(M)
    dom = "dominance-fox"
    extra = _cards_of_suit(state, Suit.RABBIT, 6)
    state = _set_fs(state, M, hand=(dom,) + tuple(extra))
    state = state.replace(turn_index=idx, phase=Phase.EVENING,
                          pending=(DiscardDecision(actor=M),))
    state = apply(state, DiscardCard(player=M, card_id=dom), rng)
    assert dom in state.dominance_aside, "捨てた圧倒カードは盤脇へ(3.3.3/14.3)"
    assert dom not in state.discard, "捨て山には入らない"
    print("  evening discard: dominance card routed to aside, not discard")


def test_coalition() -> None:
    """共闘軍(9.2.8): 3人戦非合法 / 4人戦で最低VP・同点複数 / 敵対→無関心 /
    相手勝利で winners に部族 / 結成後 VP 凍結(14.8-6)。"""
    from .factions.vagabond import _rel_get, _rel_set
    rng = random.Random(106)

    # 3人戦(M,V,E)では共闘不可
    s3 = _resolve_setup(new_game((M, V, E), rng), rng)
    s3 = _set_fs(s3, V, hand=("dominance-fox",)).replace(
        turn_index=s3.factions.index(V), phase=Phase.DAYLIGHT)
    assert not any(isinstance(a, VagabondCoalition) for a in legal_actions(s3)), \
        "3人戦では共闘不可(9.2.8)"

    # 4人戦(M,E,A,V): 最低VP対象
    state = _resolve_setup(new_game((M, E, A, V), rng), rng)
    vidx = state.factions.index(V)
    state = state.replace(turn_index=vidx, phase=Phase.DAYLIGHT)
    state = _set_fs(state, V, hand=("dominance-fox",))
    state = _set_fs(state, M, vp=0)
    state = _set_fs(state, E, vp=1)
    state = _set_fs(state, A, vp=2)
    coals = [a for a in legal_actions(state) if isinstance(a, VagabondCoalition)]
    assert {a.partner for a in coals} == {M}, "最低VPのMのみ対象(9.2.8)"
    tie = _set_fs(state, E, vp=0)
    coals_tie = [a for a in legal_actions(tie) if isinstance(a, VagabondCoalition)]
    assert {a.partner for a in coals_tie} == {M, E}, "同点は複数候補(9.2.8)"

    # 敵対派閥(M=-1)と共闘 → 無関心(0)へ(9.2.9.III.d)
    vs = dataclasses.replace(state.vagabond(),
                             relationships=_rel_set(state.vagabond(), M, -1))
    hostile = state.with_faction_state(vs)
    act = [a for a in legal_actions(hostile)
           if isinstance(a, VagabondCoalition) and a.partner == M][0]
    after = apply(hostile, act, rng)
    av = after.vagabond()
    assert av.coalition_with == M and av.dominance_card == "dominance-fox", \
        "共闘相手=M・カードは公開扱いで保持(9.2.8)"
    assert _rel_get(av, M) == 0, "敵対派閥との共闘で無関心へ(9.2.9.III.d)"
    assert award_vp(after, V, 5).vagabond().vp == av.vp, "共闘後 VP 凍結(9.2.8)"

    # 相手Mの勝利で部族も勝者(winners)
    won = after.replace(winner=M, finished=True)
    assert set(won.winners) == {M, V}, "共闘相手の勝利で部族も勝者(9.2.8)"
    print("  coalition: 3p illegal, min-vp target, tie->2, hostile->indifferent, winners={M,V}")


def test_dominance_card_conservation() -> None:
    """カード保存則54枚が dominance_card / dominance_aside 込みで成立(14.8-7)。"""
    rng = random.Random(107)
    state = _resolve_setup(new_game((M, E, A, V), rng), rng)
    doms = [c for c in state.deck if state.cards.get(c).is_dominance]
    assert len(doms) >= 2, "山札に圧倒カードが2枚以上残っている前提"
    # 1枚を発動(dominance_card)、1枚を盤脇へ(dominance_aside)。山札から移すので保存
    state = _pull_from_deck(state, doms[0])
    state = _set_fs(state, M, dominance_card=doms[0])
    state = _pull_from_deck(state, doms[1])
    state = state.replace(dominance_aside=(doms[1],))
    state.validate()  # 保存則が2ゾーン込みで成立
    print("  conservation: validate() ok with dominance_card=%s aside=%s"
          % (doms[0], doms[1]))


def main() -> int:
    print("selftest: battle via pending stack")
    test_battle_via_pending()
    print("selftest: ambush via pending stack")
    test_ambush_via_pending()
    print("selftest: eyrie turmoil (7.7)")
    test_eyrie_turmoil()
    print("selftest: eyrie turmoil new generation (7.7.3.I)")
    test_eyrie_turmoil_new_generation()
    print("selftest: alliance outrage pay from hand (8.2.6)")
    test_outrage_pay_from_hand()
    print("selftest: alliance outrage auto-draw (8.2.6)")
    test_outrage_auto_draw()
    print("selftest: alliance revolt (8.4.1)")
    test_revolt()
    print("selftest: alliance base removal chain (8.2.4)")
    test_base_removed()
    print("selftest: alliance guerrilla dice reversal (8.2.2)")
    test_guerrilla_dice()
    print("selftest: vagabond explore (9.5.3)")
    test_vagabond_explore()
    print("selftest: vagabond aid & relationship (9.5.4 / 9.2.9)")
    test_vagabond_aid_relationship()
    print("selftest: vagabond hostility & infamy (9.2.9.III)")
    test_vagabond_hostility_infamy()
    print("selftest: vagabond battle readings (9.2.4/9.2.6/9.2.7)")
    test_vagabond_battle_readings()
    print("selftest: vagabond revolt damage (9.2.2.I)")
    test_vagabond_revolt_damage()
    print("selftest: vagabond evening (9.6)")
    test_vagabond_evening()
    print("selftest: vagabond quest (9.5.5)")
    test_vagabond_quest()
    print("selftest: dominance activation (3.3.1)")
    test_dominance_activation()
    print("selftest: dominance general victory (3.3.1.I)")
    test_dominance_general_victory()
    print("selftest: dominance bird victory (3.3.1.II)")
    test_dominance_bird_victory()
    print("selftest: dominance cost & recover (3.3.3/3.3.4)")
    test_dominance_cost_and_recover()
    print("selftest: dominance evening discard (3.3.3)")
    test_dominance_evening_discard()
    print("selftest: coalition (9.2.8)")
    test_coalition()
    print("selftest: dominance card conservation (validate)")
    test_dominance_card_conservation()
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
