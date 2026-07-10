"""可視化ダッシュボード: simulation/runner.py が書いた SQLite を集計し、
Chart.js の静的HTML(自己完結1ファイル)として出力する(DESIGN.md 10.5)。

使い方:
  python3 -m analysis.dashboard                       # 全 run を1枚のHTMLに
  python3 -m analysis.dashboard --runs 1,3,5            # run_id を指定
  python3 -m analysis.dashboard -o simulation/dashboard.html --db simulation/results.sqlite

集計はすべて sqlite3 の SQL で行う(pandas 等は未導入)。データは JSON として
HTML に埋め込み、描画は CDN から読み込む Chart.js が担う。Python 側のテンプレート
処理は素朴な文字列置換のみ。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Dict, List, Optional, Tuple

#: 派閥の固定カラーマップ(DESIGN.md 10.5)。将来の派閥追加でも色が安定するように固定する。
FACTION_COLORS: Dict[str, str] = {
    "marquise": "#d97706",
    "eyrie": "#2563eb",
    "alliance": "#16a34a",
    "vagabond": "#6b7280",
    "timeout": "#9ca3af",
}

#: FACTION_COLORS のうち実際にプレイヤブルな派閥(勝者になりうる値)の表示順。
_FACTION_ORDER = ["marquise", "eyrie", "alliance", "vagabond"]

#: ターン数ヒストグラムのビン幅(DESIGN.md 10.5)。
HIST_BIN_WIDTH = 5

#: run 比較の折れ線オーバーレイに使う配色(派閥色とは独立。run数が増えたら循環する)。
_RUN_PALETTE = ["#0ea5e9", "#db2777", "#65a30d", "#9333ea", "#ea580c",
                "#0d9488", "#dc2626", "#4338ca"]

CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"


def _run_label(run_id: int, label: Optional[str], games: int) -> str:
    """run のラベル表記 `#id label(games)`(DESIGN.md 10.5 表記統一)。"""
    return "#%d %s(%d)" % (run_id, label or "-", games)


def _resolve_run_ids(conn: sqlite3.Connection, runs_arg: Optional[str]) -> List[int]:
    """--runs 引数(カンマ区切り run_id)を解決する。省略時は全 run を run_id 昇順で。"""
    if runs_arg:
        ids = [int(x.strip()) for x in runs_arg.split(",") if x.strip()]
        existing = {row[0] for row in conn.execute("SELECT run_id FROM runs").fetchall()}
        missing = [i for i in ids if i not in existing]
        if missing:
            raise SystemExit("run_id が見つかりません: %s" % missing)
        return ids
    rows = conn.execute("SELECT run_id FROM runs ORDER BY run_id").fetchall()
    return [r[0] for r in rows]


def _fetch_run_meta(conn: sqlite3.Connection, run_id: int) -> dict:
    row = conn.execute(
        "SELECT run_id, created_at, label, factions, games, base_seed, max_turns, "
        "validate, engine_commit, elapsed_sec FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    (rid, created_at, label, factions_str, games, base_seed, max_turns,
     validate, engine_commit, elapsed_sec) = row
    factions = [f.strip() for f in factions_str.split(",")]
    return {
        "run_id": rid,
        "created_at": created_at,
        "label": label,
        "factions": factions,
        "games": games,
        "base_seed": base_seed,
        "max_turns": max_turns,
        "validate": bool(validate),
        "engine_commit": engine_commit,
        "elapsed_sec": elapsed_sec,
    }


def _fetch_winrates(conn: sqlite3.Connection, run_id: int, games: int,
                     factions: List[str]) -> Dict[str, float]:
    """派閥ごとの勝率(%)+timeout率(%)。games=0 のときは全て0とする。"""
    rates: Dict[str, float] = {}
    for f in factions:
        wins = conn.execute(
            "SELECT COUNT(*) FROM games WHERE run_id = ? AND winner = ?", (run_id, f)
        ).fetchone()[0]
        rates[f] = 100.0 * wins / games if games else 0.0
    timeouts = conn.execute(
        "SELECT COUNT(*) FROM games WHERE run_id = ? AND winner IS NULL", (run_id,)
    ).fetchone()[0]
    rates["timeout"] = 100.0 * timeouts / games if games else 0.0
    return rates


def _fetch_vp_stats(conn: sqlite3.Connection, run_id: int,
                     factions: List[str]) -> Dict[str, Optional[Tuple[float, float, float]]]:
    """派閥ごとの VP (min, avg, max)。データがない派閥は None。"""
    stats: Dict[str, Optional[Tuple[float, float, float]]] = {}
    for f in factions:
        row = conn.execute(
            "SELECT MIN(vp), AVG(vp), MAX(vp) FROM game_vps WHERE run_id = ? AND faction = ?",
            (run_id, f),
        ).fetchone()
        vp_min, vp_avg, vp_max = row
        stats[f] = None if vp_min is None else (float(vp_min), float(vp_avg), float(vp_max))
    return stats


def _fetch_turns(conn: sqlite3.Connection, run_id: int) -> List[int]:
    rows = conn.execute("SELECT turns FROM games WHERE run_id = ?", (run_id,)).fetchall()
    return [r[0] for r in rows]


def _build_histogram(turns_by_label: Dict[str, List[int]],
                      bin_width: int = HIST_BIN_WIDTH) -> Tuple[List[str], Dict[str, List[int]]]:
    """runラベルごとのターン数リストから、共通ビンのヒストグラム(オーバーレイ比較用)を作る。"""
    all_turns = [t for turns in turns_by_label.values() for t in turns]
    if not all_turns:
        return [], {label: [] for label in turns_by_label}

    lo = (min(all_turns) // bin_width) * bin_width
    hi = ((max(all_turns) // bin_width) + 1) * bin_width
    bin_starts = list(range(lo, hi, bin_width))
    labels = ["%d-%d" % (b, b + bin_width - 1) for b in bin_starts]

    series: Dict[str, List[int]] = {}
    for label, turns in turns_by_label.items():
        counts = [0] * len(bin_starts)
        for t in turns:
            idx = min((t - lo) // bin_width, len(bin_starts) - 1)
            counts[idx] += 1
        series[label] = counts
    return labels, series


def _ordered_factions(all_factions: set) -> List[str]:
    """FACTION_COLORS の固定順を優先し、未知の派閥名は末尾にソートして追加する。"""
    ordered = [f for f in _FACTION_ORDER if f in all_factions]
    extra = sorted(f for f in all_factions if f not in _FACTION_ORDER)
    return ordered + extra


def build_dashboard_data(conn: sqlite3.Connection, run_ids: List[int]) -> dict:
    """指定 run 群から DATA(HTMLに埋め込む JSON)を組み立てる。"""
    metas = [_fetch_run_meta(conn, rid) for rid in run_ids]
    all_factions: set = set()
    for m in metas:
        all_factions.update(m["factions"])
    factions = _ordered_factions(all_factions)

    runs_out = []
    turns_by_label: Dict[str, List[int]] = {}
    for m in metas:
        run_label = _run_label(m["run_id"], m["label"], m["games"])
        winrates = _fetch_winrates(conn, m["run_id"], m["games"], factions)
        vp_stats = _fetch_vp_stats(conn, m["run_id"], factions)
        turns = _fetch_turns(conn, m["run_id"])
        turns_by_label[run_label] = turns

        runs_out.append({
            "run_id": m["run_id"],
            "run_label": run_label,
            "created_at": m["created_at"],
            "label": m["label"],
            "factions": m["factions"],
            "games": m["games"],
            "base_seed": m["base_seed"],
            "max_turns": m["max_turns"],
            "engine_commit": m["engine_commit"],
            "elapsed_sec": m["elapsed_sec"],
            "winrates": winrates,
            "vp": {f: (None if v is None else {"min": v[0], "avg": v[1], "max": v[2]})
                   for f, v in vp_stats.items()},
        })

    hist_labels, hist_series = _build_histogram(turns_by_label)

    return {
        "runs": runs_out,
        "factions": factions,
        "faction_colors": FACTION_COLORS,
        "run_palette": _RUN_PALETTE,
        "turns_hist": {"labels": hist_labels, "series": hist_series},
    }


_PAGE_TEMPLATE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Root シミュレーション ダッシュボード</title>
<script src="__CHART_JS_CDN__"></script>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", sans-serif;
    margin: 0; padding: 24px; background: #f8fafc; color: #0f172a;
  }
  h1 { font-size: 1.4rem; margin-bottom: 4px; }
  .sub { color: #64748b; margin-bottom: 24px; font-size: 0.9rem; }
  section {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 16px 20px; margin-bottom: 24px;
  }
  h2 { font-size: 1.05rem; margin-top: 0; }
  .chart-wrap { position: relative; height: 380px; }
  table { border-collapse: collapse; width: 100%; font-size: 0.88rem; }
  th, td { border-bottom: 1px solid #e2e8f0; padding: 6px 10px; text-align: left; }
  th { color: #475569; font-weight: 600; }
  code { background: #f1f5f9; padding: 1px 5px; border-radius: 4px; }
  @media (prefers-color-scheme: dark) {
    body { background: #0b1220; color: #e2e8f0; }
    section { background: #111827; border-color: #1f2937; }
    .sub { color: #94a3b8; }
    th, td { border-bottom-color: #1f2937; }
    th { color: #cbd5e1; }
    code { background: #1f2937; }
  }
</style>
</head>
<body>
<h1>Root シミュレーション ダッシュボード</h1>
<p class="sub">simulation/runner.py の結果DBから生成(DESIGN.md 10.5)。runs: __RUN_LABELS__</p>

<section>
  <h2>1. run比較: 派閥別勝率</h2>
  <div class="chart-wrap"><canvas id="chart-winrate"></canvas></div>
</section>

<section>
  <h2>2. ターン数分布(ビン幅 __BIN_WIDTH__)</h2>
  <div class="chart-wrap"><canvas id="chart-turns"></canvas></div>
</section>

<section>
  <h2>3. 派閥別VP分布(平均・最小-最大)</h2>
  <div class="chart-wrap"><canvas id="chart-vp"></canvas></div>
</section>

<section>
  <h2>4. runメタ情報</h2>
  <table id="meta-table">
    <thead>
      <tr>
        <th>run_id</th><th>created_at</th><th>label</th><th>factions</th>
        <th>games</th><th>engine_commit</th><th>elapsed_sec</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>
</section>

<script>
const DATA = __DATA_JSON__;

function buildMetaTable() {
  const tbody = document.querySelector('#meta-table tbody');
  for (const r of DATA.runs) {
    const tr = document.createElement('tr');
    const cells = [
      r.run_id, r.created_at, r.label ?? '-', r.factions.join(', '),
      r.games, r.engine_commit ?? '-',
      r.elapsed_sec !== null ? r.elapsed_sec.toFixed(1) : '-',
    ];
    for (const c of cells) {
      const td = document.createElement('td');
      td.textContent = String(c);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function colorFor(faction) {
  return DATA.faction_colors[faction] || '#a1a1aa';
}

function buildWinrateChart() {
  const labels = DATA.runs.map(r => r.run_label);
  const seriesKeys = [...DATA.factions, 'timeout'];
  const datasets = seriesKeys.map(f => ({
    label: f,
    data: DATA.runs.map(r => r.winrates[f] ?? 0),
    backgroundColor: colorFor(f),
  }));
  new Chart(document.getElementById('chart-winrate'), {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true, max: 100, title: { display: true, text: '勝率 (%)' } },
      },
      plugins: {
        legend: { position: 'bottom' },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}%` } },
      },
    },
  });
}

function buildTurnsChart() {
  const labels = DATA.turns_hist.labels;
  const seriesEntries = Object.entries(DATA.turns_hist.series);
  const datasets = seriesEntries.map(([runLabel, counts], i) => ({
    label: runLabel,
    data: counts,
    borderColor: DATA.run_palette[i % DATA.run_palette.length],
    backgroundColor: DATA.run_palette[i % DATA.run_palette.length],
    fill: false,
    tension: 0.15,
    pointRadius: 2,
  }));
  new Chart(document.getElementById('chart-turns'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: { title: { display: true, text: 'ターン数' } },
        y: { beginAtZero: true, title: { display: true, text: '試合数' } },
      },
      plugins: { legend: { position: 'bottom' } },
    },
  });
}

function buildVpChart() {
  const labels = DATA.runs.map(r => r.run_label);
  const datasets = DATA.factions.map(f => {
    const avgValues = DATA.runs.map(r => (r.vp[f] ? r.vp[f].avg : null));
    return {
      label: f,
      data: DATA.runs.map(r => r.vp[f] ? [r.vp[f].min, r.vp[f].max] : [null, null]),
      backgroundColor: colorFor(f) + '55',
      borderColor: colorFor(f),
      borderWidth: 1,
      avgValues,
    };
  });
  new Chart(document.getElementById('chart-vp'), {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true, title: { display: true, text: 'VP (min-max、色は派閥)' } },
      },
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const avg = ctx.dataset.avgValues[ctx.dataIndex];
              const [min, max] = ctx.raw ?? [null, null];
              if (min === null) return `${ctx.dataset.label}: データなし`;
              return `${ctx.dataset.label}: min=${min} avg=${avg.toFixed(1)} max=${max}`;
            },
          },
        },
      },
    },
  });
}

buildMetaTable();
buildWinrateChart();
buildTurnsChart();
buildVpChart();
</script>
</body>
</html>
"""


