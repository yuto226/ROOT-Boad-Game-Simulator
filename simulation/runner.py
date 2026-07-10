"""並列対戦ランナー: N 試合を multiprocessing で実行し SQLite に保存する(DESIGN.md 10.2)。

使い方:
  python3 -m simulation.runner --games 200 --factions marquise,eyrie,alliance --seed 0
  python3 -m simulation.runner --games 50 --workers 1 --validate   # 直列・不変量検証つき

各試合は seed = base_seed + game_idx で決定的に定まる。--workers の値によらず
同じ (games, seed, factions) なら games テーブルの内容は一致する(決定性)。
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from bots.heuristic import HeuristicBot
from bots.random_bot import RandomBot
from engine.game import run_game
from engine.types import FactionId

#: ワーカーの戻り値: (seed, winner_value|None, turns, {faction_value: vp}, elapsed_sec)
WorkerResult = Tuple[int, Optional[str], int, Dict[str, int], float]

#: ワーカーへの引数: (seed, faction_values, max_turns, validate, bot_pairs)。
#: bot_pairs は (faction_value, bot_name) のタプル列(faction_values と同順=picklable かつ決定的)。
WorkerArgs = Tuple[int, Tuple[str, ...], int, bool, Tuple[Tuple[str, str], ...]]

#: 使用可能な bot 名(DESIGN.md 11.4)。
_BOT_NAMES = ("random", "heuristic")


def _make_bot(name: str):
    """bot 名から Policy インスタンスを構築する(DESIGN.md 11.4)。"""
    if name == "heuristic":
        return HeuristicBot()
    return RandomBot()


def _parse_bots(spec: str, faction_values: Tuple[str, ...]) -> Tuple[Tuple[str, str], ...]:
    """--bots SPEC を (faction_value, bot_name) 列に正規化する(DESIGN.md 11.4)。

    形式:
      - "random" / "heuristic": 全派閥一括
      - "marquise=heuristic,eyrie=random,...": 派閥別(未指定派閥は random)
    返り値は常に faction_values と同順(dict 反復順に依存しない=決定性 10.2)。
    """
    spec = spec.strip()
    if spec in _BOT_NAMES:
        return tuple((f, spec) for f in faction_values)
    mapping: Dict[str, str] = {}
    for part in spec.split(","):
        key, sep, val = part.partition("=")
        key = key.strip()
        val = val.strip()
        if not sep or key not in faction_values or val not in _BOT_NAMES:
            raise ValueError("不正な --bots 指定: %r(要素 %r)" % (spec, part))
        mapping[key] = val
    return tuple((f, mapping.get(f, "random")) for f in faction_values)


def _play_one(args: WorkerArgs) -> WorkerResult:
    """1試合を実行するトップレベル関数(picklable。multiprocessing のワーカーで呼ばれる)。

    ワーカー内で bot_pairs に従い per-faction に Policy を構築して run_game を呼ぶ。
    sqlite には触れない。
    """
    seed, faction_values, max_turns, validate, bot_pairs = args
    factions = tuple(FactionId(v) for v in faction_values)
    bot_map = dict(bot_pairs)
    policies = {f: _make_bot(bot_map[f.value]) for f in factions}

    start = time.perf_counter()
    result = run_game(factions=factions, policies=policies, seed=seed,
                       max_turns=max_turns, validate_each_step=validate)
    elapsed = time.perf_counter() - start

    winner = result.winner.value if result.winner is not None else None
    vps = {f.value: result.vps[f] for f in factions}
    return (seed, winner, result.turns, vps, elapsed)


def _engine_commit() -> Optional[str]:
    """`git rev-parse --short HEAD` を取得する。失敗時は None。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            label TEXT,
            factions TEXT NOT NULL,
            games INTEGER NOT NULL,
            base_seed INTEGER NOT NULL,
            max_turns INTEGER NOT NULL,
            validate INTEGER NOT NULL,
            engine_commit TEXT,
            elapsed_sec REAL,
            bots TEXT
        );
        CREATE TABLE IF NOT EXISTS games (
            run_id INTEGER NOT NULL REFERENCES runs(run_id),
            game_idx INTEGER NOT NULL,
            seed INTEGER NOT NULL,
            winner TEXT,
            turns INTEGER NOT NULL,
            elapsed_sec REAL,
            PRIMARY KEY (run_id, game_idx)
        );
        CREATE TABLE IF NOT EXISTS game_vps (
            run_id INTEGER NOT NULL,
            game_idx INTEGER NOT NULL,
            faction TEXT NOT NULL,
            vp INTEGER NOT NULL,
            PRIMARY KEY (run_id, game_idx, faction)
        );
    """)
    # 既存 DB(bots 列なし)へのマイグレーション(DESIGN.md 11.4)。
    # 重複追加時の OperationalError は無視する。旧 run は NULL のまま=random とみなす。
    try:
        conn.execute("ALTER TABLE runs ADD COLUMN bots TEXT")
    except sqlite3.OperationalError:
        pass


def _run_games(tasks: Sequence[WorkerArgs], games: int, workers: int) -> List[WorkerResult]:
    """tasks を実行して game_idx 順の結果リストを返す。

    --workers 1 のときは Pool を使わず直列実行する(デバッグ用・例外がそのまま出る)。
    それ以外は multiprocessing.Pool + imap_unordered(chunksize は games//(workers*8))。
    """
    results: List[Optional[WorkerResult]] = [None] * games
    completed = 0

    if workers == 1:
        for idx, task in enumerate(tasks):
            results[idx] = _play_one(task)
            completed += 1
            if completed % 100 == 0:
                print("progress: %d/%d" % (completed, games))
    else:
        pool_size = workers if workers > 0 else (os.cpu_count() or 1)
        chunksize = max(1, games // (pool_size * 8))
        seed_to_idx = {task[0]: idx for idx, task in enumerate(tasks)}
        with multiprocessing.Pool(pool_size) as pool:
            for res in pool.imap_unordered(_play_one, tasks, chunksize=chunksize):
                idx = seed_to_idx[res[0]]
                results[idx] = res
                completed += 1
                if completed % 100 == 0:
                    print("progress: %d/%d" % (completed, games))

    assert all(r is not None for r in results), "一部の試合結果が欠落した"
    return results  # type: ignore[return-value]


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Root 並列対戦ランナー(DESIGN.md 10.2)")
    parser.add_argument("--games", type=int, default=200)
    parser.add_argument("--factions", type=str, default="marquise,eyrie,alliance",
                         help="カンマ区切りの派閥リスト(入力順で runs.factions に記録される)")
    parser.add_argument("--seed", type=int, default=0, help="base_seed。試合 i の seed = base_seed + i")
    parser.add_argument("--max-turns", type=int, default=300)
    parser.add_argument("--workers", type=int, default=0, help="0=os.cpu_count()。1=直列実行")
    parser.add_argument("--db", type=str, default="simulation/results.sqlite")
    parser.add_argument("--validate", action="store_true",
                         help="各 apply 後に state.validate() で不変量(9.4)を検証する")
    parser.add_argument("--label", type=str, default=None, help="runs テーブルに残す任意メモ")
    parser.add_argument("--bots", type=str, default="random",
                         help="random/heuristic(全派閥一括)または "
                              "marquise=heuristic,eyrie=random,... 形式(DESIGN.md 11.4)")
    args = parser.parse_args(argv)

    faction_values = tuple(name.strip() for name in args.factions.split(","))
    for v in faction_values:
        FactionId(v)  # 不正な派閥名は起動時に弾く

    bot_pairs = _parse_bots(args.bots, faction_values)  # 不正な --bots は起動時に弾く
    bots_str = ",".join("%s=%s" % (f, name) for f, name in bot_pairs)

    tasks: List[WorkerArgs] = [
        (args.seed + i, faction_values, args.max_turns, args.validate, bot_pairs)
        for i in range(args.games)
    ]

    start = time.perf_counter()
    results = _run_games(tasks, args.games, args.workers)
    elapsed_sec = time.perf_counter() - start

    db_dir = os.path.dirname(args.db)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(args.db)
    try:
        _ensure_schema(conn)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO runs (created_at, label, factions, games, base_seed, "
            "max_turns, validate, engine_commit, elapsed_sec, bots) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(),
                args.label,
                ",".join(faction_values),
                args.games,
                args.seed,
                args.max_turns,
                int(args.validate),
                _engine_commit(),
                elapsed_sec,
                bots_str,
            ),
        )
        run_id = cur.lastrowid

        game_rows = []
        vp_rows = []
        wins = 0
        timeouts = 0
        for idx, (seed, winner, turns, vps, g_elapsed) in enumerate(results):
            game_rows.append((run_id, idx, seed, winner, turns, g_elapsed))
            if winner is None:
                timeouts += 1
            else:
                wins += 1
            for faction, vp in vps.items():
                vp_rows.append((run_id, idx, faction, vp))

        cur.executemany(
            "INSERT INTO games (run_id, game_idx, seed, winner, turns, elapsed_sec) "
            "VALUES (?,?,?,?,?,?)",
            game_rows,
        )
        cur.executemany(
            "INSERT INTO game_vps (run_id, game_idx, faction, vp) VALUES (?,?,?,?)",
            vp_rows,
        )
        conn.commit()
    finally:
        conn.close()

    print("run_id=%d games=%d wins=%d timeouts=%d elapsed_sec=%.1f"
          % (run_id, args.games, wins, timeouts, elapsed_sec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
