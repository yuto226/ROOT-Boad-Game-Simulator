"""RL 環境ラッパー(フェーズ6a, DESIGN.md 12章)。

- ``catalog`` : 固定インデックス行動空間+合法手マスク(numpy 不要)。
- ``encoder`` / ``env`` : 観測エンコーダと AEC 互換環境(numpy 必須)。

numpy 未導入環境でも ``rl.catalog`` は使えるよう、encoder/env の import は
遅延・任意にする(numpy が無ければ ObservationSpec/encode/RootEnv は None)。
"""
from __future__ import annotations

from .catalog import (
    ActionCatalog,
    action_for,
    action_key,
    legal_mask,
)

try:  # numpy が無い環境では encoder/env を無効化する(12.1)
    from .encoder import ObservationSpec, encode
    from .env import RootEnv
except ImportError:  # pragma: no cover - numpy 未導入時のみ
    ObservationSpec = None  # type: ignore
    encode = None  # type: ignore
    RootEnv = None  # type: ignore

__all__ = [
    "ActionCatalog",
    "action_key",
    "legal_mask",
    "action_for",
    "ObservationSpec",
    "encode",
    "RootEnv",
]
