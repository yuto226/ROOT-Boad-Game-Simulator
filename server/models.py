"""学習済みチェックポイント一覧の走査。

``ROOT_SIM_RUNS`` 環境変数(既定 ``rl_runs``)配下の ``<run>/ckpt_<N>.pt`` を
glob して一覧化するだけ。torch は使わない(ファイル名とmtime/sizeのみ)。
"""
from __future__ import annotations

import glob
import os
import re
from datetime import datetime, timezone
from typing import List, Optional

_CKPT_RE = re.compile(r"^ckpt_(\d+)\.pt$")


def list_models(runs_dir: Optional[str] = None) -> List[dict]:
    """``<runs_dir>/*/ckpt_*.pt`` を走査し update 降順で返す。

    ``runs_dir`` が None なら環境変数 ``ROOT_SIM_RUNS``(既定 "rl_runs")を使う。
    ``ckpt_<N>.pt`` の N をパースできないファイルはスキップする。
    """
    if runs_dir is None:
        runs_dir = os.environ.get("ROOT_SIM_RUNS", "rl_runs")

    entries: List[dict] = []
    for path in glob.glob(os.path.join(runs_dir, "*", "ckpt_*.pt")):
        m = _CKPT_RE.match(os.path.basename(path))
        if not m:
            continue
        update = int(m.group(1))
        run = os.path.basename(os.path.dirname(path))
        stat = os.stat(path)
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        entries.append({
            "run": run,
            "update": update,
            "path": path,
            "mtime": mtime,
            "size_bytes": stat.st_size,
        })

    entries.sort(key=lambda e: e["update"], reverse=True)
    return entries
