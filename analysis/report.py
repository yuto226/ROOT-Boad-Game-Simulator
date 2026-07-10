"""基礎集計レポート: simulation/runner.py が書いた SQLite を集計して表示する(DESIGN.md 10.3)。

使い方:
  python3 -m analysis.report                      # 最新 run を表示
  python3 -m analysis.report --run 3               # run_id=3 を表示
  python3 -m analysis.report --list                # runs 一覧のみ表示

集計はすべて sqlite3 の SQL で行い、print するだけ(pandas 等は未導入)。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import List, Optional


def _latest_run_id(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute("SELECT run_id FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    return row[0] if row else None


def _print_runs_list(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT run_id, created_at, label, factions, games, base_seed, "
        "max_turns, elapsed_sec, bots FROM runs ORDER BY run_id DESC"
    ).fetchall()
    if not rows:
        print("(runs テーブルは空です)")
        return
    # 旧 run は bots が NULL=random とみなす(DESIGN.md 11.4)。
    print("run_id  created_at                label            factions                      games  seed  max_turns  elapsed_sec  bots")
    for (run_id, created_at, label, factions, games, base_seed,
         max_turns, elapsed_sec, bots) in rows:
        print("%-7d %-25s %-16s %-29s %-6d %-5d %-10d %-12s %s"
              % (run_id, created_at, label or "-", factions, games, base_seed,
                 max_turns, "%.1f" % elapsed_sec if elapsed_sec is not None else "-",
                 bots or "random"))


def _percentile(conn: sqlite3.Connection, run_id: int, games: int, q: float) -> int:
    """games テーブルの turns を ORDER BY + OFFSET で q 分位点(0..1)を取り出す。"""
    offset = int((games - 1) * q)
    row = conn.execute(
        "SELECT turns FROM games WHERE run_id = ? ORDER BY turns LIMIT 1 OFFSET ?",
        (run_id, offset),
    ).fetchone()
    return row[0]


def _print_report(conn: sqlite3.Connection, run_id: int) -> None:
    run = conn.execute(
        "SELECT run_id, created_at, label, factions, games, base_seed, max_turns, "
        "validate, engine_commit, elapsed_sec, bots FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        print("run_id=%d は見つかりません" % run_id)
        return
    (_, created_at, label, factions_str, games, base_seed, max_turns,
     validate, engine_commit, elapsed_sec, bots) = run
    factions: List[str] = [f.strip() for f in factions_str.split(",")]

    # 1. run メタ情報
    print("[run] run_id=%d created_at=%s label=%s" % (run_id, created_at, label or "-"))
    print("      factions=%s games=%d base_seed=%d max_turns=%d validate=%d"
          % (factions_str, games, base_seed, max_turns, validate))
    print("      bots=%s" % (bots or "random"))
    print("      engine_commit=%s elapsed_sec=%s"
          % (engine_commit or "-", "%.1f" % elapsed_sec if elapsed_sec is not None else "-"))

    # 2. 派閥ごとの勝率
    timeouts = conn.execute(
        "SELECT COUNT(*) FROM games WHERE run_id = ? AND winner IS NULL", (run_id,)
    ).fetchone()[0]
    print("\n[勝率] games=%d timeouts=%d" % (games, timeouts))
    for f in factions:
        wins = conn.execute(
            "SELECT COUNT(*) FROM games WHERE run_id = ? AND winner = ?", (run_id, f)
        ).fetchone()[0]
        win_pct = 100.0 * wins / games if games else 0.0
        print("  %-10s wins=%-4d win%%=%.1f" % (f, wins, win_pct))

    # 3. ターン数の min/avg/max と分位点
    turns_row = conn.execute(
        "SELECT MIN(turns), AVG(turns), MAX(turns) FROM games WHERE run_id = ?", (run_id,)
    ).fetchone()
    t_min, t_avg, t_max = turns_row
    p25 = _percentile(conn, run_id, games, 0.25)
    p50 = _percentile(conn, run_id, games, 0.50)
    p75 = _percentile(conn, run_id, games, 0.75)
    print("\n[ターン数] min=%d avg=%.1f max=%d  P25=%d P50=%d P75=%d"
          % (t_min, t_avg, t_max, p25, p50, p75))

    # 4. 派閥ごとの VP min/avg/max
    print("\n[VP]")
    for f in factions:
        vp_row = conn.execute(
            "SELECT MIN(vp), AVG(vp), MAX(vp) FROM game_vps "
            "WHERE run_id = ? AND faction = ?", (run_id, f)
        ).fetchone()
        vp_min, vp_avg, vp_max = vp_row
        if vp_min is None:
            print("  %-10s (データなし)" % f)
            continue
        print("  %-10s min=%-3d avg=%-6.1f max=%d" % (f, vp_min, vp_avg, vp_max))

    # 5. 勝者別の平均ターン数
    print("\n[勝者別平均ターン数]")
    for f in factions:
        row = conn.execute(
            "SELECT AVG(turns), COUNT(*) FROM games WHERE run_id = ? AND winner = ?",
            (run_id, f),
        ).fetchone()
        avg_turns, n = row
        if n == 0:
            print("  %-10s (勝利なし)" % f)
        else:
            print("  %-10s avg_turns=%.1f (n=%d)" % (f, avg_turns, n))


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Root シミュレーション結果の基礎集計(DESIGN.md 10.3)")
    parser.add_argument("--db", type=str, default="simulation/results.sqlite")
    parser.add_argument("--run", type=int, default=None, help="run_id。省略時は最新 run")
    parser.add_argument("--list", action="store_true", help="runs 一覧のみ表示")
    args = parser.parse_args(argv)

    conn = sqlite3.connect(args.db)
    try:
        # DESIGN.md 11.4: 旧DB(bots列なし)を読むためのマイグレーション。
        # runner.py の _ensure_schema() と同じロジックをここでも独立して実行する
        # (analysis/ から simulation/ への依存を作らないため import はしない)。
        try:
            conn.execute("ALTER TABLE runs ADD COLUMN bots TEXT")
        except sqlite3.OperationalError:
            pass
        if args.list:
            _print_runs_list(conn)
            return 0

        run_id = args.run if args.run is not None else _latest_run_id(conn)
        if run_id is None:
            print("runs テーブルが空です(先に simulation.runner を実行してください)")
            return 1
        _print_report(conn, run_id)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
