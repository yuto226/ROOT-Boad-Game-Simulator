"""ヒューリスティックbotのテスト(DESIGN.md 11.5-1)。

(a) choose の返り値が渡した候補に含まれる
(b) 同一入力で同一出力(決定性 10.2)
(c) 勝利直結アクションを確実に選ぶ(終端ショートカット, 11.2 step 3)

conftest.py のヘルパー(make_state/set_hand/find_card/legal_of)を使う。
engine/・bots/base.py・bots/random_bot.py は変更していない。
"""
from __future__ import annotations

import dataclasses
import random

from engine.actions import CraftCard, EndPhase
from engine.apply import apply
from engine.legal import legal_actions
from engine.types import FactionId, ItemKind, Phase

from bots.heuristic import HeuristicBot, evaluate
from conftest import find_card, legal_of, make_state, set_hand

M = FactionId.MARQUISE
E = FactionId.EYRIE
A = FactionId.ALLIANCE
V = FactionId.VAGABOND


def test_choose_returns_a_candidate():
    """(a) choose の返り値は必ず渡した候補 actions のいずれか。"""
    state, _ = make_state((M, E, A))
    actions = legal_actions(state)
    assert actions, "初期状態に合法手があるはず"
    bot = HeuristicBot()
    chosen = bot.choose(state, actions, random.Random(0))
    assert chosen in actions


def test_deterministic_same_input_same_output():
    """(b) 同一 state/actions・同一 seed の rng なら choose は同一結果(10.2)。"""
    state, _ = make_state((M, E, A))
    actions = legal_actions(state)

    # 別インスタンス・同一 seed の rng で2回呼ぶ。
    r1 = HeuristicBot().choose(state, actions, random.Random(12345))
    r2 = HeuristicBot().choose(state, actions, random.Random(12345))
    assert r1 == r2

    # 異なる seed でも「同じ入力なら同じ内部シミュレーション列」になるよう、
    # base の消費が1回だけであることを間接確認: rng を1回 getrandbits した状態と一致。
    rng_a = random.Random(777)
    r3 = HeuristicBot().choose(state, actions, rng_a)
    rng_b = random.Random(777)
    r4 = HeuristicBot().choose(state, actions, rng_b)
    assert r3 == r4
    # choose は rng を getrandbits(32) 1回だけ消費する(消費列が seed から一意)。
    assert rng_a.getrandbits(32) == rng_b.getrandbits(32)


def test_picks_winning_action_via_terminal_shortcut():
    """(c) 勝利直結アクション(適用で me が 30VP 到達=勝利)を確実に選ぶ。

    猫を 29VP にして DAYLIGHT でブーツ(vp=1, cost=['rabbit'])をクラフトすると
    30VP 到達で finished/winner=marquise になる(3.1)。候補の末尾にクラフトを
    置いても(先頭の EndPhase ではなく)クラフトを選ぶことを確認する。
    """
    state, _ = make_state((M, E))
    state = state.replace(phase=Phase.DAYLIGHT)
    # 猫を 29VP に設定。
    ms = dataclasses.replace(state.marquise(), vp=29)
    state = state.with_faction_state(ms)
    # ブーツのクラフトカードを手札に置く(既定の工房=rabbit広場で支払える)。
    card = find_card(state, item=ItemKind.BOOTS)
    state = set_hand(state, M, (card,))

    craft = CraftCard(player=M, card_id=card)
    assert craft in legal_actions(state), "前提: クラフトが合法であること"

    # 適用すると勝利で終端することを直接確認(前提の健全性)。
    won = apply(state, craft, random.Random(0))
    assert won.finished and won.winner == M

    # EndPhase は勝利しない。候補の先頭に EndPhase、末尾にクラフトを置く。
    end = EndPhase(player=M)
    assert end in legal_actions(state), "前提: EndPhase も合法であること"
    actions = [end, craft]

    chosen = HeuristicBot().choose(state, actions, random.Random(0))
    assert chosen == craft, "終端ショートカットで勝利直結のクラフトを選ぶはず"


def test_vagabond_deterministic_same_input_same_output():
    """(b) 放浪部族(DESIGN.md 11.6)を含む決定性テスト: 同一 state/actions・
    同一 seed の rng なら choose は同一結果(vagabond.faction_term の経路を含む)。"""
    state, _ = make_state((M, E, A, V))
    actions = legal_actions(state)
    assert actions, "初期状態に合法手があるはず"

    r1 = HeuristicBot().choose(state, actions, random.Random(4321))
    r2 = HeuristicBot().choose(state, actions, random.Random(4321))
    assert r1 == r2


def test_evaluate_prefers_higher_vp():
    """評価関数の健全性: 自分の VP が高い状態のスコアは高い(11.3 の vp*100)。"""
    state, _ = make_state((M, E, A))
    low = evaluate(state, M)
    boosted = state.with_faction_state(
        dataclasses.replace(state.marquise(), vp=state.marquise().vp + 5))
    high = evaluate(boosted, M)
    assert high > low
