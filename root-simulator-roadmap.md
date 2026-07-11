# Root シミュレーター開発ロードマップ

## 進め方の方針

- **1フェーズ = 1〜2セッションの粒度**で進め、**セッションの区切りで必ずユーザーにコントロールを戻す**(一気通貫で進めない。トークンコントロールのため)
- 各セッションの終わりに、このファイルの進捗と「引き継ぎメモ」を更新する。**完了したフェーズの作業経緯は書き残さない**(git履歴とコミットメッセージが正)。残すのは「次のセッションが必要とする情報」だけ
- 情報の置き場所: 設計判断=`engine/DESIGN.md`(章マップは下記)/ルール根拠=`rules/*.md`(原文番号併記)/盤面データの検証記録=`rules/data-verification.md`/使い方=`README.md`
- モデル運用は `CLAUDE.md` 参照(設計・レビュー=Fable直接、実装=Sonnet/Opus subagent)

## 全体状況(2026-07-11時点)

| フェーズ | 内容 | 状態 |
|---|---|---|
| 0 | ルール構造化(基本4派閥) | ✅ 完了 |
| 1 | コアエンジン+3派閥(猫・鷲巣・連合) | ✅ 完了 |
| 2 | テスト・検証基盤(pytest・不変量・1000戦スモーク) | ✅ 完了 |
| 3 | 統計基盤(並列runner・SQLite・report・dashboard) | ✅ 完了 |
| 4 | ヒューリスティックbot(1手先読みgreedy+派閥別評価関数) | ✅ 完了 |
| 5 | 放浪部族の追加(実装+レビュー+テスト+評価関数) | ✅ 完了 |
| R | ルール完全性(既知の簡略化の解消) | 🚧 A完了、B〜D残 |
| 6 | 強化学習(PPO self-play) | 🚧 6a完了・6c前半完了、6b/6c後半残 |
| 7 | UI接続(観戦・対人) | 未着手(任意) |

**DESIGN.md 章マップ**: 3=コア設計(3.1決定性・3.2 pendingスタック)/8=放浪部族/9=テスト基盤/10=runner+SQLite(10.2 決定性制約)/11=ヒューリスティックbot/12=RL環境ラッパー/13=PPO学習/14=圧倒カード+共闘軍

**完了フェーズの恒常メモ**:
- GitHubリモート: git@github.com:yuto226/ROOT-Boad-Game-Simulator.git(main)。`docs/`(ルールブックPDF等)はgit管理外、消えたら `tools/extract_rulebook.py` で再生成(URLはCLAUDE.md)
- テスト実行: `python3 -m pytest tests/ -q`(65 passed + 3 skipped + 1 xfailed。xfail=城砦6.2.2、フェーズR-Bで解除予定。skip=torch必要テスト)
- bot勝率の参考値(バランスの結論ではない): ランダム4派閥=連合圧勝 → 全heuristic 3派閥=猫48.5%/連合51.5%(鷲巣とvagabondのheuristicは弱い。1-plyの原理的限界、RLで解決の方向)

---

## フェーズR: ルール完全性(2026-07-11 ユーザー決定。フェーズ6と並行、余剰トークンで進める)

**目的**: 既知の簡略化を解消し、バランス統計検証の信頼性を上げる。

- [x] **A: 圧倒カード(3.3)+共闘軍(9.2.8)** — 2026-07-11完了(bd83beb+5247e50)。設計=DESIGN.md **14章**。VP凍結の中央集約(mechanics.award_vp)・捨て山リダイレクト(to_discard)・昼光共通フック・鳥歌開始時の圧倒勝利判定・winners(共闘の共同勝利)。rl/はcatalog v2(size 8052、CATALOG_VERSION導入)。500試合ランダム4派閥で圧倒勝利157・共闘勝利84を確認
- [ ] **B: 猫の簡略化バッチ** — 行軍2移動(6.5.2)/野戦病院(6.2.3)/城砦の配置禁止(6.2.2、xfail解除)/奇襲2ヒットの除去対象選択
- [ ] **C: immediate/persistentクラフト効果** — ホワイトリスト方式(DESIGN.md 3.7)。Armorers/Sappers/Brutal Tactics/Royal Claim/Command Warren/Better Burrow Bank/Cobbler/Codebreakers/Stand and Deliver!/Tax Collector/Favor×3
- [ ] **D(任意): 細部** — 猫の木材支払い広場選択/工房プールの1ターン1クラフト制限/鷲巣クラフトany割当/連合の支援者支払い選択・戒厳令(8.4.2.II.a)の解釈確認/部族の_pay_any・隠れ家自動選択/同盟の同時移動・攻撃・肩代わり(9.2.9.II.b〜d)

