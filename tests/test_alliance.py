"""森林連合(第8章)の合法/違法テスト(DESIGN.md 9.3)。

DESIGN.md 9.3 の項目名と実装コードのクラス名には以下のズレがある
(判断根拠は engine/factions/alliance.py を正として確認済み):
  - 項目1「支持拡大 8.5.1」= 実装上は AllianceSpreadSympathy(8.4.2)。
  - 項目2「戒厳令 8.4.2.II.a」は AllianceSpreadSympathy のコストに
    +1する副次ルール(_martial_law / _spread_cost)として実装されている
    (独立したアクションではない)。
  - 項目3「蜂起 8.5.2: 一致スート支援者2枚で合法、基地設置+敵駒全除去」は
    実装上は AllianceRevolt(8.4.1)そのもの。tests/test_selftest.py の
    test_revolt で既にカバー済みのためここには書かない。
  - 項目4「憤慨 8.4.1: 他派閥が共感トークンを除去→一致スートのカードを
    支援者へ」は OutrageDecision/OutragePay の機構だが、selftest.py の
    test_outrage_pay_from_hand/test_outrage_auto_draw は「移動起因」の
    蜂起(outrage_on_move, 8.2.6)のみを検証しており、「除去起因」
    (on_sympathy_removed, battle.remove_piece 経由)は未カバー。
    ここではその未カバー側面(鳥ワイルドでの支払いも兼ねる)を補う。
  - 項目5「ゲリラ戦 8.4.3」は selftest.py の test_guerrilla_dice で
    カバー済みのためここには書かない。
  - 項目6「支援者上限 8.4.1」は実装上 8.2.3.I の add_supporter。
    selftest.py の test_base_removed は「全拠点喪失時」の5枚調整
    (SupportersLimitDecision)のみを検証しており、「拠点0の通常時に
    6枚目を得ようとした場合に即座に捨て札へ落ちる」分岐は未カバー。
"""
from __future__ import annotations

import dataclasses

from engine import battle as battle_mod
from engine.actions import AllianceMobilize, AllianceSpreadSympathy, OutrageDecision, OutragePay
from engine.apply import apply
from engine.state import GameState
from engine.types import CLEARING_SUITS, FactionId, Piece, Suit, T_SYMPATHY

from conftest import assert_illegal, assert_legal, find_card, legal_of, make_state, set_hand

M = FactionId.MARQUISE
A = FactionId.ALLIANCE


def _set_alliance(state: GameState, **kw) -> GameState:
    return state.with_faction_state(dataclasses.replace(state.alliance(), **kw))


def _cards_of_suit(state: GameState, suit: Suit, n: int):
    """山札に存在するカード定義から suit と一致する n 枚のIDを集める。

    圧倒カードは除外(2人戦の山札に存在しないため)。selftest.py の
    同名ヘルパーと同じ方針(conftest.find_card は1枚しか返せないため、
    複数枚必要なテストではこのローカルヘルパーを使う)。
    """
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


# ---------------- 1. 支持拡大 8.4.2: 累進コスト / 一致スート不足で違法 ----------------
def test_spread_sympathy_progressive_cost():
    """支持拡大 8.4.2: コストは配置済み支持トークン数(placed_sympathy)に応じて累進する。"""
    state, rng = make_state((M, A))
    state = state.replace(turn_index=state.factions.index(A))  # 鳥歌(8.4)は連合の手番
    costs = state.board_defs["alliance"]["sympathy_costs"]
    target = next(cs.cid for cs in state.clearings if not cs.has_token(A, T_SYMPATHY))
    suit = state.map.clearing(target).suit

    need_at_0 = costs[0]
    need_at_3 = costs[3]
    assert need_at_3 > need_at_0, "テスト前提: コストが累進する区間を選べていること"

    # placed_sympathy=0 → costs[0]枚ちょうどで合法
    cards0 = _cards_of_suit(state, suit, need_at_0)
    s0 = _set_alliance(state, placed_sympathy=0, supporters=tuple(cards0))
    assert_legal(s0, AllianceSpreadSympathy(player=A, clearing=target))

    # placed_sympathy=3 → costs[0]枚では足りない(累進コストが上がっている)
    s3_short = _set_alliance(state, placed_sympathy=3, supporters=tuple(cards0))
    assert_illegal(s3_short, AllianceSpreadSympathy(player=A, clearing=target))

    # placed_sympathy=3 → costs[3]枚あれば合法、適用後に支援者を全消費しVP獲得
    cards3 = _cards_of_suit(state, suit, need_at_3)
    s3_full = _set_alliance(state, placed_sympathy=3, supporters=tuple(cards3))
    assert_legal(s3_full, AllianceSpreadSympathy(player=A, clearing=target))
    applied = apply(s3_full, AllianceSpreadSympathy(player=A, clearing=target), rng)
    als = applied.alliance()
    assert als.placed_sympathy == 4
    assert len(als.supporters) == 0, "累進コスト分(costs[3]枚)を全消費するはず"
    assert applied.clearing(target).has_token(A, T_SYMPATHY)


