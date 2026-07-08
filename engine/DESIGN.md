# コアエンジン設計書(フェーズ1)

作成: Fable 5(設計担当)。実装者(subagent)はこの設計に従うこと。
ルールの根拠はすべて `rules/*.md` にあり、原文番号(例: 4.3.2)で参照する。

## 0. ゴールと非ゴール

- **ゴール**: 基本4派閥(猫野侯国・鷲巣王朝・森林連合・放浪部族)で「合法手列挙 → アクション適用 → 状態遷移」が回り、ランダムbotだけで1試合が必ず終了する(勝者確定 or 安全弁ターン上限)。
- **非ゴール(フェーズ1では扱わない)**: 拡張派閥、冬マップ、UI、強いAI。ただし後のMCTS/RL(フェーズ6)を見据え、Policyが差し替え可能な形にする。
- 2〜4人戦をサポート。派閥の組み合わせは任意(同一派閥の重複は不可)。2人戦では圧倒カード4枚を山札から除く(5.1.3)。

## 1. 技術方針

- Python 3.11+、**標準ライブラリのみ**(dataclasses / enum / typing / random / json)。
- 型ヒント必須。`from __future__ import annotations`。
- 静的データ(マップ・カード・派閥ボード数列)はコードから分離し `engine/data/` に置く。

## 2. ディレクトリ構成

```
engine/
  __init__.py
  types.py          # Suit, FactionId, Phase, ItemKind などの enum と小型値オブジェクト
  board.py          # MapData(静的): Clearing, Forest, 隣接, 遺跡位置。data/map_autumn.json をロード
  cards.py          # CardDef(静的定義)のロードと山札ユーティリティ。data/cards.json / quests.json
  state.py          # GameState と派閥別 FactionState(すべて frozen dataclass)
  actions.py        # Action 型群(共通 + 派閥固有)。純データ(dataclass)
  legal.py          # legal_actions(state) -> list[Action] のディスパッチ
  apply.py          # apply(state, action, rng) -> GameState のディスパッチ
  battle.py         # 戦闘サブシステム(4.3 の4ステップ + 派閥の読み替えフック)
  crafting.py       # クラフト共通処理(4.1)
  factions/
    __init__.py     # FactionLogic プロトコル定義と registry
    marquise.py     # 猫野侯国(rules/cat.md)
    eyrie.py        # 鷲巣王朝(rules/birds.md)
    alliance.py     # 森林連合(rules/woodland.md)
    vagabond.py     # 放浪部族(rules/vagabond.md)
  data/
    map_autumn.json
    cards.json      # 山札54枚(ユニーク定義 + copies)
    quests.json     # クエスト15枚
    boards.json     # 派閥ボード数列(コスト/VP/カードアイコン)※要検証データを集約
  game.py           # Game ファサード: セットアップ、ターン進行、勝利判定、対戦ループ
bots/
  __init__.py
  base.py           # Policy プロトコル: choose(state, legal_actions, rng) -> Action
  random_bot.py
```

## 3. コア設計判断

### 3.1 状態はイミュータブル、乱数は注入
- `GameState` は frozen dataclass。コレクションは `tuple` / `frozenset`。更新は `dataclasses.replace` を包んだヘルパで行う。
- 乱数(ダイス 4.3.2、シャッフル 2.1)は状態に持たせず、`apply(state, action, rng: random.Random)` に注入する。同一 seed で完全再現可能にする(将来のMCTSではchanceノードとして扱えるよう、乱数を使う適用箇所を `battle.py` のロールと `cards.py` のシャッフルに限定する)。

### 3.2 「保留デシジョンスタック」方式
Rootは1アクションの内部に他プレイヤーの選択が挟まる(奇襲 4.3.1、蜂起 8.2.6、野戦病院 6.2.3、ヒット割り振り 4.3.4 等)。これを次で統一する:

- `GameState.pending: tuple[Decision, ...]`(スタック)。`Decision` は「誰が」「何を選ぶか」を表す frozen dataclass(例: `AmbushDecision(defender, battle_ctx)`, `AllocateHitsDecision(player, hits, battle_ctx)`, `OutrageDecision(payer, clearing)`)。
- `legal_actions(state)` は pending が空でなければスタック先頭の Decision に対する選択肢のみを返す。空ならターンプレイヤーのフェイズに応じた通常アクションを返す。
- `state.to_act()`(次に選択すべきプレイヤー)は pending 先頭の担当者、なければターンプレイヤー。
- 選択肢が1つしかない Decision も自動解決せずスタックに積んでよい(実装単純性優先)が、`game.py` のループで単一選択は自動適用してよい。

### 3.3 アクションは純データ、適用は関数
- `Action` はプレイヤーIDと必要パラメータのみを持つ dataclass(例: `Move(player, src, dst, count)`, `DeclareBattle(player, clearing, defender)`, `CraftCard(player, card_id, tool_ids)`)。
- 派閥固有アクション(例: `Build(建設)`, `Recruit`, `SpreadSympathy`, `Explore`)も同じ流儀で `actions.py` に定義。名前は英語、docstringに原文番号。
- `apply` は Action 型でディスパッチ。**適用前に合法性を再検証しない**(生成器が正しいことをテストで担保。ただし `assert` による安価な防御は可)。