def render_html(data: dict) -> str:
    """DATA を埋め込んだ自己完結HTMLを生成する。"""
    run_labels = ", ".join(r["run_label"] for r in data["runs"])
    html = _PAGE_TEMPLATE
    html = html.replace("__CHART_JS_CDN__", CHART_JS_CDN)
    html = html.replace("__RUN_LABELS__", run_labels or "(なし)")
    html = html.replace("__BIN_WIDTH__", str(HIST_BIN_WIDTH))
    html = html.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    return html


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Root シミュレーション可視化ダッシュボード(DESIGN.md 10.5)")
    parser.add_argument("--db", type=str, default="simulation/results.sqlite")
    parser.add_argument("--runs", type=str, default=None,
                         help="カンマ区切りの run_id(省略時は全run)")
    parser.add_argument("-o", "--output", type=str, default="simulation/dashboard.html")
    args = parser.parse_args(argv)

    conn = sqlite3.connect(args.db)
    try:
        run_ids = _resolve_run_ids(conn, args.runs)
        if not run_ids:
            print("runs テーブルが空です(先に simulation.runner を実行してください)")
            return 1
        data = build_dashboard_data(conn, run_ids)
    finally:
        conn.close()

    html = render_html(data)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print("dashboard: %s (runs=%s)" % (args.output, ",".join(str(r) for r in run_ids)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
