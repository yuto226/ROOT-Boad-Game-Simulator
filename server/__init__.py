"""対局を都度生成する観戦APIサーバ(フェーズ7後半)。

``tools/record_game.py`` の部品(``run_and_record`` / ``build_output`` /
``make_policy``)を再利用し、FastAPI 経由でオンデマンドに対局を実行して
``ui/viewer.html`` と同じスキーマの JSON を返す。engine/rl/tools/ui は
一切変更せず import のみで利用する。
"""
