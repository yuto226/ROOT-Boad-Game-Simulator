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
| R | ルール完全性(既知の簡略化の解消) | 🚧 A・B完了、C〜D残 |
| 6 | 強化学習(PPO self-play) | 🚧 6a完了・6c前半完了、6b/6c後半残 |
| 7 | UI接続(観戦・対人) | 未着手(任意) |

**DESIGN.md 章マップ**: 3=コア設計(3.1決定性・3.2 pendingスタック)/8=放浪部族/9=テスト基盤/10=runner+SQLite(10.2 決定性制約)/11=ヒューリスティックbot/12=RL環境ラッパー/13=PPO学習/14=圧倒カード+共闘軍

**完了フェーズの恒常メモ**:
- GitHubリモート: git@github.com:yuto226/ROOT-Boad-Game-Simulator.git(main)。`docs/`(ルールブックPDF等)はgit管理外、消えたら `tools/extract_rulebook.py` で再生成(URLはCLAUDE.md)
- テスト実行: `python3 -m pytest tests/ -q`(67 passed + 3 skipped。skip=torch必要テスト)
- bot勝率の参考値(バランスの結論ではない): ランダム4派閥=連合圧勝 → 全heuristic 3派閥=猫48.5%/連合51.5%(鷲巣とvagabondのheuristicは弱い。1-plyの原理的限界、RLで解決の方向)

---

## フェーズR: ルール完全性(2026-07-11 ユーザー決定。フェーズ6と並行、余剰トークンで進める)

**目的**: 既知の簡略化を解消し、バランス統計検証の信頼性を上げる。

- [x] **A: 圧倒カード(3.3)+共闘軍(9.2.8)** — 2026-07-11完了(bd83beb+5247e50)。設計=DESIGN.md **14章**。VP凍結の中央集約(mechanics.award_vp)・捨て山リダイレクト(to_discard)・昼光共通フック・鳥歌開始時の圧倒勝利判定・winners(共闘の共同勝利)。rl/はcatalog v2(size 8052、CATALOG_VERSION導入)。500試合ランダム4派閥で圧倒勝利157・共闘勝利84を確認
- [x] **B: 猫の簡略化バッチ** — 2026-07-11完了。設計=DESIGN.md **15章**。行軍2移動(6.5.2、MarquiseMarchDecision+SkipMove)/野戦病院(6.2.3、イベント単位集計・反乱と狙撃にも適用)/城砦の配置禁止(6.2.2、placement_blocked。xfailは誤読につき正テスト2本に差し替え)/奇襲2ヒットの除去対象選択(4.3.1.II、_finish_allocationに継続処理を統合)。rl/はcatalog v3(size 8096)。ランダム4派閥100戦で行軍2移動目3168回(移動92.2%)・野戦病院709回(発動58.1%)
- [x] **C: immediate/persistentクラフト効果** — 2026-07-12完了(b9b48c5)。設計=DESIGN.md **18章**。13種(Codebreakersは完全情報ゆえ除外、Scouting Party追加)。戦闘の4.3.3効果ステージ新設/Favorはremove_piece共通経路/フェイズ効果は「フェイズ中いつでも1回」に緩和(明記)。rl: catalog v4(size 8129)+観測に継続効果multi-hot。200試合でクラフト1318回・効果使用3741回
- [x] **D第1弾: 支払い選択のデシジョン化** — 2026-07-12完了(feature/d1-catalog-v5ブランチ、設計=DESIGN.md **19章**)。木材支払い広場選択/連合の支援者支払い選択/部族の援助アイテム選択・隠れ家修理選択。**catalog v5(size 8161)**。マージはGPU学習(v4 ckpt)の評価・観戦が一段落してから
- [ ] **D残り(catalog非影響)**: 工房ごとクラフト(仕様=19.6、ユーザー確認済みの例あり)/鷲巣クラフトany割当/戒厳令(8.4.2.II.a)の解釈確認/(見送り)同盟の同時移動・攻撃・肩代わり(9.2.9.II.b〜d)

**引き継ぎメモ**:
> - A完了によりゲームの終わり方の分布が変わった(勝利手段3種)。以後のバランス統計はこの実装前提で読む。gamesテーブルに勝因列は未追加、共闘の共同勝利もDB未記録(winner=主勝者のみ)=既知の割り切り
> - Cの実装時は、新アクション追加なら rl/catalog.py の追随(キー追加+CATALOG_VERSION増分)とencoderの観測追加をセットで行うこと(A=5247e50、B=15.5が手本)
> - B完了によりcatalog v3(size 8096)。v2以前のRL ckptとは非互換(resume時にCATALOG_VERSIONで検出される)

---

## フェーズ6: 強化学習(RL)層(2026-07-10 構想確定)

**目的**: PPO self-playで学習したbotを載せる。学習はWindows機(RTX 4080 Super)のDocker環境、MacからSSH制御。

**方針(ユーザー合意)**: PPO+合法手マスク/まず2人戦固定(猫vs鷲巣)・完全情報/エンジンは標準ライブラリのみ維持(torch等は分離)/エンジン速度が律速になったらホットパスのRust/C++移植を検討(`legal_actions`/`apply` のインターフェースと決定性制約=DESIGN.md 10.2が仕様書)

