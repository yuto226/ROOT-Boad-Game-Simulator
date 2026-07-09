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
    AllianceDiscardSupporter,
    AllianceRevolt,
    AllocateHit,
    AllocateHitsDecision,
    AmbushChoice,
    AmbushDefenderDecision,
    DeclareBattle,
    EndPhase,
    EyrieChooseCorner,
    EyrieChooseLeader,
    EyrieTurmoil,
    MarquiseMarch,
    OutrageDecision,
    OutragePay,
    SetupChooseKeep,
    SupportersLimitDecision,
)
from .apply import apply
from .battle import remove_piece
from .game import new_game
from .legal import legal_actions
from .state import GameState
from .types import (
    B_BASE,
    B_ROOST,
    B_SAWMILL,
    Corner,
    FactionId,
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
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
