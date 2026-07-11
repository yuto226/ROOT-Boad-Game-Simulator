"""対局レコーダ(DESIGN.md 17.2)。

1対局を実行しつつ ``run_game`` の ``observer`` kwarg 経由で
毎ステップ完全情報スナップショットを取り、``ui/viewer.html`` が読み込める
JSON に書き出す。学習(フェーズ6)とは完全独立。torch は ``nn:<ckpt>``
policy 指定時のみ遅延 import する(17.1)。

CLI:
  python3 -m tools.record_game --factions marquise,eyrie \\
      --policies heuristic,random --seed 0 -o game.json

policy 指定(factions と同順のカンマ区切り):
  random / heuristic / nn:<ckptパス>[:sample](既定 greedy)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from bots.heuristic import HeuristicBot
from bots.random_bot import RandomBot
from engine.actions import Action
from engine.board import MapData, load_map
from engine.game import GameResult, run_game
from engine.state import GameState
from engine.types import FactionId, LOYAL_VIZIER


# ============================================================
# スナップショット(17.2)
# ============================================================
def snapshot(state: GameState) -> Dict:
    """1状態を完全情報 dict にする(17.2)。engine には入れない(tools 側)。"""
    clearings = []
    for cs in state.clearings:
        clearings.append({
            "cid": cs.cid,
            "soldiers": {f.value: n for f, n in cs.soldiers},
            "buildings": [{"faction": p.faction.value, "kind": p.kind}
                          for p in cs.buildings],
            "tokens": [{"faction": p.faction.value, "kind": p.kind}
                      for p in cs.tokens],
            "ruin": cs.ruin,
        })
    hands = {
        fs.faction.value: [state.cards.get(c).name for c in fs.hand]
        for fs in state.faction_states
    }
    discard_top = (state.cards.get(state.discard[-1]).name
                  if state.discard else None)  # 末尾=捨て山の一番上(mechanics.to_discard)
    return {
        "turn_count": state.turn_count,
        "to_act": state.to_act().value,
        "finished": state.finished,
        "pending": [type(dec).__name__ for dec in state.pending],
        "vps": {fs.faction.value: fs.vp for fs in state.faction_states},
        "clearings": clearings,
        "hands": hands,
        "draw_size": len(state.deck),
        "discard_top": discard_top,
        "faction_extras": {
            f.value: _faction_extras(state, f) for f in state.factions
        },
    }


def _card_names(state: GameState, card_ids) -> List[str]:
    return ["忠臣" if c == LOYAL_VIZIER else state.cards.get(c).name for c in card_ids]


def _faction_extras(state: GameState, faction: FactionId) -> Dict:
    """派閥固有の主要フィールド(17.2)。素直に state.py の該当フィールドから引く。"""
    fs = state.fs(faction)
    extras: Dict = {}
    if fs.dominance_card is not None:
        extras["dominance_card"] = state.cards.get(fs.dominance_card).name
    if faction == FactionId.MARQUISE:
        ms = state.marquise()
        extras.update({
            "wood_supply": ms.wood_supply,
            "keep_corner": ms.keep_corner,
        })
    elif faction == FactionId.EYRIE:
        es = state.eyrie()
        extras.update({
            "leader": es.leader,
            "decree": [_card_names(state, col) for col in es.decree],
        })
    elif faction == FactionId.ALLIANCE:
        als = state.alliance()
        extras.update({
            "supporters": len(als.supporters),
            "officers": als.officers,
            "placed_sympathy": als.placed_sympathy,
        })
    elif faction == FactionId.VAGABOND:
        vs = state.vagabond()
        extras.update({
            "items": [
                {"kind": it.kind, "exhausted": it.exhausted,
                 "damaged": it.damaged, "on_track": it.on_track}
                for it in vs.items
            ],
            "relationships": {f.value: level for f, level in vs.relationships},
            "coalition_with": vs.coalition_with.value if vs.coalition_with else None,
        })
    return extras


def _map_dict(map_data: MapData) -> Dict:
    """map_autumn.json の clearings をそのまま転記する(17.2)。"""
    return {
        "clearings": [
            {
                "id": c.id,
                "suit": c.suit.value,
                "slots": c.slots,
                "ruin": c.ruin,
                "corner": c.corner.value if c.corner is not None else None,
                "adjacent": list(c.adjacent),
            }
            for c in map_data.clearings
        ],
    }


# ============================================================
# 実行+記録(17.2)
# ============================================================
def run_and_record(factions: Tuple[FactionId, ...], policies: Dict[FactionId, object],
                    seed: int, max_turns: int = 300
                   ) -> Tuple[GameResult, List[Dict]]:
    """``run_game`` を ``observer`` 付きで実行し (結果, steps) を返す(17.2)。"""
    steps: List[Dict] = []

    def observer(action: Optional[Action], state: GameState) -> None:
        steps.append({
            "i": len(steps),
            "actor": action.player.value if action is not None else None,
            "action": repr(action) if action is not None else None,
            "state": snapshot(state),
        })

    result = run_game(factions=factions, policies=policies, seed=seed,
                      max_turns=max_turns, observer=observer)
    return result, steps


def build_output(factions: Tuple[FactionId, ...], policy_specs: List[str],
                 seed: int, max_turns: int, result: GameResult,
                 steps: List[Dict], map_data: Optional[MapData] = None) -> Dict:
    """JSON 化する最終 dict を組み立てる(17.2 のスキーマ)。"""
    if map_data is None:
        map_data = load_map()
    meta = {
        "factions": [f.value for f in factions],
        "policies": list(policy_specs),
        "seed": seed,
        "max_turns": max_turns,
        "winner": result.winner.value if result.winner is not None else None,
        "winners": [w.value for w in result.winners],
        "vps": {f.value: result.vps[f] for f in factions},
        "turns": result.turns,
        "timeout": result.timeout,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"meta": meta, "map": _map_dict(map_data), "steps": steps}


# ============================================================
# policy 構築(random/heuristic/nn:<ckpt>[:sample])
# ============================================================
def _make_nn_policy(ckpt_path: str, sample: bool, device_name: str):
    """torch を遅延 import して NNPolicy を構築する(17.1。rl.nn_policy 再利用)。"""
    from rl.eval import load_checkpoint, select_device  # 遅延import(torch依存)
    from rl.nn_policy import NNPolicy

    device = select_device(device_name)
    net, spec, catalog, _ckpt_factions, _meta = load_checkpoint(ckpt_path, device)
    return NNPolicy(net, spec, catalog, device, greedy=not sample)


def make_policy(spec: str, device_name: str = "auto"):
    """policy 指定文字列から Policy インスタンスを作る(17.2)。

    random / heuristic / nn:<ckptパス>[:sample](既定 greedy)。
    """
    if spec == "random":
        return RandomBot()
    if spec == "heuristic":
        return HeuristicBot()
    if spec.startswith("nn:"):
        rest = spec[len("nn:"):]
        sample = False
        if rest.endswith(":sample"):
            sample = True
            rest = rest[: -len(":sample")]
        if not rest:
            raise ValueError("nn: policy にはチェックポイントパスが必要: %r" % spec)
        return _make_nn_policy(rest, sample, device_name)
    raise ValueError(
        "未知の policy 指定: %r(random / heuristic / nn:<ckpt>[:sample])" % spec)


# ============================================================
# CLI
# ============================================================
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Root 対局レコーダ(DESIGN.md 17.2)")
    parser.add_argument("--factions", type=str, required=True,
                        help="カンマ区切りの派閥リスト(座席順)。例: marquise,eyrie")
    parser.add_argument("--policies", type=str, required=True,
                        help="factions と同順のカンマ区切り policy。"
                             "random/heuristic/nn:<ckpt>[:sample]")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-turns", type=int, default=300)
    parser.add_argument("--device", type=str, default="auto",
                        help="nn: policy 使用時のみ(auto/cpu/cuda/mps)")
    parser.add_argument("-o", "--out", type=str, default="game.json")
    args = parser.parse_args(argv)

    factions = tuple(FactionId(v.strip()) for v in args.factions.split(","))
    policy_specs = [s.strip() for s in args.policies.split(",")]
    if len(policy_specs) != len(factions):
        raise ValueError(
            "--policies の要素数(%d)が --factions(%d)と一致しない"
            % (len(policy_specs), len(factions)))
    policies = {f: make_policy(spec, args.device)
               for f, spec in zip(factions, policy_specs)}

    start = time.perf_counter()
    result, steps = run_and_record(factions, policies, args.seed, args.max_turns)
    elapsed = time.perf_counter() - start

    data = build_output(factions, policy_specs, args.seed, args.max_turns, result, steps)

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    size_bytes = os.path.getsize(args.out)

    print("recorded: out=%s factions=%s policies=%s seed=%d max_turns=%d "
          "winner=%s turns=%d steps=%d elapsed_sec=%.2f size_bytes=%d"
          % (args.out, [f.value for f in factions], policy_specs, args.seed,
             args.max_turns, result.winner.value if result.winner is not None else "timeout",
             result.turns, len(steps), elapsed, size_bytes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
