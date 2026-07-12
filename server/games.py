"""対局の都度生成+プロセス内メモリ保持。

現時点では「1リクエストで最初から最後まで自動対局を実行し、その記録を
返す」機能のみを持つ。セッション機構は持たない。

拡張点: 人間 vs bot を1手ずつ進める場合はここに進行中セッション(state,
次の合法手)を保持する仕組みを追加し、create_session/step_session を
別途用意する。現時点ではそうした逐次進行の仕組みは存在しない。
"""
from __future__ import annotations

import collections
import uuid
from typing import Dict, List, Optional

from engine.types import FactionId
from tools.record_game import build_output, run_and_record

from server.policies import make_policy

_MAX_GAMES = 32

# game_id -> record({"meta":..., "map":..., "steps":...})。挿入順を保持し、
# 上限を超えたら最も古いものをFIFOで破棄する(単純なプロセス内キャッシュ)。
_games: "collections.OrderedDict[str, dict]" = collections.OrderedDict()


def create_game(factions: List[str], policies: List[str], seed: int = 0,
                max_turns: int = 300) -> dict:
    """対局を1本実行し、生成した record をメモリに保持して返す。

    factions/policies の要素数が不一致、未知の faction 文字列、未知の
    policy 指定形式のいずれも ValueError が自然に飛ぶ(呼び出し元で
    捕捉してHTTPエラーに変換する想定)。
    """
    if len(factions) != len(policies):
        raise ValueError(
            "factions の要素数(%d)と policies の要素数(%d)が一致しない"
            % (len(factions), len(policies)))

    faction_ids = tuple(FactionId(v) for v in factions)
    policy_objs = {f: make_policy(spec) for f, spec in zip(faction_ids, policies)}

    result, steps = run_and_record(faction_ids, policy_objs, seed, max_turns)
    record = build_output(faction_ids, list(policies), seed, max_turns, result, steps)

    game_id = uuid.uuid4().hex[:8]
    _games[game_id] = record
    if len(_games) > _MAX_GAMES:
        _games.popitem(last=False)  # 挿入順で最も古いものを破棄(FIFO)

    return {"game_id": game_id, "record": record}


def get_game(game_id: str) -> Optional[dict]:
    """保持している record を返す(無ければ None)。"""
    return _games.get(game_id)


def list_games() -> List[dict]:
    """保持している対局の概要一覧を返す。"""
    return [{"game_id": gid, "meta": record["meta"]} for gid, record in _games.items()]
