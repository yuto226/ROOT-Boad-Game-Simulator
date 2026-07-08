# Root シミュレーションプロジェクト

ボードゲーム ROOT のシミュレーションプロジェクト。
公式ルールブック(Law of Root 日本語版 2023Dec):
https://arclightgames.jp/wp-content/uploads/2024/01/Law-of-Root_JPN-full-2023Dec.pdf
(ローカルコピー: `docs/law-of-root-jpn.pdf`、gitには含めない)

## 進行の基礎ルール(ユーザー指示・厳守)

### モデル運用
- **Fable 5**: 設計・アーキテクチャ検討・横断レビューを直接担当する。subagentに委譲しない。
- **実装**: Sonnetのsubagentをメインに、難易度の高い実装のみOpusのsubagentが補助する
  (Agentツールの `model` パラメータで指定)。
- トークン消費が激しいことが予想されるため、上記の役割分担を厳守すること。

### フェーズ・セッション運用
- `root-simulator-roadmap.md` に定義されたフェーズとセッション区切りを厳守する。
- **一気通貫で進めない**。トークンコントロールが破綻するため。
- **必ずセッションの区切りで一度ユーザーにコントロールを戻す**こと。
- 各セッションの終わりにロードマップの進捗チェックボックスと「引き継ぎメモ」を更新する。

### Git運用
- 特別なルールは設けない。適宜コミットする。

## ディレクトリ構成(ロードマップ準拠)
- `rules/` — フェーズ0: 構造化ルールmd(common / cat / birds / woodland など)
- `engine/` — フェーズ1: コアエンジン(Pythonパッケージ)
- `tests/` — フェーズ2: pytest
- `simulation/` — フェーズ3: 並列対戦ランナー
- `analysis/` — フェーズ3: 集計・可視化
- `bots/` — フェーズ4: ヒューリスティックbot