### 3.4 派閥ロジックのプロトコル(並列実装のための境界)
`factions/__init__.py` に:

```python
class FactionLogic(Protocol):
    faction: FactionId
    def setup(self, state, setup_choices, rng) -> GameState: ...
    def legal_actions(self, state) -> list[Action]:  # 自派閥ターンの現フェイズの合法手
    def begin_phase(self, state, rng) -> GameState:  # フェイズ開始時の強制処理(木材配置 6.4 等)
```

- 共通アクション(移動・戦闘・クラフト)の**本体**は `battle.py`/`crafting.py`/`apply.py` にあり、派閥モジュールは「いつ・何回・どのコストで使えるか」だけを差す。
- 派閥による共通ルールの読み替え(ゲリラ戦 8.2.2、放浪部族のヒット=アイテム損傷 9.2.7、森の王者 7.2.2、身軽 9.2.3 等)は、`battle.py`/`board.py` に**フック点を最初から用意**する(下記 3.6)。派閥モジュール側から `if faction == ...` の分岐を核に埋め込むのではなく、核が問い合わせる形にする:
  - `rules_hooks.py` は作らず、`FactionLogic` にオプションメソッドとして生やす(未実装はデフォルト動作)。例: `battle_dice_assignment(default)`, `hit_capacity(state, clearing)`, `apply_hits(state, hits) -> GameState`, `rules_tiebreak(counts) -> winner`, `can_move(state, src, dst) -> bool`, `on_pieces_removed(...)`。

### 3.5 支配・移動・除去のセマンティクス
- 支配(2.5): 兵士コマ+建物タイル数の最大。同点は支配者なし。鷲巣のタイブレーク(7.2.2)はフック。放浪者コマ・トークンは不算入(9.2.2)。
- 移動(4.2.1): 移動元か移動先を支配していること。放浪者は無条件(9.2.3)。
- **除去の行き先(ユーザー確認済み)**: 建物タイル・専用トークンは所有派閥ボードの対応トラックの**最右の空き枠**へ戻る。兵士コマはサプライへ。城砦は再配置不可のためゲームから除外(6.2.2)。支持トークンは支持エリアの最右空き枠へ。木材はサプライへ。
- 建物・トークン除去による1VP(3.2.1)は除去した側に入る(戦闘・狙撃・反乱すべて共通)。

### 3.6 戦闘(battle.py)
4.3の4ステップを Decision スタックで表現する:
1. `DeclareBattle` 適用 → `AmbushDecision(defender)` を積む
2. 防御側: 奇襲する/しない → するなら `AmbushCounterDecision(attacker)` → 解決(2ヒット即適用、攻撃側全滅なら戦闘終了)
3. ロール(rng)。出目上限 = 戦場の自兵士数(4.3.2.I)、放浪部族は非損傷S枚数(9.2.6)、防御側連合は大小反転(8.2.2)
4. `EffectsDecision`(フェーズ1では実装済みの戦闘効果のみ: 無防備+1ヒット 4.3.3.II は自動)
5. `AllocateHitsDecision(受け手ごと)` → 兵士優先制約(4.3.4)。放浪部族はアイテム損傷選択(9.2.7)。除去発生時に蜂起(8.2.6)・野戦病院(6.2.3)・敵対化(9.2.9.III)のフックを発火
- 戦闘コンテキスト(戦場、攻守、残ヒット等)は Decision 内に不変データとして保持。

### 3.7 クラフト(crafting.py)
- クラフトツール: 猫=工房(6.2.1)、鳥=止まり木(7.2.1)、連合=支持トークン(8.2.1)、部族=H(9.2.1、動物種は現在地に追従、複数コスト=H複数)。ツールごとに1ターン1回(4.1.1)。
- カード効果は `cards.json` の `effect.kind` でディスパッチ:
  - `item`: アイテム獲得+VP(4.1.2)。サプライに無ければクラフト不可。鳥の商業軽視はフック(7.2.3)
  - `immediate` / `persistent`: フェーズ1は **実装済み効果のホワイトリスト**のみ合法手に含める。未実装効果のカードはクラフト不可として除外(ゲーム進行は壊さない)。実装対象(シンプルで頻出): Armorers, Sappers, Brutal Tactics, Royal Claim, Command Warren, Better Burrow Bank, Cobbler, Codebreakers, Stand and Deliver!, Tax Collector, Favor三種 は**フェーズ4以降に回してよい**(=フェーズ1の必須はitem系のみ)。

