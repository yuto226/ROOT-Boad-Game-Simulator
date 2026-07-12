"""観戦APIサーバの検証(server/ 一式)。

torch 不要で全部回ること必須(nn: policy はここではテストしない)。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)


# ============================================================
# GET /api/models
# ============================================================
def test_list_models_endpoint(tmp_path, monkeypatch):
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    run_a.mkdir()
    run_b.mkdir()
    (run_a / "ckpt_10.pt").write_bytes(b"")
    (run_a / "ckpt_5.pt").write_bytes(b"")
    (run_b / "ckpt_100.pt").write_bytes(b"")
    (run_b / "not_a_ckpt.pt").write_bytes(b"")  # N をパースできない→スキップ

    monkeypatch.setenv("ROOT_SIM_RUNS", str(tmp_path))

    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data) == 3
    assert [e["update"] for e in data] == [100, 10, 5]
    for e in data:
        assert {"run", "update", "path", "mtime", "size_bytes"} <= set(e.keys())
    assert {e["run"] for e in data} == {"run_a", "run_b"}


# ============================================================
# POST /api/games
# ============================================================
def test_create_game_endpoint():
    resp = client.post("/api/games", json={
        "factions": ["marquise", "eyrie"],
        "policies": ["heuristic", "random"],
        "seed": 0,
    })
    assert resp.status_code == 200
    body = resp.json()

    assert "game_id" in body
    record = body["record"]
    assert set(record.keys()) == {"meta", "map", "steps"}
    assert record["meta"]["winner"] is None or isinstance(record["meta"]["winner"], str)
    assert len(record["steps"]) > 0
    assert set(record["meta"]["vps"].keys()) == {"marquise", "eyrie"}


def test_create_game_mismatched_lengths_returns_4xx():
    resp = client.post("/api/games", json={
        "factions": ["marquise", "eyrie"],
        "policies": ["random"],
        "seed": 0,
    })
    assert 400 <= resp.status_code < 500


def test_create_game_unknown_policy_returns_4xx():
    resp = client.post("/api/games", json={
        "factions": ["marquise", "eyrie"],
        "policies": ["heuristic", "foo"],
        "seed": 0,
    })
    assert 400 <= resp.status_code < 500


def test_create_game_unknown_faction_returns_4xx():
    resp = client.post("/api/games", json={
        "factions": ["marquise", "unknown"],
        "policies": ["heuristic", "random"],
        "seed": 0,
    })
    assert 400 <= resp.status_code < 500


# ============================================================
# GET /api/games, /api/games/{id}
# ============================================================
def test_get_game_roundtrip_and_404():
    created = client.post("/api/games", json={
        "factions": ["marquise", "eyrie"],
        "policies": ["random", "random"],
        "seed": 1,
        "max_turns": 8,
    }).json()
    game_id = created["game_id"]

    fetched = client.get("/api/games/%s" % game_id)
    assert fetched.status_code == 200
    assert fetched.json() == created["record"]

    listed = client.get("/api/games")
    assert listed.status_code == 200
    ids = [g["game_id"] for g in listed.json()]
    assert game_id in ids

    missing = client.get("/api/games/doesnotexist")
    assert missing.status_code == 404