def test_spread_sympathy_insufficient_matching_supporters_illegal():
    """支持拡大 8.4.2: 一致スートの支援者不足(枚数だけ足りていても種が違う)なら違法。"""
    state, rng = make_state((M, A))
    state = state.replace(turn_index=state.factions.index(A))
    costs = state.board_defs["alliance"]["sympathy_costs"]
    target = next(cs.cid for cs in state.clearings if not cs.has_token(A, T_SYMPATHY))
    suit = state.map.clearing(target).suit
    other_suit = next(s for s in CLEARING_SUITS if s != suit)
    need = costs[0]

    wrong_suit_cards = _cards_of_suit(state, other_suit, need)
    s_wrong = _set_alliance(state, placed_sympathy=0, supporters=tuple(wrong_suit_cards))
    assert_illegal(s_wrong, AllianceSpreadSympathy(player=A, clearing=target)), (
        "一致しない動物種の支援者では枚数が足りていても違法のはず")

    # 対照: 同じ枚数でも一致スートなら合法
    matching_cards = _cards_of_suit(state, suit, need)
    s_ok = _set_alliance(state, placed_sympathy=0, supporters=tuple(matching_cards))
    assert_legal(s_ok, AllianceSpreadSympathy(player=A, clearing=target))


# ---------------- 2. 戒厳令 8.4.2.II.a ----------------
def test_martial_law_increases_spread_cost():
    """戒厳令 8.4.2.II.a: 対象広場に連合以外の1派閥が兵士3個以上で支持拡大コスト+1。"""
    state, rng = make_state((M, A))
    state = state.replace(turn_index=state.factions.index(A))
    target = next(cs.cid for cs in state.clearings if not cs.has_token(A, T_SYMPATHY))
    suit = state.map.clearing(target).suit
    base_cost = state.board_defs["alliance"]["sympathy_costs"][0]

    cs = state.clearing(target).with_soldiers(M, 3)
    state = state.with_clearing(cs)

    # 通常コスト枚数だけでは(戒厳令の+1が乗るため)足りず違法
    exact_cards = _cards_of_suit(state, suit, base_cost)
    s_short = _set_alliance(state, placed_sympathy=0, supporters=tuple(exact_cards))
    assert_illegal(s_short, AllianceSpreadSympathy(player=A, clearing=target)), (
        "戒厳令(敵兵士3個以上)でコストが+1されているはず")

    # 通常コスト+1枚あれば合法、適用でその枚数を全消費
    extra_cards = _cards_of_suit(state, suit, base_cost + 1)
    s_full = _set_alliance(state, placed_sympathy=0, supporters=tuple(extra_cards))
    assert_legal(s_full, AllianceSpreadSympathy(player=A, clearing=target))
    applied = apply(s_full, AllianceSpreadSympathy(player=A, clearing=target), rng)
    assert len(applied.alliance().supporters) == 0


# ---------------- 4. 憤慨 8.4.1(除去起因の蜂起, on_sympathy_removed) ----------------
def test_outrage_via_token_removal_bird_wildcard():
    """憤慨 8.4.1: 他派閥が共感(支持)トークンを除去→そのプレイヤーは一致スート
    (鳥ワイルド含む)のカードを支援者へ。

    selftest.py がカバーする「移動起因」の蜂起(outrage_on_move, 8.2.6)とは別の
    トリガー経路である「除去起因」(on_sympathy_removed, battle.remove_piece 経由)
    を検証する。あわせて鳥カードによるワイルド支払い(2.1.1)も確認する。
    """
    state, rng = make_state((M, A))
    cid = next(cs.cid for cs in state.clearings if not cs.has_token(A, T_SYMPATHY))
    state = state.with_clearing(state.clearing(cid).add_token(Piece(A, T_SYMPATHY)))
    state = _set_alliance(state, placed_sympathy=1, supporters=())
    bird_card = find_card(state, suit=Suit.BIRD)
    state = set_hand(state, M, (bird_card,))

    state = battle_mod.remove_piece(state, cid, A, ("token", T_SYMPATHY), M)
    als = state.alliance()
    assert als.placed_sympathy == 0, "トークン除去で placed_sympathy が減算されるはず(8.2.5)"
    assert state.pending and isinstance(state.pending[-1], OutrageDecision)
    assert state.pending[-1].actor == M and state.pending[-1].clearing == cid

    pay_acts = [a for a in legal_of(state, OutragePay) if a.card_id == bird_card]
    assert pay_acts, "鳥カードはワイルドとして蜂起の支払いに使えるはず(2.1.1): %r" % (
        legal_of(state, OutragePay))
    state = apply(state, pay_acts[0], rng)
    assert not state.pending
    assert bird_card not in state.fs(M).hand
    assert state.alliance().supporters == (bird_card,)


# ---------------- 6. 支援者上限 8.2.3.I ----------------
def test_supporter_limit_without_base_discards_excess():
    """支援者上限 8.2.3.I: 拠点が盤上にない状態で6枚目を得ようとすると即座に捨て札へ。

    selftest.py の test_base_removed は「全拠点喪失時」に発生する5枚調整
    (SupportersLimitDecision)を検証済み。ここでは拠点0の通常時に6枚目を
    得ようとした際、デシジョンを経由せず add_supporter が直接捨て札に
    落とす分岐(factions/alliance.py の add_supporter)を検証する。
    """
    state, rng = make_state((M, A))
    five = _cards_of_suit(state, Suit.FOX, 5)
    state = _set_alliance(state, bases_placed=(), supporters=tuple(five))
    sixth = _cards_of_suit(state, Suit.RABBIT, 1)[0]
    state = set_hand(state, A, (sixth,))

    state = apply(state, AllianceMobilize(player=A, card_id=sixth), rng)
    als = state.alliance()
    assert als.supporters == tuple(five), "5枚を超える分は支援者ボックスに入らないはず"
    assert sixth in state.discard, "拠点0での6枚目は即座に捨て札へ落ちるはず"
    assert not state.pending, "5枚超過調整デシジョンは発生しないはず(全拠点喪失時のみ)"