### 3.8 ターン構造と勝利
- `game.py` がフェイズ遷移を駆動: 鳥歌開始時に圧倒勝利判定(3.3.1)→各派閥の begin_phase → プレイヤー選択ループ(`EndPhase`/`EndTurn` アクションを合法手に含める)。
- 30VP到達で即勝利(3.1)。圧倒カードの発動・回収(3.3)は昼光の合法手。放浪部族は発動不可、代わりに共闘軍(9.2.8、4人戦のみ)。
- 安全弁: `max_turns`(既定300ターン)超過で引き分け終了(統計上 "timeout" と記録)。

### 3.9 セットアップ
- 5.1の手順を `game.py` に実装。派閥ごとの初期配置選択(城砦の隅選択 6.3.2、鳥の開始隅 7.3.2、部族のキャラ・樹林選択 9.3)は「セットアップ用 Decision」として同じ合法手機構で処理(botにも選択させられる)。
- 準備順は派閥ボード記載のA,B,C…(5.1.7)。本4派閥の順: 猫→鳥→連合→部族(A→B→C→D)。

## 4. データ仕様(engine/data/)

### 4.1 map_autumn.json
```json
{"clearings": [{"id": 0, "suit": "fox", "slots": 1, "ruin": false, "corner": "NW",
                 "adjacent": [1,4], "forests": [0]}, ...],
 "forests": [{"id": 0, "adjacent_forests": [1]}, ...]}
```
- 12広場。`corner` は NW/NE/SW/SE または null。遺跡4ヶ所(2.2.4)。slotsは建物枠数(遺跡枠は遺跡除去後に使用可になる点に注意: 遺跡がある間は塞がっている)。
- 河はフェーズ1では未使用(河民商団専用)なので省略してよい。

### 4.2 cards.json(山札54枚)
```json
[{"id": "anvil", "name": "Anvil", "suit": "fox", "copies": 1,
  "kind": "craftable", "cost": ["fox"],
  "effect": {"type": "item", "item": "hammer", "vp": 2},
  "text": "...", "image": "https://..."}, ...]
```
- `suit`: fox|rabbit|mouse|bird。`kind`: craftable|ambush|dominance。
- `cost` の要素: fox|rabbit|mouse|bird|any("?"シンボル)。
- `effect.type`: item|immediate|persistent(item以外は `key` と `text` を保持し、実装はホワイトリスト方式)。
- Σcopies = 54 であること(ロード時に assert)。

### 4.3 quests.json(15枚)
```json
[{"id": "errand_rabbit_1", "name": "Errand", "suit": "rabbit",
  "items": ["boots", "coins"], "image": "https://..."}, ...]
```

### 4.4 boards.json(派閥ボード数列、**要検証マーク付き**)
```json
{"marquise": {"building_costs": [0,1,2,3,3,4],
               "building_vp": {"sawmill": [...6], "workshop": [...6], "recruiter": [...6]},
               "card_icons": {"recruiter": [枠index...]}},
 "eyrie": {"roost_vp": [...7], "roost_card_icons": [...]},
 "alliance": {"sympathy_costs": [...10], "sympathy_vp": [...10], "base_card_icons": {...}},
 "_verified": false}
```
- 実数値は実装者がベストエフォートで埋め、`rules/data-verification.md` に一覧化してユーザー検証に回す。

## 5. アイテムとサプライ

- 共通サプライ(5.1.5): boots×2, bag×2, crossbow×1, hammer×1, sword×2, tea×2, coins×2。
- 遺跡アイテム: R付き bag/boots/hammer/sword 各1(9.3.4)。開始時アイテム(S付き): boots, bag, crossbow, hammer, sword, tea, coins, **torch** 各1(B.1.2 のアイテム総数23枚から逆算)。
- 放浪部族キャラ(基本3種, D.1〜D.3): 盗賊{M,F,T,S}/修繕屋{M,F,B,H}/森護り{M,F,C,S}。特別アクション: 盗み/日常業務/隠れ家(rules/vagabond.md 9.5.9 + 原文D章)。

## 6. テスト戦略(フェーズ2の先行分)

- フェーズ1完了条件のスモーク: `python -m sim.smoke --games 20 --seed 0` で4人戦(猫鳥連合部族)がクラッシュせず終了すること。
- 状態不変量チェック(適用ごとに検証できる `state.validate()`): 兵士総数≤上限、広場の建物数≤枠数、VP≥0、手札枚数整合、アイテム総数保存 等。デバッグモードでのみ有効化。

## 7. 実装フェーズ分割(このセッション以降)

1. **コア**(このセッション): types/board/cards/state/actions/legal/apply の骨格 + battle + crafting + game ループ + random_bot。派閥ロジックはインターフェースとスタブ(猫のみ最小実装して1派閥ソロのスモークが回る状態)。
2. **派閥並列実装**(次セッション): marquise 完成 / eyrie / alliance / vagabond を4エージェント並列。コアとの境界は本書 3.4 のプロトコル。共有ファイル(actions.py 等)への追記が必要な場合は「派閥名プレフィックスの新規クラス追加」のみ許可し、既存コードの変更は禁止(コンフリクト防止)。
3. **統合スモーク+レビュー**(その次): 4派閥戦のスモーク、Fableによる横断レビュー。
