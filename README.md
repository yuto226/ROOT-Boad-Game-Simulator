# ROOT Board Game Simulator

ボードゲーム [ROOT](https://ledergames.com/products/root-a-game-of-woodland-might-and-right)(Leder Games)の非対称4派閥対戦を Python でシミュレートし、大量の自己対戦から勝率・ゲームバランスを統計的に検証するためのプロジェクト。

ルールの典拠は公式ルールブック「[Law of Root 日本語版 2023Dec](https://arclightgames.jp/wp-content/uploads/2024/01/Law-of-Root_JPN-full-2023Dec.pdf)」(アークライトゲームズ)。実装コードの docstring には原文のルール番号(例: `7.5.2`)を併記し、`rules/` の構造化テキストまでトレーサビリティを確保している。

## プロジェクトの目的

1. **ルール完全準拠のゲームエンジン**を作る(合法手列挙 → アクション適用 → 状態遷移)
2. その上で**ランダム/ヒューリスティックbotの大量自己対戦**を回す
3. 勝率・ターン数などを集計して**派閥バランスや戦略の統計検証**を行う
4. (将来)MCTS/強化学習エージェントや観戦UIを載せる

## 現在の進捗(フェーズ1進行中)

| 派閥 | 状態 |
|---|---|
| 猫野侯国(Marquise de Cat) | ✅ 実装済み(一部簡略化あり、ロードマップ参照) |
| 鷲巣王朝(Eyrie Dynasties) | ✅ 実装済み(勅令・内乱・君主4種・森の王者・商業軽視) |
| 森林連合(Woodland Alliance) | ✅ 実装済み(反乱・支持拡大・蜂起・ゲリラ戦・作戦行動) |
| 放浪部族(Vagabond) | 🚧 未実装(次セッション予定) |

- 秋マップ(12広場)・山札54枚・派閥ボード数列は公式コンポーネントから確定済み(`rules/data-verification.md`)
- 2〜3派閥のランダムbot対戦がクラッシュゼロで最後まで回ることを確認済み
- 未実装の共通ルール: 圧倒(支配)カード(3.3)、城砦の配置禁止(6.2.2)、item以外のクラフト効果(immediate/persistent)

詳細な進捗・既知の簡略化・セッション引き継ぎメモは [`root-simulator-roadmap.md`](root-simulator-roadmap.md) を参照。

## 使い方

Python 3.11+(標準ライブラリのみ、外部依存なし)。

### スモークテスト(ランダムbot対戦)

```bash
# 猫ソロ 20試合(既定)
python3 -m sim.smoke --games 20 --seed 0

# 2人戦: 猫 vs 鷲巣
python3 -m sim.smoke --games 30 --seed 0 --factions marquise,eyrie

# 3人戦: 猫 + 鷲巣 + 森林連合
python3 -m sim.smoke --games 30 --seed 0 --factions marquise,eyrie,alliance
```

出力例:

```
game  0 seed=300: turns= 34 vp[marquise=12 eyrie=9 alliance=30] WIN:alliance
...
games=30 wins[marquise=0 eyrie=0 alliance=30] timeouts=0
turns: min=26 avg=33.9 max=47
```

勝利条件は30VP到達(3.1)。`--max-turns`(既定300)超過は timeout(引き分け)として記録される。同一シードで結果は完全に再現可能。

### セルフテスト(ルール検証シナリオ)

```bash
python3 -m engine.selftest
```

戦闘の4ステップ・奇襲・鷲巣の内乱(恥辱/追放/失脚/休止)・連合の蜂起/反乱/拠点除去/ゲリラ戦などの固定シナリオを検証する。

### コードからの利用

```python
import random
from engine.game import run_game
from engine.types import FactionId
from bots.random_bot import RandomBot

bot = RandomBot()
result = run_game(
    factions=(FactionId.MARQUISE, FactionId.ALLIANCE),
    policies={FactionId.MARQUISE: bot, FactionId.ALLIANCE: bot},
    seed=42,
)
print(result.winner, result.turns, result.vps)
```

botは `bots/base.py` の `Policy` プロトコル(`choose(state, legal_actions, rng) -> Action`)を満たせば差し替え可能。

## ディレクトリ構成

```
rules/       構造化ルールテキスト(フェーズ0の成果物。原文ルール番号併記)
  common.md    共通ルール(第1〜5章: 勝利条件・移動・戦闘・クラフト等)
  cat.md       猫野侯国(第6章)
  birds.md     鷲巣王朝(第7章)
  woodland.md  森林連合(第8章)
  vagabond.md  放浪部族(第9章)
  data-verification.md  盤面印刷データ(マップ・派閥ボード数列)の検証記録
engine/      コアエンジン(フェーズ1)
  DESIGN.md    設計書(イミュータブル状態・保留デシジョンスタック等の設計判断)
  state.py     GameState / 派閥別状態(すべて frozen dataclass)
  actions.py   アクションとデシジョンの型定義
  legal.py     合法手列挙
  apply.py     アクション適用(型ディスパッチ)
  battle.py    戦闘サブシステム(派閥の読み替えフック込み)
  crafting.py  クラフト共通処理
  game.py      セットアップ・ターン進行・対戦ループ
  factions/    派閥ロジック(marquise / eyrie / alliance / vagabond)
  data/        マップ・カード・派閥ボードの静的データ(JSON)
  selftest.py  ルール検証シナリオ
bots/        bot実装(Policyプロトコル + ランダムbot)
sim/         対戦ランナー(smoke)
tools/       ルールブックPDFの抽出スクリプト
docs/        ルールブックPDF等のローカル資料(git管理外)
```

## 設計の要点(engine/DESIGN.md より)

- **イミュータブル状態**: `GameState` は frozen dataclass。`apply(state, action, rng) -> GameState` は入力を変更しない。乱数は注入式で、同一シードなら完全再現(将来のMCTSを見据えた設計)
- **保留デシジョンスタック**: 1アクションの内部に他プレイヤーの選択が挟まるROOT特有の構造(奇襲・ヒット割り振り・蜂起など)を、`pending` スタックで統一的に処理
- **派閥ロジックの境界**: 共通アクションの本体はエンジン側、派閥モジュールは「いつ・何回・どのコストで使えるか」だけを差す。派閥固有の読み替え(ゲリラ戦・森の王者など)はエンジン側のフック点で吸収

## 今後のロードマップ(未実装)

| フェーズ | 内容 | 状態 |
|---|---|---|
| 0 | ルール構造化(基本4派閥) | ✅ 完了 |
| 1 | コアエンジン + 4派閥ロジック | 🚧 放浪部族が残 |
| 2 | テスト・検証基盤(pytest、1000戦スモーク) | 未着手 |
| 3 | 統計基盤(並列実行・SQLite/Parquet・集計/可視化) | 未着手 |
| 4 | ヒューリスティックbot(派閥別評価関数) | 未着手 |
| 5 | 4派閥フル対戦の統合検証 | 未着手 |
| 6 | (任意)MCTS / 強化学習 | 未着手 |
| 7 | (任意)観戦・対人UI(FastAPI) | 未着手 |

※ 現状のランダムbot同士の勝率(例: 3人戦で森林連合が圧勝)はbotの質を反映したものであり、派閥バランスの結論ではない。意味のあるバランス検証はフェーズ4以降。

## 開発の進め方

セッション分割・モデル運用・引き継ぎのルールは `CLAUDE.md` と `root-simulator-roadmap.md` に記載。拡張派閥(蜥蜴教団・河民商団など)・冬マップは当面スコープ外。

## ライセンス・出典

- ROOT は Leder Games の作品(日本語版はアークライトゲームズ)。本リポジトリは個人のルール研究・シミュレーション目的であり、ゲーム本体の素材(アートワーク等)は含まない。
- `engine/data/` のカード・マップデータは公式ルールブックおよび実物コンポーネントからの転記。
