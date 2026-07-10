"""engine/selftest.py の各シナリオを pytest から実行する薄いラッパー。

selftest.py 側の ``test_*`` 関数を個別 import して別名でラップする。
``from engine.selftest import *`` すると pytest が engine 側の関数を二重収集して
しまうため、明示的に1つずつラップする方式を採る。

カバー範囲(9.3 で「selftest 済みのためラッパーでカバー」と指定されたものを含む):
  戦闘 pending(4.3) / 奇襲(4.3.1) / 内乱(7.7)・新世代(7.7.3.I) /
  蜂起=憤慨(8.2.6) / 反乱(8.4.1) / 拠点除去連鎖(8.2.4) / ゲリラ戦(8.2.2)
"""
from __future__ import annotations

from engine.selftest import (
    test_ambush_via_pending as _ambush_via_pending,
    test_base_removed as _base_removed,
    test_battle_via_pending as _battle_via_pending,
    test_eyrie_turmoil as _eyrie_turmoil,
    test_eyrie_turmoil_new_generation as _eyrie_turmoil_new_generation,
    test_guerrilla_dice as _guerrilla_dice,
    test_outrage_auto_draw as _outrage_auto_draw,
    test_outrage_pay_from_hand as _outrage_pay_from_hand,
    test_revolt as _revolt,
)


def test_battle_via_pending():
    _battle_via_pending()


def test_ambush_via_pending():
    _ambush_via_pending()


def test_eyrie_turmoil():
    _eyrie_turmoil()


def test_eyrie_turmoil_new_generation():
    _eyrie_turmoil_new_generation()


def test_outrage_pay_from_hand():
    _outrage_pay_from_hand()


def test_outrage_auto_draw():
    _outrage_auto_draw()


def test_revolt():
    _revolt()


def test_base_removed():
    _base_removed()


def test_guerrilla_dice():
    _guerrilla_dice()
