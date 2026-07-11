"""tools/record_game.py の検証(DESIGN.md 17.4-1)。

対象:
(a) observer が steps+1 回呼ばれる(小さな乱数局で)。
(b) 生成JSONの必須キー存在+steps[0].action==null。
(c) 同 seed 2回記録の一致(決定性)。
併せて engine.game.run_game の observer=None 既定が従来と完全同一に
振る舞うこと(17.1: additive)も確認する。
"""
from __future__ import annotations

import json

from bots.random_bot import RandomBot
from engine.types import FactionId
from tools.record_game import build_output, run_and_record, snapshot

_FACTIONS = (FactionId.MARQUISE, FactionId.EYRIE)


def _policies():
    return {f: RandomBot() for f in _FACTIONS}


# ============================================================
# (a) observer 呼び出し回数 = apply() 回数 + 1
# ============================================================
def test_observer_called_steps_plus_one(monkeypatch):
    import engine.game as game_mod

    real_apply = game_mod.apply
    calls = {"n": 0}

    def counting_apply(state, action, rng):
        calls["n"] += 1
        return real_apply(state, action, rng)

    monkeypatch.setattr(game_mod, "apply", counting_apply)

    result, steps = run_and_record(_FACTIONS, _policies(), seed=1, max_turns=5)

    assert calls["n"] > 0
    assert len(steps) == calls["n"] + 1
    assert steps[0]["i"] == 0
    assert steps[0]["action"] is None
    assert steps[0]["actor"] is None


# ============================================================
# (b) JSON スキーマの必須キー + steps[0].action == null
# ============================================================
def test_json_schema_required_keys(tmp_path):
    result, steps = run_and_record(_FACTIONS, _policies(), seed=2, max_turns=8)
    data = build_output(_FACTIONS, ["random", "random"], seed=2, max_turns=8,
                        result=result, steps=steps)

    assert set(data.keys()) == {"meta", "map", "steps"}

    meta_keys = {"factions", "policies", "seed", "max_turns", "winner", "winners",
                "vps", "turns", "timeout", "recorded_at"}
    assert meta_keys <= set(data["meta"].keys())
    assert data["meta"]["factions"] == ["marquise", "eyrie"]
    assert data["meta"]["seed"] == 2

    assert "clearings" in data["map"]
    assert len(data["map"]["clearings"]) == 12
    for c in data["map"]["clearings"]:
        assert {"id", "suit", "slots", "ruin", "corner", "adjacent"} <= set(c.keys())

    assert data["steps"][0]["action"] is None
    assert data["steps"][0]["actor"] is None

    state_keys = {"turn_count", "to_act", "finished", "pending", "vps",
                 "clearings", "hands", "draw_size", "discard_top", "faction_extras"}
    for step in data["steps"]:
        assert {"i", "actor", "action", "state"} <= set(step.keys())
        assert state_keys <= set(step["state"].keys())

    # file:// で開けるよう素朴な JSON として書き出せること。
    out = tmp_path / "game.json"
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded["meta"]["seed"] == 2
    assert reloaded["steps"][0]["action"] is None


def test_snapshot_matches_step_state():
    """snapshot(state) 単体呼び出しと observer 経由の step["state"] が同形であること。"""
    from engine.game import new_game
    import random

    rng = random.Random(0)
    state = new_game(_FACTIONS, rng)
    snap = snapshot(state)
    assert snap["turn_count"] == 0
    assert snap["finished"] is False
    assert len(snap["clearings"]) == 12
    assert set(snap["hands"].keys()) == {"marquise", "eyrie"}
    assert set(snap["faction_extras"].keys()) == {"marquise", "eyrie"}
    assert "wood_supply" in snap["faction_extras"]["marquise"]
    assert "leader" in snap["faction_extras"]["eyrie"]


# ============================================================
# (c) 同 seed 2回記録の一致(決定性)
# ============================================================
def test_same_seed_reproducible():
    r1, s1 = run_and_record(_FACTIONS, _policies(), seed=3, max_turns=8)
    r2, s2 = run_and_record(_FACTIONS, _policies(), seed=3, max_turns=8)

    assert r1.winner == r2.winner
    assert r1.turns == r2.turns
    assert r1.vps == r2.vps
    assert len(s1) == len(s2)
    assert [st["action"] for st in s1] == [st["action"] for st in s2]
    assert [st["state"] for st in s1] == [st["state"] for st in s2]


# ============================================================
# observer=None 既定の無影響(17.1: additive)
# ============================================================
def test_observer_default_none_unaffected():
    from engine.game import run_game

    r1 = run_game(factions=_FACTIONS, policies=_policies(), seed=4, max_turns=8)
    r2 = run_game(factions=_FACTIONS, policies=_policies(), seed=4, max_turns=8,
                  observer=None)

    assert r1.winner == r2.winner
    assert r1.turns == r2.turns
    assert r1.vps == r2.vps
    assert r1.timeout == r2.timeout
    assert r1.winners == r2.winners


def test_observer_does_not_change_game_outcome():
    """observer あり/なしで同じ乱数消費列を辿り結果が一致すること。"""
    from engine.game import run_game

    baseline = run_game(factions=_FACTIONS, policies=_policies(), seed=5, max_turns=8)

    seen = []
    result = run_game(factions=_FACTIONS, policies=_policies(), seed=5, max_turns=8,
                      observer=lambda action, state: seen.append(action))

    assert result.winner == baseline.winner
    assert result.turns == baseline.turns
    assert result.vps == baseline.vps
    assert len(seen) > 0
    assert seen[0] is None  # new_game 直後の初回呼び出し