**引き継ぎメモ**:
> - A完了によりゲームの終わり方の分布が変わった(勝利手段3種)。以後のバランス統計はこの実装前提で読む。gamesテーブルに勝因列は未追加、共闘の共同勝利もDB未記録(winner=主勝者のみ)=既知の割り切り
> - B/Cの実装時は、新アクション追加なら rl/catalog.py の追随(キー追加+CATALOG_VERSION増分)とencoderの観測追加をセットで行うこと(Aのコミット 5247e50 が手本)

---

## フェーズ6: 強化学習(RL)層(2026-07-10 構想確定)

**目的**: PPO self-playで学習したbotを載せる。学習はWindows機(RTX 4080 Super)のDocker環境、MacからSSH制御。

**方針(ユーザー合意)**: PPO+合法手マスク/まず2人戦固定(猫vs鷲巣)・完全情報/エンジンは標準ライブラリのみ維持(torch等は分離)/エンジン速度が律速になったらホットパスのRust/C++移植を検討(`legal_actions`/`apply` のインターフェースと決定性制約=DESIGN.md 10.2が仕様書)

### 6a: RL環境ラッパー — ✅ 完了(2026-07-11, ebc2d46)
`rl/catalog.py`(固定行動空間、正準キー方式)+`rl/encoder.py`(完全情報・perspective onehot)+`rl/env.py`(AEC互換・pettingzoo非依存)+`pyproject.toml`。設計=DESIGN.md 12章。

### 6b: Windows側の学習環境構築 — 🚧 定義済み・実機セットアップ残
- [x] Dockerfile/compose/セットアップ手順書(`docker/`。detached起動でSSH切断耐性)
- [ ] Windows実機: WSL2+Docker Desktop+GPU確認 → Tailscale+SSH → `docker compose build` → 学習ジョブ投入(手順は `docker/README.md`)
- [ ] 学習曲線の監視方法の確定(まずは log.csv の tail。W&B/TBは必要になってから)

### 6c: PPO self-play学習 — 🚧 前半(コード+Mac検証)完了
- [x] 学習コード一式(80b4f2a): `rl/net.py`+`rl/ppo.py`+`rl/nn_policy.py`(既存run_gameで評価)+`rl/train.py`/`rl/eval.py`。設計=DESIGN.md 13章
- [x] Mac CPUで50万ステップ検証(下記結果)
- [ ] 10⁷ステップ規模のGPU学習(6b完了後)
- [ ] self-playの非定常対策(過去世代とのリーグ戦)→ スケールアップ判断

**引き継ぎメモ**:
> - 実行環境: torchはリポジトリ直下 `.venv/`(gitignore)。`.venv/bin/python -m rl.train --total-steps N --run-name X`。出力は `rl_runs/<run名>/`(log.csv+eval.csv+ckpt、gitignore)。CPUが既定(約1350steps/s、MPSより速い)
> - **Mac 50万ステップの結果(rl_runs/mac-500k、猫vs鷲巣)**: entropy 2.39→1.04・KL安定。vs RandomBot=猫席100%/鷲巣席96.9%。vs HeuristicBot=**猫席96.9〜100%**(フェーズ4 botに圧勝)/鷲巣席0〜12.5%。self-playが猫に偏り鷲巣の学習信号が薄い=リーグ戦・shaping・スケールで対処予定
> - **ckpt非互換に注意**: catalog v2(圧倒カード対応)で行動空間が8052になり、旧ckpt(mac-500k)はresume不可(明示エラーが出る)。GPU学習はv2で新規に回す
> - 次の作業候補: (1)6bのWindows実機セットアップ(ユーザー作業主体) (2)リーグ戦の設計・実装(Macで完結可能)

---

## フェーズ7(将来・任意): UI接続

- [ ] FastAPI等でエンジンをAPI化
- [ ] Action履歴を1手ずつ流し込む観戦モードUI
- [ ] (任意)人間 vs CPU対戦モード

---

## 運用ルール(セッションをまたぐときのチェックリスト)

1. このロードマップの進捗・引き継ぎメモを最新化してからセッションを終える
2. 新セッションは「このロードマップ+該当フェーズのDESIGN.md章」を読んで再開する
3. 詰まった点・次にやりたいことはユーザーが一言添える
