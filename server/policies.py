"""policy 指定文字列から Policy インスタンスを作る。

``tools/record_game.py`` の ``make_policy`` と同じ意味(random / heuristic /
nn:<ckptパス>[:sample])だが、``nn:`` policy についてはチェックポイント単位で
ネット・spec・catalog をキャッシュする(観戦APIは短時間に同じckptで複数対局を
生成し得るため、毎回 torch.load するのは無駄が大きい)。torch import は
``nn:`` 使用時までモジュールトップレベルでは行わない。
"""
from __future__ import annotations

import functools
from typing import Tuple

from bots.heuristic import HeuristicBot
from bots.random_bot import RandomBot


@functools.lru_cache(maxsize=4)
def _load_nn_components(ckpt_path: str, device_name: str) -> Tuple[object, object, object, object]:
    """(net, spec, catalog, device) を ckptパス+device単位でキャッシュする。"""
    from rl.eval import load_checkpoint, select_device  # 遅延import(torch依存)

    device = select_device(device_name)
    net, spec, catalog, _factions, _meta = load_checkpoint(ckpt_path, device)
    return net, spec, catalog, device


def make_policy(spec: str, device_name: str = "auto"):
    """policy 指定文字列から Policy インスタンスを作る。

    random / heuristic / nn:<ckptパス>[:sample](既定 greedy)。
    ``NNPolicy`` インスタンス自体はキャッシュしない(greedy/sample切替や
    将来の並行対局のため状態を共有しない)。ネット本体のロードのみキャッシュする。
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
        from rl.nn_policy import NNPolicy  # 遅延import(torch依存)

        net, obs_spec, catalog, device = _load_nn_components(rest, device_name)
        return NNPolicy(net, obs_spec, catalog, device, greedy=not sample)
    raise ValueError(
        "未知の policy 指定: %r(random / heuristic / nn:<ckpt>[:sample])" % spec)
