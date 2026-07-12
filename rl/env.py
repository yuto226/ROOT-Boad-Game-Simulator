"""RL 環境ラッパー RootEnv(AEC 互換, DESIGN.md 12.4)。

pettingzoo には依存せず、AEC API(reset/step/observe/last/agents/
agent_selection/rewards/terminations/truncations/infos)と同名・同義の
メソッドを duck-typing で実装する。本家 AEC 継承が必要になったら 6c で
薄いアダプタを書く。

- ``agent`` 文字列 = ``FactionId.value``。
- ``auto_single=True``: 合法手が1つだけの間は自動適用して次の意思決定点まで進める
  (エピソード長の短縮。run_game のターン数とは一致しなくなる — 仕様)。
- 報酬: 終局時に勝者 +1・他 -1、タイムアウト(max_turns 超過)は全員 0、途中 0。
  ``vp_shaping>0`` なら自派閥 VP 増分×係数を毎 step 加算(6c で使うかは未定)。
  ``build_shaping>0`` なら EYRIE の建設欄(勅令4列目)にポテンシャルベース
  シェイピングを加算する(方策不変・終局でゼロ化、12.7)。
- 乱数: reset で ``random.Random(seed)`` を1つ作り new_game / apply に注入
  (決定性 10.2。同一 seed+同一行動列で軌跡完全一致)。
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

import numpy as np

from engine.apply import apply
from engine.factions.eyrie import COL_BUILD, card_suit
from engine.game import begin_first_turn, new_game
from engine.legal import legal_actions
from engine.state import GameState
from engine.types import FactionId, Suit

from .catalog import ActionCatalog, action_for, action_key, legal_mask
from .encoder import ObservationSpec


def build_column_potential(state: GameState) -> float:
    """建設列(勅令4列目)のポテンシャル φ(s)(DESIGN.md 12.7)。

    建設列(decree[COL_BUILD])の鳥カード枚数 b・非鳥枚数 n を数え、
    φ = base(b) − 0.5·n(base: b==0→−1.0, b==1→+1.0, b>=2→0.0)。
    忠臣カード(LOYAL_VIZIER)は鳥として数える(7.3.4, card_suit 参照)。
    EYRIE が対戦にいない場合は 0.0(このシェイピングは EYRIE 専用)。
    """
    if FactionId.EYRIE not in state.factions:
        return 0.0
    column = state.eyrie().decree[COL_BUILD]
    b = sum(1 for card_id in column if card_suit(state, card_id) == Suit.BIRD)
    n = len(column) - b
    if b == 0:
        base = -1.0
    elif b == 1:
        base = 1.0
    else:
        base = 0.0
    return base - 0.5 * n


class RootEnv:
    """Root の AEC 互換環境(12.4)。"""

    def __init__(self, factions: Tuple[FactionId, ...], max_turns: int = 300,
                 auto_single: bool = True, seed: Optional[int] = None,
                 vp_shaping: float = 0.0, build_shaping: float = 0.0,
                 shaping_gamma: float = 1.0) -> None:
        self.factions: Tuple[FactionId, ...] = tuple(factions)
        self.max_turns = max_turns
        self.auto_single = auto_single
        self.vp_shaping = vp_shaping
        self.build_shaping = build_shaping
        self.shaping_gamma = shaping_gamma
        self.catalog = ActionCatalog()
        self.spec = ObservationSpec(self.factions)
        self.obs_dim = self.spec.obs_dim
        self.action_space_size = self.catalog.size
        self.possible_agents: List[str] = [f.value for f in self.factions]
        self._seed = seed
        self.reset(seed)

    # ------------------------------------------------------------
    def reset(self, seed: Optional[int] = None) -> None:
        """初期化して最初の意思決定点まで進める(12.4)。"""
        if seed is not None:
            self._seed = seed
        self._rng = random.Random(self._seed)
        self.state = new_game(self.factions, self._rng)
        self._setup_done = False
        self._done = False
        self._cur_acts: List = []
        self.agents: List[str] = list(self.possible_agents)
        self.rewards: Dict[str, float] = {a: 0.0 for a in self.possible_agents}
        self._cumulative_rewards: Dict[str, float] = {a: 0.0 for a in self.possible_agents}
        self.terminations: Dict[str, bool] = {a: False for a in self.possible_agents}
        self.truncations: Dict[str, bool] = {a: False for a in self.possible_agents}
        self.infos: Dict[str, Dict] = {a: {} for a in self.possible_agents}
        self._prev_vp: Dict[FactionId, int] = {
            fid: self.state.fs(fid).vp for fid in self.factions}
        if self.build_shaping and FactionId.EYRIE in self.factions:
            self._build_phi_prev = build_column_potential(self.state)
        else:
            self._build_phi_prev = 0.0
        self._advance()
        self.agent_selection: str = (
            self.state.to_act().value if not self._done else self.possible_agents[0])

    # ------------------------------------------------------------
    def _advance(self) -> None:
        """次の意思決定点(または終局)まで内部状態を進める。"""
        while True:
            if self.state.finished or self.state.turn_count >= self.max_turns:
                self._done = True
                self._cur_acts = []
                self.agents = []
                return
            if not self.state.pending and not self._setup_done:
                # セットアップ完了後の先手番の鳥歌開始処理(3.8)。以降のフェイズ
                # 開始処理は EndPhase 適用時に engine 側で自動実行される。
                self.state = begin_first_turn(self.state, self._rng)
                self._setup_done = True
                continue
            acts = legal_actions(self.state)
            if not acts:
                self._done = True
                self._cur_acts = []
                self.agents = []
                return
            if self.auto_single and len(acts) == 1:
                self.state = apply(self.state, acts[0], self._rng)
                continue
            self._cur_acts = acts
            return

    # ------------------------------------------------------------
    def observe(self, agent: str) -> Dict[str, "np.ndarray"]:
        """{"observation": float32[obs_dim], "action_mask": bool_[size]}(12.4)。

        action_mask は「その agent が現在手番で、かつ未終局」のときのみ合法手を立てる。
        """
        perspective = FactionId(agent)
        obs = self.spec.encode(self.state, perspective)
        if (not self._done) and agent == self.agent_selection:
            mask = legal_mask(self.state, self.catalog)
        else:
            mask = np.zeros(self.catalog.size, dtype=np.bool_)
        return {"observation": obs, "action_mask": mask}

    def last(self):
        """agent_selection の (obs, reward, terminated, truncated, info) を返す。"""
        a = self.agent_selection
        return (self.observe(a), self.rewards[a], self.terminations[a],
                self.truncations[a], self.infos[a])

    # ------------------------------------------------------------
    def step(self, action_index: int) -> None:
        """行動インデックスを適用し次の意思決定点まで進める(12.4)。"""
        if self._done:
            return  # 終局後のデッドステップは無視(AEC 慣習)
        actor = self.state.to_act()
        action = action_for(self.state, int(action_index), self.catalog, self._cur_acts)
        if action is None:
            raise ValueError(
                "illegal action index %d (key=%r) for agent %s; mask を尊重すること"
                % (action_index, self.catalog.key_at(int(action_index)), actor.value))
        self.state = apply(self.state, action, self._rng)
        self._advance()
        self._update_rewards(actor)
        if not self._done:
            self.agent_selection = self.state.to_act().value

    # ------------------------------------------------------------
    def _update_rewards(self, actor: FactionId) -> None:
        """step 後の報酬・終了フラグ・infos を更新する(12.4, 12.7)。

        ``_cumulative_rewards`` は途中の shaping 分も含めて毎 step 加算する
        (PPO 側が意思決定点間の差分で途中報酬を回収するため、13.3)。
        """
        self.rewards = {a: 0.0 for a in self.possible_agents}
        if self.vp_shaping:
            delta = self.state.fs(actor).vp - self._prev_vp[actor]
            self.rewards[actor.value] += self.vp_shaping * float(delta)
        for fid in self.factions:
            self._prev_vp[fid] = self.state.fs(fid).vp

        if self.build_shaping and FactionId.EYRIE in self.factions:
            # 建設欄ポテンシャルベースシェイピング(potential-based, 方策不変, 12.7)。
            phi_new = build_column_potential(self.state)
            self.rewards[FactionId.EYRIE.value] += self.build_shaping * (
                self.shaping_gamma * phi_new - self._build_phi_prev)
            self._build_phi_prev = phi_new

        if self._done:
            terminated = bool(self.state.finished)
            timed_out = not terminated  # max_turns 超過(勝者なし)
            winner = self.state.winner
            for fid in self.factions:
                a = fid.value
                self.terminations[a] = terminated
                self.truncations[a] = timed_out
            if terminated and winner is not None:
                for fid in self.factions:
                    self.rewards[fid.value] += 1.0 if fid == winner else -1.0
            # timed_out は勝敗分の加算なし(初期化のまま)
            if self.build_shaping and FactionId.EYRIE in self.factions:
                # 終局(勝敗確定・タイムアウトとも)でポテンシャルをゼロ化(12.7)。
                self.rewards[FactionId.EYRIE.value] += self.build_shaping * (
                    0.0 - self._build_phi_prev)
                self._build_phi_prev = 0.0
            for fid in self.factions:
                self.infos[fid.value] = {
                    "winner": winner.value if winner is not None else None,
                    "turns": self.state.turn_count,
                    "vp": self.state.fs(fid).vp,
                }

        for a in self.possible_agents:
            self._cumulative_rewards[a] += self.rewards[a]
