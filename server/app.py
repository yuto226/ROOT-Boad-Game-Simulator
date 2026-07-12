"""観戦API本体(FastAPI)。

起動:
  .venv/bin/uvicorn server.app:app --reload --port 8000

エンドポイント:
  GET  /api/models        — rl_runs 配下のチェックポイント一覧(ROOT_SIM_RUNS)
  POST /api/games         — 対局を1本生成して record を返す
  GET  /api/games         — 生成済み対局の一覧(概要のみ)
  GET  /api/games/{id}    — 生成済み対局の record を取得
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from server.games import create_game, get_game, list_games
from server.models import list_models

app = FastAPI(title="Root 観戦API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateGameRequest(BaseModel):
    factions: List[str]
    policies: List[str]
    seed: int = 0
    max_turns: int = 300


@app.get("/api/models")
def get_models() -> List[dict]:
    return list_models()


@app.post("/api/games")
def post_game(req: CreateGameRequest) -> dict:
    try:
        return create_game(req.factions, req.policies, req.seed, req.max_turns)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/games")
def get_games() -> List[dict]:
    return list_games()


@app.get("/api/games/{game_id}")
def get_game_by_id(game_id: str) -> dict:
    record = get_game(game_id)
    if record is None:
        raise HTTPException(status_code=404, detail="game not found: %r" % game_id)
    return record