### 6a: RL環境ラッパー — ✅ 完了(2026-07-11, ebc2d46)
`rl/catalog.py`(固定行動空間、正準キー方式)+`rl/encoder.py`(完全情報・perspective onehot)+`rl/env.py`(AEC互換・pettingzoo非依存)+`pyproject.toml`。設計=DESIGN.md 12章。

### 6b: Windows側の学習環境構築 — 🚧 疎通確認まで完了(2026-07-11)
- [x] Dockerfile/compose/セットアップ手順書(`docker/`。detached起動でSSH切断耐性)
- [x] Windows実機の疎通: WSL2(Ubuntu)+Docker Desktop統合+GPUコンテナで nvidia-smi 確認(RTX 4080 Super/CUDA 13.1)+Tailscale+SSH鍵認証(ハマりどころは docker/README.md 5章に追記)
- [ ] リポジトリclone → `docker compose build` → 学習ジョブ投入(手順は `docker/README.md`)
- [ ] 学習曲線の監視方法の確定(まずは log.csv の tail。W&B/TBは必要になってから)

### 6c: PPO self-play学習 — 🚧 前半(コード+Mac検証)完了
- [x] 学習コード一式(80b4f2a): `rl/net.py`+`rl/ppo.py`+`rl/nn_policy.py`(既存run_gameで評価)+`rl/train.py`/`rl/eval.py`。設計=DESIGN.md 13章
- [x] Mac CPUで50万ステップ検証(下記結果)
- [ ] 10⁷ステップ規模のGPU学習(6b完了後)
- [x] self-playの非定常対策(過去世代とのリーグ戦)— ✅ 実装完了(2026-07-11。DESIGN.md 16章)→ スケールアップ判断はGPU学習後

**引き継ぎメモ**:
> - 実行環境: torchはリポジトリ直下 `.venv/`(gitignore)。`.venv/bin/python -m rl.train --total-steps N --run-name X`。出力は `rl_runs/<run名>/`(log.csv+eval.csv+ckpt、gitignore)。CPUが既定(約1350steps/s、MPSより速い)
> - Windows機への接続: `ssh <user>@<tailscale名>`(実値はリポジトリに書かない。Claudeのローカルメモリに記録済み)。Mac の鍵で鍵認証設定済み。リモート実行は `ssh <user>@<host> "wsl -d Ubuntu -e bash -lc \"<cmd>\""` の形(cmd.exe経由なので**内側はダブルクォート**、シングルは通らない)
> - 次セッションの最初の作業: WSL2のUbuntu内で git clone(SSH鍵の用意 or HTTPSで)→ `docker compose -f docker/compose.yaml build` → 学習ジョブ投入
> - RL ckpt互換性: フェーズR-B完了で catalog v3(size 8096)。旧ckptからのresumeは不可(CATALOG_VERSIONで検出)
> - **Mac 50万ステップの結果(rl_runs/mac-500k、猫vs鷲巣)**: entropy 2.39→1.04・KL安定。vs RandomBot=猫席100%/鷲巣席96.9%。vs HeuristicBot=**猫席96.9〜100%**(フェーズ4 botに圧勝)/鷲巣席0〜12.5%。self-playが猫に偏り鷲巣の学習信号が薄い=リーグ戦・shaping・スケールで対処予定
> - **ckpt非互換に注意**: R-C完了で catalog v4(size 8129)。v3以前のckpt(GPU学習をv3で回した場合を含む)はresume・nn観戦不可(CATALOG_VERSIONで明示エラー)。v3のckptを使いたい場合は b9b48c5 より前をcheckoutする
> - **リーグ戦実装済み(2026-07-11、DESIGN.md 16章)**: `rl/league.py`(OpponentPool)+ppo/train拡張。`--league-prob`(既定0.5、0で従来の純self-play)/`--league-pool-max`(既定20)/`--league-snapshot-every`(既定20更新)。log.csvに league_episodes/league_winrate 列が増えた(旧runのlog.csvとは列非互換)。winrate_seat0/1 は self-playエピソードのみの集計。スナップショットは `rl_runs/<run>/league/snap_*.pt`(間引き時はファイルも削除)、resume時はckptの league_meta から再構築(欠損はwarn+skip)。league有効時のスループットは約4〜5割低下(凍結ネット推論の分)
> - 次の作業: GPU学習(6bの残り=clone+build+ジョブ投入 → 10⁷ステップをリーグ戦有効で回す)

---

## フェーズ7(将来・任意): UI接続

- [x] 観戦モード — ✅ 完了(2026-07-11、DESIGN.md 17章)。サーバ不要の2点構成:
  `tools/record_game.py`(対局→JSON。policy指定 random/heuristic/nn:<ckpt>[:sample])+
  `ui/viewer.html`(自己完結単一HTML。file://で開き game.json を読み込む)。
  使い方例: `python3 -m tools.record_game --factions marquise,eyrie --policies nn:rl_runs/gpu-10m/ckpt_400.pt,heuristic --seed 0 -o ui/game.json` → `open ui/viewer.html`
- [ ] FastAPI等でエンジンをAPI化(観戦はAPI不要で実現済み。人間vs CPUをやる段で導入判断)
- [ ] (任意)人間 vs CPU対戦モード

---

## 運用ルール(セッションをまたぐときのチェックリスト)

1. このロードマップの進捗・引き継ぎメモを最新化してからセッションを終える
2. 新セッションは「このロードマップ+該当フェーズのDESIGN.md章」を読んで再開する
3. 詰まった点・次にやりたいことはユーザーが一言添える
