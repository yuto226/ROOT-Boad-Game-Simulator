"""Game ファサード: セットアップ(5.1)・ターン進行・勝利判定(3.8)。"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .actions import (
    EyrieLeaderDecision,
    EyrieSetupCornerDecision,
    SetupKeepDecision,
    VagabondSetupCharacterDecision,
    VagabondSetupForestDecision,
)
from .apply import apply
from .board import load_board_defs, load_map
from .cards import CardIndex, load_card_defs, shuffled_deck
from .legal import legal_actions
from .state import (
    AllianceState,
    ClearingState,
    DummyState,
    EyrieState,
    FactionState,
    GameState,
    MarquiseState,
    VagabondState,
)
from .types import Corner, FactionId, ItemKind, OPPOSITE_CORNER, Phase, Suit

#: 共通サプライのアイテム(5.1.5)
SUPPLY_ITEMS: Tuple[Tuple[ItemKind, int], ...] = (
    (ItemKind.BOOTS, 2), (ItemKind.BAG, 2), (ItemKind.CROSSBOW, 1),
    (ItemKind.HAMMER, 1), (ItemKind.SWORD, 2), (ItemKind.TEA, 2),
    (ItemKind.COINS, 2),
)

#: 準備順(5.1.7): A→B→C→D
SETUP_ORDER = (FactionId.MARQUISE, FactionId.EYRIE,
               FactionId.ALLIANCE, FactionId.VAGABOND, FactionId.DUMMY)


def _initial_faction_state(faction: FactionId) -> FactionState:
    if faction == FactionId.MARQUISE:
        # 6.3.1: 兵士25・木材8
        return MarquiseState(faction=faction, soldiers_supply=25, wood_supply=8)
    if faction == FactionId.EYRIE:
        # 7.3.1: 兵士20
        return EyrieState(faction=faction, soldiers_supply=20)
    if faction == FactionId.ALLIANCE:
        # 8.3.1: 兵士10(拠点3・支持トークン10は state 側で管理)
        return AllianceState(faction=faction, soldiers_supply=10)
    if faction == FactionId.VAGABOND:
        # 9.3: 兵士なし(放浪者コマのみ)。キャラ・樹林はセットアップ Decision
        return VagabondState(faction=faction, soldiers_supply=0)
    if faction == FactionId.DUMMY:
        return DummyState(faction=faction, soldiers_supply=10)
    raise NotImplementedError("faction %s not implemented in phase 1" % faction.value)


def new_game(factions: Tuple[FactionId, ...], rng: random.Random) -> GameState:
    """初期状態を構築する(5.1)。

    セットアップ中のプレイヤー選択(城砦の隅 6.3.2 等)は Decision として
    pending に積まれる(3.9)。呼び出し側は pending が空になるまで通常の
    legal_actions/apply で解決してからターンループへ入る。
    """
    assert len(set(factions)) == len(factions), "同一派閥の重複は不可"
    map_data = load_map()
    board_defs = load_board_defs()
    defs, from_json = load_card_defs()
    index = CardIndex(defs, from_json)

    two_player = len(factions) == 2
    deck = shuffled_deck(index, two_player, rng)

    clearings = tuple(
        ClearingState(cid=c.id, ruin=c.ruin)  # 遺跡タイル配置(5.1.4)
        for c in map_data.clearings
    )
    fstates = tuple(_initial_faction_state(f) for f in factions)

    state = GameState(
        map=map_data,
        cards=index,
        board_defs=board_defs,
        factions=factions,
        faction_states=fstates,
        clearings=clearings,
        deck=tuple(deck),
        supply_items=SUPPLY_ITEMS,
    )

    # 5.1.3: 各プレイヤー3枚ドロー
    from .mechanics import draw_cards
    for f in factions:
        state = draw_cards(state, f, 3, rng)

    # 5.1.7: 派閥ごとの準備(A→B→…)。選択はセットアップ用 Decision。
    decisions = []
    for f in SETUP_ORDER:
        if f not in factions:
            continue
        if f == FactionId.MARQUISE:
            decisions.append(SetupKeepDecision(actor=f))
        elif f == FactionId.EYRIE:
            # 7.3.2 隅の選択 → 7.3.3 君主選択(忠臣配置 7.3.4 は適用側)
            decisions.append(EyrieSetupCornerDecision(actor=f))
            decisions.append(EyrieLeaderDecision(actor=f))
        elif f == FactionId.ALLIANCE:
            # 8.3.4 支援者獲得: 山札トップ3枚を支援者ボックスへ(選択なし=Decision不要)
            state = _setup_alliance_supporters(state, rng)
        elif f == FactionId.VAGABOND:
            # 9.3.3 クエスト山 / 9.3.4 遺跡アイテム / 9.3.6 関係マーカー(選択なし)
            state = _setup_vagabond(state, rng)
            # 9.3.1 キャラ選択 → 9.3.2 樹林選択(開始時アイテム 9.3.5 は適用側)
            decisions.append(VagabondSetupCharacterDecision(actor=f))
            decisions.append(VagabondSetupForestDecision(actor=f))
        # DUMMY はセットアップ選択なし
    if decisions:
        state = state.push_pending(*decisions)
    return state


def _setup_vagabond(state: GameState, rng: random.Random) -> GameState:
    """放浪部族の選択なしセットアップ(9.3.3 / 9.3.4 / 9.3.6)。

    - クエスト15枚をシャッフルして山を作り、上から3枚を公開する(9.3.3)。
    - 遺跡アイテム4種(boards.json ``ruin_items``)を4遺跡広場へランダムに
      割り当てる(9.3.4。隠匿情報として VagabondState.ruin_items に保持)。
    - 参加中の他派閥すべての関係マーカーを無関心(0)に置く(9.3.6)。
    """
    from .factions.vagabond import quest_ids
    vs = state.vagabond()
    qids = quest_ids()
    rng.shuffle(qids)
    open3 = tuple(qids.pop() for _ in range(3))  # 末尾=山の上(2.1 と同規約)
    ruin_cids = [c.id for c in state.map.clearings if c.ruin]
    kinds = list(state.board_defs["vagabond"]["ruin_items"])
    rng.shuffle(kinds)
    ruins = tuple(zip(ruin_cids, kinds))
    rels = tuple((f, 0) for f in state.factions if f != FactionId.VAGABOND)
    import dataclasses as _dc
    vs = _dc.replace(vs, quest_deck=tuple(qids), quests_open=open3,
                     ruin_items=ruins, relationships=rels)
    return state.with_faction_state(vs)


def _setup_alliance_supporters(state: GameState, rng: random.Random,
                               n: int = 3) -> GameState:
    """8.3.4: 山札トップ n 枚を支援者ボックスへ直接配置する。

    手札ドロー(5.1.3)とは別枠。add_supporter を通すため上限(8.2.3.I)も
    尊重されるが、拠点0・支援者0の初期状態で3枚なので実質そのまま入る。
    """
    from .factions.alliance import add_supporter
    deck = list(state.deck)
    discard = list(state.discard)
    drawn: List[str] = []
    for _ in range(n):
        if not deck:
            if not discard:
                break
            deck = discard
            discard = []
            rng.shuffle(deck)
        drawn.append(deck.pop())
    state = state.replace(deck=tuple(deck), discard=tuple(discard))
    for card in drawn:
        state = add_supporter(state, card)
    return state


def check_dominance_victory(state: GameState) -> GameState:
    """圧倒勝利の判定(3.3.1.I/II)。手番派閥の鳥歌フェイズ開始時に呼ぶ(14.5)。

    発動済み圧倒カードの動物種に応じて:
    - 一般(fox/rabbit/mouse): その動物種の広場を3ヶ所以上支配していれば勝利。
    - 鳥: 対角の隅広場2ヶ所(NW+SE または NE+SW)を支配していれば勝利。

    放浪部族は圧倒発動不可(9.2.8)のため判定対象外。
    成立なら ``winner`` を設定し ``finished=True`` にする。
    """
    if state.finished:
        return state
    f = state.current_faction()
    if f == FactionId.VAGABOND:
        return state
    fs = state.fs(f)
    if fs.dominance_card is None:
        return state
    suit = state.cards.suit_of(fs.dominance_card)
    if suit == Suit.BIRD:
        # 3.3.1.II: 対角の隅広場2ヶ所を支配
        for corner in (Corner.NW, Corner.NE):
            a = state.map.corner_clearing(corner)
            b = state.map.corner_clearing(OPPOSITE_CORNER[corner])
            if (a is not None and b is not None
                    and state.controls(f, a) and state.controls(f, b)):
                return state.replace(winner=f, finished=True)
        return state
    # 3.3.1.I: 一致動物種の広場を3ヶ所以上支配
    controlled = sum(
        1 for cs in state.clearings
        if state.map.clearing(cs.cid).suit == suit and state.controls(f, cs.cid))
    if controlled >= 3:
        return state.replace(winner=f, finished=True)
    return state


def begin_first_turn(state: GameState, rng: random.Random) -> GameState:
    """セットアップ完了後、先手番の鳥歌フェイズ開始処理を実行(3.8)。"""
    assert not state.pending, "setup decisions remain"
    # 3.3.1: 鳥歌開始時に圧倒勝利判定(begin_phase の前)
    state = check_dominance_victory(state)
    if state.finished:
        return state
    from .factions import get_logic
    return get_logic(state.current_faction()).begin_phase(state, rng)


@dataclass
class GameResult:
    """1試合の結果。"""

    winner: Optional[FactionId]
    turns: int
    vps: Dict[FactionId, int]
    timeout: bool
    #: 勝者の集合(3.1 / 9.2.8)。共闘軍の共同勝利を含む。単独勝利なら (winner,)。
    winners: Tuple[FactionId, ...] = ()


def run_game(factions: Tuple[FactionId, ...], policies: Dict[FactionId, object],
             seed: int, max_turns: int = 300,
             validate_each_step: bool = False) -> GameResult:
    """1試合を回す(3.8)。policies は faction -> Policy。

    30VP 到達で即勝利(3.1)。max_turns 超過で timeout 引き分け。

    ``validate_each_step=True`` のとき、各 apply 後に ``state.validate()`` を
    呼んで状態不変量(9.4)を検証する。既定 False(性能への影響を避ける)。
    """
    rng = random.Random(seed)
    state = new_game(factions, rng)

    setup_done = False
    while True:
        if state.finished:
            break
        if state.turn_count >= max_turns:
            break
        if not state.pending and not setup_done:
            state = begin_first_turn(state, rng)
            setup_done = True
        acts = legal_actions(state)
        assert acts, "no legal actions for %s" % state.to_act()
        if len(acts) == 1:
            action = acts[0]  # 単一選択は自動適用(3.2)
        else:
            policy = policies[state.to_act()]
            action = policy.choose(state, acts, rng)
        state = apply(state, action, rng)
        if validate_each_step:
            state.validate()

    return GameResult(
        winner=state.winner,
        turns=state.turn_count,
        vps={f: state.fs(f).vp for f in state.factions},
        timeout=state.winner is None,
        winners=state.winners,
    )
