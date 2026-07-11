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

---

## 8. 放浪部族の詳細設計(Fable 2026-07-09。実装者はこの設計に従うこと)

ルールの正は `rules/vagabond.md`(追補D・ボード印刷データ含む)。データは
`engine/data/boards.json` の `vagabond` キーと `map_autumn.json` の `forests`(いずれも確定済み)。

### 8.1 スコープ(ユーザー確認済み 2026-07-09)

**実装する**: 全9アクション(9.5.1〜9.5.9)+鳥歌(回復・潜入)+夕闇4ステップ、
アイテム3ゾーン管理、派閥関係トラック(強化VP・同盟援助2VP)・敵対・悪名、
戦闘の読み替え4種(9.2.4/9.2.6/9.2.7/9.2.2.I)、キャラクター3種(盗賊/修繕屋/森護り)、
遺跡探索(隠匿アイテム)、クエスト(解決後に山札から1枚補充する。日本語版法典の
記述漏れと判断、ボード面 "Claim a quest and replace it." に準拠)。

**対象外(既知の簡略化として記録)**:
- 共闘軍(9.2.8)— 圧倒カード(3.3)自体が未実装のため同水準で当面対象外。放浪部族の勝利は30VPのみ。
- 同盟派閥との同時移動・同時攻撃・ヒット肩代わり(9.2.9.II.b〜d)— 戦闘への大型フックが必要。
  同盟状態自体と援助2VP(II.a)は実装する。フェーズ4前後で追加。
- 放浪部族2人戦(9.7)、拡張キャラクター(D.4以降)。

### 8.2 状態モデル(VagabondState)

```python
@dataclass(frozen=True)
class ItemTile:
    kind: str            # ItemKind の値("boots"等)
    exhausted: bool = False   # 裏向き(使用済み)
    damaged: bool = False     # 損傷アイテムボックスにある
    on_track: bool = True     # T/X/B が配置枠にある(表向き時のみ)。M/S/C/F/H は常に False

@dataclass(frozen=True)
class VagabondState(FactionState):
    character: Optional[str] = None       # "thief"/"tinker"/"ranger"(9.3.1)
    pawn_clearing: Optional[int] = None   # 広場 or 樹林のどちらか一方(排他)
    pawn_forest: Optional[int] = None
    items: Tuple[ItemTile, ...] = ()
    #: 派閥関係(9.2.9): 0=無関心,1,2,3=同盟 / -1=敵対。他派閥全員分
    relationships: Tuple[Tuple[FactionId, int], ...] = ()
    #: 同一ターン中の派閥ごとの援助回数(9.2.9.I.a。ターン開始でリセット)
    aids_this_turn: Tuple[Tuple[FactionId, int], ...] = ()
    quest_deck: Tuple[str, ...] = ()      # 非公開の山(シャッフル済み)
    quests_open: Tuple[str, ...] = ()     # 公開3枚
    quests_done: Tuple[str, ...] = ()     # 解決済み(動物種カウントは quests.json 参照)
    #: 遺跡の隠匿アイテム(9.3.4)。(広場ID, ItemKind値)。探索で除去
    ruin_items: Tuple[Tuple[int, str], ...] = ()
    #: 戦闘中に自アイテム損傷で満たしたヒット数(9.2.9.II.d 用。宣言時リセット)
    #  ※II.d は対象外だが、奇襲・複数戦闘の整合のため損傷はすべて decision 経由にする
```

- **ゾーンの導出**: `damaged=True` → 損傷ボックス / `on_track=True` → 配置枠 / それ以外 → かばんエリア。
- **配置枠の自動配置(簡略化)**: T/X/B が「表向きで獲得・回復・修理」された時、配置枠(種類毎3枠、
  boards.json `track_slots_per_kind`)に空きがあれば自動で配置する(9.2.5.I の「配置できる」は
  常に選択と割り切る。枠に置くことは常に有利: X/T/B ボーナス対象になり、上限9.6.4の計算外になる)。
  枠が満杯なら表向きのままかばんエリアに留まる。使用(裏向き化)時は on_track=False にして
  かばんエリアへ(9.2.5.I)。
- **アイテムコストの支払い**: 「未使用(表向き)・非損傷の該当種1枚を exhaust」。同種同状態の
  タイルは同一視し(dedupして)決定的に選ぶ(配置枠のものを優先)。既存の猫/鳥/連合の
  自動支払いと同方針の簡略化。

### 8.3 アクションと Decision

昼光は回数制限なし(アイテムが尽きるまで)。合法手 = コストを支払える全アクション + EndPhase。

| Action | コスト | 要点 |
|---|---|---|
| VagabondSlip(dst) | なし | 鳥歌の潜入(9.4.2)。隣接する広場or樹林へ。任意(スキップ可) |
| VagabondMove(dst) | M1(+敵対兵士のいる広場へはM1追加) | 9.5.1。樹林へは移動不可。樹林からは隣接広場のみ。支配条件無視(9.2.3) |
| VagabondBattle(defender) | S1 | 9.5.2。現在広場で戦闘 |
| VagabondExplore | F1 | 9.5.3。現在広場の遺跡アイテム獲得+1VP。空になった遺跡は除去(ruin=False→枠が空く) |
| VagabondAid(faction, card_id, take_item) | 任意1 | 9.5.4。現在広場一致の手札(鳥可)を相手の手札へ。相手の作成アイテム(fs.items)があるなら1枚取得は**強制**(どれを取るかは選択。None は相手ボックスが空のときのみ)。関係処理は 8.5 |
| VagabondQuest(quest_id, reward) | クエスト記載の2枚 | 9.5.5。reward="vp"(同種解決数ぶん) or "cards"(2ドロー)。解決後、山から1枚補充 |
| VagabondStrike(target) | C1 | 9.5.6。現在広場の兵士1個、または兵士のいないプレイヤーの建物/トークン1個を除去 |
| VagabondRepair(kind) | H1 | 9.5.7。損傷1枚をかばんへ(裏表維持。表のT/X/Bは枠が空けば配置枠へ) |
| CraftCard(既存) | Hをコストシンボル数 | 9.5.8。全Hの動物種=現在広場(9.2.1)。樹林ではクラフト不可(広場の動物種がないため) |
| VagabondSpecial(...) | F1 | 9.5.9。盗み=対象プレイヤー指定(rngで1枚)/日常業務=捨て山の一致カード指定/隠れ家=3枚まで修理し即夕闇(鷲巣の休止と同じ phase 直行パターン) |

Decision(pending スタック):
- **VagabondSetupCharacterDecision** / **VagabondSetupForestDecision**(9.3.1/9.3.2)
- **RefreshDecision(remaining)**: 鳥歌の回復(9.4.1)。回復総数 = 3 + 表向きT(配置枠)×2。
  裏向きタイル数 ≤ 総数なら自動全回復(Decision不要)。超えるなら1枚ずつ選択(選択肢=裏向きの種類毎)
- **ItemDamageDecision(remaining)**: 受けヒット(9.2.7)・反乱等の全除去(9.2.2.I、3個)。
  選択肢=非損傷タイルの種類毎(表裏は区別)。非損傷が尽きたら残りは無視して pop
- **ItemLimitDecision**: 夕闇の上限調整(9.6.4)。かばん+損傷ボックスの枚数 > 6+表B(配置枠)×2 の間、
  1枚ずつ選択して**ゲームから除外**(捨て山ではない)

### 8.4 戦闘の読み替え(battle.py へのフック)

既存のゲリラ戦(8.2.2)分岐と同様に、放浪部族参加時のみの分岐を核に置く:

1. **出目上限(9.2.6)**: `_roll_and_allocate` の「自兵士数」を、放浪部族側は
   「非損傷Sの枚数」(exhausted は問わない)に置換。攻守どちら側でも適用
2. **無防備(9.2.4)**: 防御側が放浪部族のときの無防備判定(攻撃側+1ヒット)を
   「防御側兵士0」ではなく「非損傷Sを1枚も所有していない」に置換
3. **ヒット適用(9.2.7)**: 受け手が放浪部族なら AllocateHitsDecision の代わりに
   ItemDamageDecision を積む。`_has_pieces` 相当の継続判定は「非損傷アイテムが残っているか」
4. **奇襲2ヒット(4.3.1.II)**: 放浪部族が攻撃側なら2アイテム損傷(自動選択でなく Decision)。
   放浪者コマは除去されないため「攻撃側全滅で戦闘終了」は発生せず、ロールへ継続
5. **全除去効果(9.2.2.I)**: 連合の反乱(alliance._remove_all_enemies)で放浪者コマの広場が
   対象になったら、コマは除去せず ItemDamageDecision(3) を積む
6. **敵対化(9.2.9.III)**: remove_piece で source=部族 かつ 兵士除去 かつ 対象が非敵対なら即敵対へ。
   建物・トークンの除去では敵対化しない
7. **悪名(9.2.9.III.a)**: 部族のターン中の戦闘で「既に敵対の派閥」の配置物を除去するたび+1VP。
   敵対化のトリガーになった除去自体は対象外(除去時点では非敵対だったため)と解釈。
   狙撃(9.5.6)は戦闘ではないので悪名なし(建物/トークンの3.2.1のVPは入る)

放浪者コマは支配計算(2.5)に不算入 — 既存 controller() は soldiers/buildings のみ参照するため
変更不要。**蜂起(8.2.6)は「兵士コマの移動」がトリガーのため、放浪者コマの移動では発火しない**
(outrage_on_move を呼ばないこと)。

### 8.5 派閥関係の処理(9.2.9)

- 援助アクション適用時、対象派閥の状態で分岐:
  - **敵対(-1)**: 関係は動かない(III.c)。アイテム取得は可
  - **同盟(3)**: +2VP(II.a)
  - **無関心〜(0..2)**: aids_this_turn[faction] += 1。それが
    `relationship_aid_costs[現在マス]`(=1/2/3)に達したら1マス進めて
    `relationship_vp[新マス-1]`(=1/2/2)を獲得し、援助回数を0にリセット(I.a/I.b)
- aids_this_turn は部族のターン開始(鳥歌 begin_phase)でリセット
- 敵対化(8.4-6)はトラック位置を捨てて -1 へ(一方通行)

### 8.6 セットアップ(9.3)と樹林

- new_game: VagabondSetupCharacterDecision(3種) → VagabondSetupForestDecision(7樹林)を積む。
  クエスト山シャッフル+3枚公開、遺跡アイテム4種(boards.json `ruin_items`)を rng で
  4遺跡広場(ruin=True の cid)へ割当(隠匿情報として ruin_items に保持)、
  キャラ確定時に初期アイテム(boards.json `characters[].start_items`)を配置、
  関係マーカーは参加中の他派閥すべて無関心(0)で初期化
- map_autumn.json の forests(7樹林、隣接広場・隣接樹林)を board.py の MapData に追加ロードする。
  樹林は放浪者コマ専用の位置であり、広場のような配置物・動物種を持たない

### 8.7 フェイズ進行

- **鳥歌**: begin_phase で aids_this_turn リセット → 回復(9.4.1、自動 or RefreshDecision)。
  合法手 = 潜入(VagabondSlip、任意) + EndPhase
- **昼光**: 合法手 = 8.3 の全アクション + EndPhase
- **夕闇**: begin_phase で夜の休息(9.6.1、樹林にいるなら損傷全回復=自動) →
  ドロー 1+表X(9.6.2) → 手札6枚以上なら DiscardDecision(9.6.3) →
  上限超過なら ItemLimitDecision(9.6.4)。合法手 = EndPhase
- 隠れ家(D.3.2)は昼光を即終了して夕闇 begin_phase へ(鷲巣の休止 7.7.4 と同じ実装パターン)

### 8.8 検証項目(selftest に追加すべきシナリオ)

1. 探索: 遺跡アイテム獲得+1VP、遺跡枯渇での除去(建物枠の解放)
2. 援助と関係強化: 1回→+1VP→(リセット後)2回→+2VP→3回→同盟、同盟後の援助+2VP、
   アイテム取得(相手の fs.items から移動)
3. 敵対化と悪名: 戦闘で非敵対派閥の兵士除去→即敵対(トリガー除去はVPなし)、
   同一戦闘の後続除去で+1VP、狙撃では悪名なし
4. 戦闘読み替え: 出目上限=非損傷S数、非損傷Sなしでの無防備+1、受けヒットのアイテム損傷、
   非損傷が尽きたら超過ヒット無視
5. 反乱 vs 放浪者コマ: コマ残存+アイテム3損傷(9.2.2.I)
6. 夕闇: 樹林での全回復、ドロー1+表X、上限6+2B超過時のゲーム除外
7. クエスト: 2アイテム消費、同種2枚目=2VP、補充で公開が3枚に戻ること

---

## 9. フェーズ2: テスト・検証基盤の設計(Fable 2026-07-10。実装者はこの設計に従うこと)

対象は**実装済み3派閥(猫野侯国・鷲巣王朝・森林連合)+共通ルール**。放浪部族はフェーズ5で
実装後にテストを追加する(8章のテストはここでは書かない)。

**テストの性格**: エンジンの「実装済みの正しい挙動」を固定化する回帰テスト。ロードマップ引き継ぎ
メモに記録済みの**既知の簡略化(野戦病院・圧倒カード・木材/支払いの自動選択 等)はテストしない**。
テスト作成中にルール(`rules/*.md`)と実装の食い違いを見つけた場合は、**修正せずテストを
`@pytest.mark.xfail(reason=...)` にして報告に含める**こと(修正判断はFableのレビューで行う)。

### 9.1 構成と実行方法

```
tests/
  conftest.py            — 共通ヘルパー・フィクスチャ(9.2)
  test_selftest.py       — 既存 engine/selftest の各 test_* 関数を pytest から呼ぶ薄いラッパー
  test_common.py         — 共通ルール: 移動・戦闘・クラフト・支配(9.3)
  test_marquise.py       — 猫野侯国(9.3)
  test_eyrie.py          — 鷲巣王朝(9.3)
  test_alliance.py       — 森林連合(9.3)
  test_invariants.py     — validate() 単体 + ミニスモーク(9.4, 9.5)
```

- 実行: リポジトリルートで `python3 -m pytest tests/ -q`(pytest 8.4.2 導入済み、Python 3.9)。
- `tests/__init__.py` は置かない。import は `from engine...`(ルート起動前提)。
  必要なら `conftest.py` で `sys.path` 調整ではなく **pytest の rootdir 前提**でそのまま動くことを確認する。
- 追加依存の導入は禁止(pytest のみ)。

### 9.2 共通ヘルパー(conftest.py)

selftest の `_setup_two_faction` パターンを一般化する。**selftest.py は変更しない**(既存の検証を壊さない)。

- `make_state(factions, seed=42) -> (GameState, rng)`: `new_game` + セットアップ Decision
  (猫の城砦NW、鷲巣の隅・君主 等)を解決して pending 空の初期状態を返す。
  各派閥のセットアップ Decision の解決手順は selftest.py と game.py を参照。
- `put(state, cid, *, soldiers={faction: n}, buildings=[Piece...], tokens=[Piece...]) -> GameState`:
  広場への駒の手動配置(`with_clearing` ラッパー)。
- `set_hand(state, faction, card_ids) -> GameState`: 手札の差し替え(`dataclasses.replace`)。
- `find_card(state, *, suit=None, is_ambush=None, item=None) -> card_id`: デッキからの条件検索
  (テストで特定カードが必要なとき用)。
- `legal_of(state, cls) -> list[Action]`: `legal_actions(state)` を型でフィルタ。
- `assert_legal(state, action)` / `assert_illegal(state, action)`: `legal_actions` への所属で判定。
  Action は frozen dataclass なので等値比較でよい(万一 eq が効かない型があればフィールド比較に落とす)。

### 9.3 合法/違法テストケース集(最低限、各1テスト関数)

フェーズ0の `rules/*.md` の節番号をテスト docstring に併記すること(トレーサビリティ)。

**共通(test_common.py)**
1. 移動 4.2: 出発か到着を支配していれば合法/どちらも支配していなければ違法/非接続広場へは違法
2. 戦闘 4.3: 防御側の駒がある広場でのみ DeclareBattle が合法/自派閥のみの広場では違法
3. 戦闘 4.3.2: 無防備(防御側が建物・トークンのみ)で攻撃側+1ヒット
4. 戦闘 4.3.2: ヒット数は自兵士数が上限(出目クランプ)
5. クラフト 4.4: ツール(工房等)のスート不足で違法/アイテムがサプライ枯渇で違法
6. 支配 2.5: 同数タイは支配なし(鷲巣がいる場合のタイブレークは test_eyrie 側)

**猫野侯国(test_marquise.py)**
1. 建設 6.5.2: 支配広場+空き枠+連結木材が足りれば合法、木材不足なら違法
2. 建設: 建設後に木材トークンが消費され、VPが入る(boards.json の印刷値に従う)
3. 木こり 6.5.1: 製材所のある広場に木材が置かれる(サプライ上限まで)
4. 徴兵 6.5.3: 募兵所の広場に兵士配置、サプライ不足時の挙動
5. 城砦 6.2.1: 城砦広場に他派閥は駒を置けない(移動先として違法)

**鷲巣王朝(test_eyrie.py)**
1. 勅令 7.5: 昼光は勅令の列を左から強制実行、列にない任意アクションは違法
2. 内乱 7.7: selftest 済みのため test_selftest.py のラッパーでカバー(重複して書かない)
3. 森の王者 7.2: 同数タイの広場を鷲巣が支配する
4. 商業軽視 7.3: クラフトVPが印刷値でなく1VPになる
5. 恥辱 7.7.1: VP喪失が0でクランプされる(selftest 済みならラッパーでカバー)

**森林連合(test_alliance.py)**
1. 支持拡大 8.5.1: 累進コスト(支持トークン数に応じた枚数)/一致スートの支援者不足で違法
2. 戒厳令 8.4.2.II.a: 対象広場に単独派閥の兵士3以上で+1枚
3. 蜂起 8.5.2: 一致スート支援者2枚で合法、基地設置+対象広場の敵駒全除去
4. 憤慨 8.4.1: 他派閥が共感トークンを除去→そのプレイヤーは一致スートのカードを支援者へ
5. ゲリラ戦 8.4.3: 防御側(連合)が高い方の出目を取る
6. 支援者上限 8.4.1: 基地が盤上にないとき支援者は5枚まで(超過分は捨札)

### 9.4 状態不変量: validate() の拡張(engine/state.py)

現状の validate()(枠数・兵士非負・VP≥0)に以下を追加する。**印刷値のハードコード禁止**:
上限は `boards.json` / `cards.json` からロードした値を使う(state から参照できなければ
map/boards のロード結果を保持する適切な場所に足す。既存 API の変更は最小限に)。

1. 派閥ごとの盤上兵士総数 ≤ 上限(猫25・鷲巣20・連合10。boards.json の値)
2. 建物種ごとの盤上数 ≤ 印刷数(製材所/工房/募兵所 各6、止まり木7、基地3)
3. トークン: 木材≤8、共感≤10、城砦≤1
4. カード保存則: 山札+捨札+全手札+連合の支援者+勅令の列+(公開中の状態があれば加算)= 54。
   クラフト済みカードの行き先(捨札か恒久領域か)は cards.py / apply.py の実装を確認して式に反映
5. pending スタックの player が state.factions に含まれる

`run_game(..., validate_each_step: bool = False)` を追加し、True のとき毎 apply 後に
`state.validate()` を呼ぶ。既定 False(性能への影響を避ける)。

### 9.5 スモークテストの二段構え

- **pytest 内ミニスモーク(test_invariants.py)**: 3人戦(猫・鷲巣・連合)を `validate_each_step=True`
  で 10 試合。CI 相当の常時実行でも数十秒に収まる規模にする。
- **1000戦スモーク(手動)**: `sim/smoke.py` に `--validate` フラグを追加(run_game に引き渡すだけ)。
  実行自体は実装完了後にFableが行うので、subagent は 30 試合程度の動作確認まででよい。

### 9.6 完了条件(subagent の報告に含めること)

1. `python3 -m pytest tests/ -q` 全パス(xfail は許容、一覧を報告)
2. `python3 -m engine.selftest` が引き続き合格(既存ファイル無変更の確認)
3. 報告には「レビュー注目点(ファイル:行)」を必須で書く(特に validate() のカード保存則と、
   ルールとの食い違いを見つけた箇所)

---

## 10. フェーズ3セッションA: 並列対戦ランナー+SQLite保存+基礎集計(Fable 2026-07-10)

**スコープ**: 標準ライブラリのみ(multiprocessing / sqlite3)。**追加依存の導入は禁止**
(pandas・matplotlib・pyarrow はセッションB=可視化で判断する。Parquet 書き出しも B へ先送り)。

### 10.1 構成

```
simulation/
  __init__.py
  runner.py     — 並列対戦ランナー(python3 -m simulation.runner)
analysis/
  __init__.py
  report.py     — 基礎集計レポート(python3 -m analysis.report)
```

### 10.2 runner.py

- CLI: `--games N --factions marquise,eyrie,alliance --seed 0 --max-turns 300
  --workers 0(=os.cpu_count) --db simulation/results.sqlite --validate --label "任意メモ"`
- 実装要点:
  - ワーカー関数はトップレベル関数(picklable)。引数 `(seed, faction_values, max_turns, validate)`
    を受け、ワーカー内で `RandomBot` と policies を構築して `run_game` を呼ぶ。
    戻り値は `(seed, winner_value|None, turns, {faction_value: vp}, elapsed_sec)` のプレーンタプル。
  - `multiprocessing.Pool(workers)` + `imap_unordered`(chunksize は `max(1, games//(workers*8))`)。
    親プロセス側で進捗を 100 試合ごとに1行 print。
  - DB 書き込みは**親プロセスのみ**(ワーカーは sqlite に触らない)。全試合完了後に一括 INSERT
    + commit(数千件規模なので分割不要)。
  - `--workers 1` のときは Pool を使わず直列実行(デバッグ用・selftest的に例外がそのまま出る)。
- スキーマ(`CREATE TABLE IF NOT EXISTS`):

```sql
runs  (run_id INTEGER PRIMARY KEY AUTOINCREMENT,
       created_at TEXT NOT NULL,          -- ISO8601 UTC
       label TEXT,
       factions TEXT NOT NULL,            -- "marquise,eyrie,alliance"(入力順)
       games INTEGER NOT NULL, base_seed INTEGER NOT NULL,
       max_turns INTEGER NOT NULL, validate INTEGER NOT NULL,
       engine_commit TEXT,                -- `git rev-parse --short HEAD`(失敗時 NULL)
       elapsed_sec REAL)
games (run_id INTEGER NOT NULL REFERENCES runs(run_id),
       game_idx INTEGER NOT NULL,         -- 0..N-1(seed = base_seed + game_idx)
       seed INTEGER NOT NULL,
       winner TEXT,                       -- faction value / NULL=timeout
       turns INTEGER NOT NULL,
       elapsed_sec REAL,
       PRIMARY KEY (run_id, game_idx))
game_vps (run_id INTEGER NOT NULL, game_idx INTEGER NOT NULL,
          faction TEXT NOT NULL, vp INTEGER NOT NULL,
          PRIMARY KEY (run_id, game_idx, faction))
```

- 実行終了時に run_id と1行サマリ(games/wins/timeouts/経過秒)を print する。
- `simulation/*.sqlite` は `.gitignore` に追加(結果DBはコミットしない)。
- **エンジン側の決定性制約(2026-07-10 確立)**: `legal_actions()` の返す順序はプロセスの
  文字列ハッシュシードに依存してはならない。set を反復して Action を列挙する箇所は必ず
  `sorted(..., key=lambda f: f.value)` を経由すること(marquise の `_battle_actions` が
  未ソートでプロセス間の再現性を壊していたのを修正済み。eyrie/alliance と同パターン)。

### 10.3 analysis/report.py

- CLI: `--db simulation/results.sqlite [--run ID]`(省略時は最新 run)。`--list` で runs 一覧。
- 出力(すべて sqlite3 の SQL 集計、print のみ):
  1. run メタ情報(factions/games/seed/engine_commit/elapsed)
  2. 派閥ごとの勝率(wins, win%, timeouts)
  3. ターン数の min/avg/max と分位点(P25/P50/P75。SQL の ORDER BY + OFFSET で算出)
  4. 派閥ごとの VP min/avg/max
  5. 勝者別の平均ターン数(どの派閥が勝つとき速いか)

### 10.4 完了条件(セッションA、subagent の報告に含めること)

1. `python3 -m simulation.runner --games 200 --factions marquise,eyrie,alliance --seed 0 --workers 0`
   が並列で完走し、`python3 -m analysis.report` が集計を表示すること(出力を報告に貼る)
2. 同一 `--games/--seed/--factions` なら並列でも直列(`--workers 1`)でも **games テーブルの内容が
   一致する**こと(seed 固定の決定性。winner/turns で確認)
3. `python3 -m pytest tests/ -q` が引き続き全パス(エンジン本体は無変更のはず)
4. レビュー注目点(ファイル:行)を列挙

### 10.5 フェーズ3セッションB: 可視化ダッシュボード(Fable 2026-07-10)

**方式**: Chart.js の静的HTML生成(Python追加依存ゼロ。Chart.js は CDN の `<script>` タグ)。
matplotlib は導入しない。

- 新規: `analysis/dashboard.py`(`python3 -m analysis.dashboard`)。既存ファイルの変更は
  `.gitignore` への出力HTML追加のみ許可。
- CLI: `--db simulation/results.sqlite`(既定)、`--runs 1,3,5`(省略時=全run)、
  `-o simulation/dashboard.html`(既定)。
- 実装: sqlite3 で集計 → データを JSON として HTML に埋め込み(`json.dumps` を
  `<script>const DATA = ...;</script>` に書き出す)→ 1ファイルの自己完結HTML。
  Python 側でのテンプレートエンジン等は使わず、文字列テンプレート(`string.Template` か
  f-string)で十分。HTMLの `<html lang="ja">`、タイトル・ラベルは日本語。
- 含めるチャート(Chart.js v4、CDN固定バージョン指定):
  1. **run比較: 派閥別勝率**(グループ棒グラフ。x=run、系列=派閥+timeout。run のラベルは
     `#id label(games)`)← フェーズ4でbot改善の効果測定に使う主役
  2. **ターン数分布**(runごとのヒストグラム、ビン幅5ターン。折れ線overlayで複数run比較)
  3. **派閥別VP分布**(runごと・派閥ごとの平均±min/max。棒+エラーバー相当の表現で可)
  4. **runメタ情報テーブル**(run_id/created_at/label/factions/games/engine_commit/elapsed)
- 派閥の色は固定マップ(marquise=#d97706 橙、eyrie=#2563eb 青、alliance=#16a34a 緑、
  vagabond=#6b7280 灰、timeout=#9ca3af 薄灰)。将来の放浪部族追加でも色が安定するように。
- 完了条件: 既存の `simulation/results.sqlite`(なければ runner で200試合生成)から
  dashboard.html が生成でき、`python3 -m pytest tests/ -q` が全パス。報告には生成HTMLの
  パスとレビュー注目点(ファイル:行)を含める。

---

## 11. フェーズ4: ヒューリスティックbot(Fable 2026-07-10。実装者はこの設計に従うこと)

### 11.1 方式: 1手先読み greedy + 派閥別評価関数

ルールベース(アクション種別ごとの優先順位 if 文)は採らない。`Policy.choose` に来る候補は
通常アクションだけでなく pending デシジョン(ヒット割り振り・捨て札・君主選択等)を含む
全意思決定であり、種別網羅が破綻するため。代わりに:

> 各候補アクションを `engine.apply.apply` でシミュレート実行し、結果状態を評価関数で
> スコアリングして argmax を選ぶ(1-ply greedy)。

- 派閥の知識は評価関数(`faction_score`)に集約する。これがロードマップ成果物の
  「勢力ごとの評価関数」であり、フェーズ6の RL 報酬設計の下敷きになる。
- エンジン(`engine/`)・既存 bot(`bots/base.py`, `bots/random_bot.py`)は**変更禁止**。
  変更可能なのは新規ファイルと runner/report の統合部分(11.4)のみ。

### 11.2 HeuristicBot(bots/heuristic/bot.py)

`Policy` プロトコル実装。コンストラクタ `HeuristicBot(samples: int = 3)`。

`choose(state, actions, rng)`:
1. `base = rng.getrandbits(32)` — メイン rng の消費は choose 1回につきこの1回だけ
   (決定性 10.2: 消費列が seed から一意に定まる)。
2. 各候補 `actions[i]` について `samples` 回シミュレート:
   `sim_rng = random.Random((base << 16) ^ (i << 8) ^ j)` で
   `next_state = apply(state, actions[i], sim_rng)` → `score_j = evaluate(next_state, me)`。
   スコアは samples 回の平均(戦闘ダイス・ドローの乱数ノイズを均す)。
   `me = state.to_act()`(choose 時点の手番/デシジョン actor)。
3. 終端ショートカット: `next_state.finished` かつ `winner == me` なら +1e9、
   winner が他派閥なら -1e9(サンプル平均に含めてよい)。
4. argmax を返す。同点は**先頭優先**(legal_actions の順序は決定的=10.2 なので決定的)。
5. `apply` は例外を投げない前提(合法手のみ渡ってくる)。try/except で握りつぶさない。

### 11.3 評価関数(bots/heuristic/evaluate.py + marquise/eyrie/alliance の各モジュール)

```
evaluate(state, me) = faction_score(state, me) - max(faction_score(state, f) for f in 他派閥)
```
(相手項は「首位の他派閥」のみ。妨害の照準をリーダーに合わせる。DUMMY は 0 固定)

`faction_score(state, f)` = 共通項 + 派閥固有項。**重みはすべて初期値**であり、11.5 の
比較 run で効果を見て調整してよい(調整結果は報告に記録)。

共通項(evaluate.py):
- `vp * 100`(30VP 到達勝ちなので VP を支配的に)
- `支配クリアリング数 * 6`(`state.controller(cid)` 使用)
- `兵士がいるクリアリング数 * 2` + `盤上兵士総数 * 1`
- `手札枚数 * 2`(ただし 5 枚まで。抱えすぎに報酬を与えない)

猫野侯国(marquise.py)— 建物はエンジン(VP は共通項で計上済み。ここでは将来収入を評価):
- `盤上の製材所 * 8`(木材収入)+ `募兵所 * 8`(兵士収入)+ `工房 * 5`(クラフト)
- `盤上の木材トークン * 2`

鷲巣王朝(eyrie.py):
- `built_roosts * 10`(ターン VP と募兵数の源泉)
- 内乱リスクの代理指標: `-6 * max(0, 勅令総カード数 - 盤上兵士数//2 - built_roosts - 2)`
  (1-ply では後日の内乱が見えないため、遂行能力を超えた勅令肥大に事前ペナルティ)

森林連合(alliance.py):
- `盤上の共感トークン * 8` + `拠点 * 12` + `officers * 5`
- `支援者枚数 * 2`(7 枚まで。上限超過廃棄に報酬を与えない)

### 11.4 runner/report 統合

- `simulation/runner.py` に `--bots SPEC` を追加。`random`(既定)/`heuristic` で全派閥一括、
  または `marquise=heuristic,eyrie=random,alliance=random` 形式で派閥別指定。
  WorkerArgs に bots 指定を追加し `_play_one` 内で per-faction に Policy を構築。
- `runs` テーブルに `bots TEXT` 列を追加。マイグレーションは接続時に
  `ALTER TABLE runs ADD COLUMN bots TEXT` を試み `OperationalError`(重複)は無視。
  既存 DB の旧 run は NULL のまま=random とみなす。`report --list` に bots 列を表示。
- `--label` を活用し、11.5 の比較 run には内容がわかるラベルを付ける。

### 11.5 完了条件(subagent の報告に含めること)

(11.6 の放浪部族追加時の完了条件は 11.6 末尾を参照)

1. `python3 -m pytest tests/ -q` 全パス + 新規 `tests/test_heuristic.py`:
   (a) choose の返り値が渡した候補に含まれる (b) 同一入力で同一出力(決定性)
   (c) 勝利直結アクションを確実に選ぶ(終端ショートカット)
2. 決定性: heuristic 全派閥・同一 seed で `--workers 1` と並列の games テーブルが一致
3. 比較 run(各 200 試合・seed 0・marquise,eyrie,alliance)を実行し勝率を報告:
   baseline 全 random / heuristic を 1 派閥だけに入れた 3 run / 全 heuristic。
   妥当性チェック: heuristic 化した派閥の勝率が baseline の同派閥勝率を明確に上回ること
   (特に猫・鷲巣が連合圧勝(baseline 98%)をどれだけ削れるか)。
4. 性能: 全 heuristic 200 試合の実行時間を報告。目安 1 試合 1 秒以内(並列)。
   超える場合は samples を下げた結果も報告(既定値変更の判断は Fable レビューで)。

### 11.6 放浪部族の評価関数(Fable 2026-07-11。フェーズ5の仕上げ)

新規 `bots/heuristic/vagabond.py` に `faction_term(state)` を実装し、`evaluate.py` の
`_FACTION_TERMS` に `FactionId.VAGABOND` を追加する。エンジン・既存評価モジュールは変更禁止。

放浪部族は兵士・建物を持たないため共通項(11.3)は実質 vp と手札のみ。派閥固有項で
**アイテム経済**と**位置**を評価する(VP 獲得イベント自体は 1-ply の apply 結果に
直接現れるので、ここでは「次以降のターンの稼ぐ力」だけを足す):

- **アイテム経済**(状態は `ItemTile`: kind/exhausted/damaged/on_track):
  - 非損傷アイテム 1 枚につき +2、さらに表向き(exhausted=False)なら +2
    (表向き非損傷=+4。無駄なコスト消費・損傷選択で exhausted/damaged を選ぶ誘導)
  - 非損傷 S(sword)1 枚につき追加 +2(出目上限 9.2.6・無防備回避 9.2.4 の源泉)
  - 配置枠(on_track)の表向き T +3 / X +3 / B +2(回復・ドロー・上限のエンジン強化。
    枠配置は自動処理なので「枠にあるものを損傷・除外で失わない」誘導が主目的)
- **派閥関係**(9.2.9): トラック位置 rel(0..3)の他派閥合計 × 3
  (同盟=毎援助+2VP の恒常収入に接近する価値。敵対 -1 は 0 として加算=ペナルティなし。
  悪名 +1VP は除去の都度 apply 結果に現れるため項は不要)
- **位置**(潜入 9.4.2・移動 9.5.1 の行き先に信号を与える):
  - 放浪者コマが広場にいる +3(樹林は夜の休息以外は何もできない)
  - その広場に遺跡があり(cs.ruin)、非損傷 F を持つなら +2(探索 9.5.3 の直前状態)
  - その広場に配置物を持つ他派閥数 × 2(援助・盗み・戦闘の機会)

重みはすべて初期値(11.3 と同様、比較 run で調整してよい。調整したら報告に記録)。

**完了条件(subagent の報告に含めること)**:
1. `python3 -m pytest tests/ -q` 全パス(既存 53+1 にリグレッションなし)。
   `tests/test_heuristic.py` に放浪部族の決定性テスト(同一入力→同一出力)を 1 件追加
2. 比較 run(各 200 試合・seed 0・factions marquise,eyrie,alliance,vagabond、--label 付き):
   (a) 全 random baseline (b) vagabond=heuristic のみ (c) 全 heuristic。
   妥当性チェック: (b) で放浪部族の勝率が baseline(現状 0%)を明確に上回ること
3. 決定性: (c) の構成・同一 seed で --workers 1 と並列の games テーブル一致
4. 性能: (c) 200 試合の実行時間(目安 1 試合 1 秒以内)

## 12. フェーズ6a: RL環境ラッパー(Fable 2026-07-11。実装者はこの設計に従うこと)

Mac のみで開発・テスト可能(GPU 不要)。学習本体(PPO)は 6c であり、ここでは
「エンジンを RL 学習ループに差し込める形」= 観測テンソル・固定行動空間・AEC 型
環境 API までを作る。

### 12.1 スコープと依存の分離

- 新規パッケージ **`rl/`** を作る。`engine/`・`bots/` は**変更禁止**(標準ライブラリのみを維持)。
- `rl/` の依存は **numpy のみ**(Mac に 1.26.4 導入済み)。**pettingzoo には依存しない**:
  AEC API(reset/step/observe/last/agents/agent_selection/rewards/terminations/
  truncations/infos)と同名・同義のメソッドを duck-typing で実装する
  (学習コンテナ側で本家 AEC 継承が必要になったら薄いアダプタを 6c で書く)。
- リポジトリ直下に **pyproject.toml** を追加し `pip install -e .` 可能にする
  (パッケージ: engine/bots/sim/simulation/analysis/rl、`engine.data` の JSON を
  package-data に含める)。`requires-python >= 3.9`(現 Mac は 3.9.6 で全テストが
  通っている。README の「3.11+」表記は「3.9+」に修正)。numpy は
  `[project.optional-dependencies] rl = ["numpy"]` に置き、エンジン本体の依存ゼロを守る。
  ※ この Mac の pip3 は ESP-IDF 環境を向いているため、`pip install -e .` の実行確認は
  **任意**。従来どおりリポジトリ直下からの `sys.path` 実行で全テストが通ることを必須とする。

### 12.2 行動カタログ(rl/catalog.py)— 固定インデックス+合法手マスク

PPO の行動空間は**固定長**が必要。全 Action を「正準キー」に写し、キーの全列挙に
インデックスを振る。

- `action_key(state, action) -> tuple`: Action → hashable キー。
  **不変条件: 同一 legal_actions 内でキーが衝突する2アクションは交換可能
  (どちらを適用しても同値)でなければならない。**
- `ActionCatalog`: 全キーの決定的列挙(静的データ= map_autumn.json / cards.json /
  quests.json / boards.json / enum 定義のみから構築。set 反復・dict 順依存の禁止は
  エンジン 10.2 と同じ)。`index_of(key)` / `key_at(i)` / `size`。
- `legal_mask(state, catalog) -> np.bool_[size]` と
  `action_for(state, index) -> Action`(合法手のうちキー一致の**最初**=
  legal_actions 順で決定的に解決)。

キー設計(ドメインは静的列挙。派閥・広場等は enum / JSON の定義順):

| Action | キー | ドメインの根拠 |
|---|---|---|
| EndPhase / MarquiseRecruit / EyrieSkipDecree / EyrieTurmoil / AllianceEndOps / VagabondExplore | (型名,) | パラメータなし |
| CraftCard / DiscardCard / MarquisePlayBirdCard / AllianceMobilize / AllianceTrain / AllianceDiscardSupporter | (型名, base_id) | カード実体は base_id で同一視(cards.json 定義順)。手札を離れるカードは銘柄が戦略価値を持つ |
| AmbushChoice / OutragePay | (型名, base_id or None) | None=しない/一致なし |
| DeclareBattle / AllianceOpBattle | (型名, clearing, defender) | defender は FactionId 全メンバー(死にインデックス許容) |
| MarquiseBuild | (型名, clearing, kind) | kind 3種 |
| MarquiseMarch | (型名, src, dst, count) | (src,dst)=隣接ペア(有向)、count 1..25 |
| MarquiseLabor | (型名, clearing, base_id) | |
| SetupChooseKeep / EyrieChooseCorner | (型名, corner) | 4隅 |
| EyrieChooseLeader | (型名, leader) | 君主4種 |
| EyrieAddToDecree | (型名, base_id, column) | column 0..3 |
| EyriePlaceRoost / EyrieDecreeBuild※ / EyrieRecruit※ | (型名, [suit,] clearing) | ※勅令系はカードがボードに残り銘柄が無意味なので **suit に縮約**(4種) |
| EyrieDecreeMove | (型名, suit, src, dst, count) | count 1..20 |
| EyrieDecreeBattle | (型名, suit, clearing, defender) | |
| AllianceRevolt / SpreadSympathy / OpRecruit / OpOrganize | (型名, clearing) | |
| AllianceOpMove | (型名, src, dst, count) | count 1..10 |
| VagabondChooseCharacter | (型名, character) | 3種 |
| VagabondChooseForest | (型名, forest) | 7樹林 |
| VagabondSlip | (型名, dst, dst_forest) | 広場12+樹林7 |
| VagabondMove | (型名, dst) | 12 |
| VagabondBattle | (型名, defender) | |
| VagabondAid | (型名, faction, base_id, take_item or None) | take_item は ItemKind 8種+None |
| VagabondQuest | (型名, quest_id, reward) | 15×2 |
| VagabondStrike | (型名, faction, target) | target=("soldier",)/("building",kind5)/("token",kind3) |
| VagabondRepair | (型名, kind) | ItemKind 8種 |
| VagabondSpecial | (型名, target or None, base_id or None) | 盗み=(faction,None)/日常業務=(None,base)/隠れ家=(None,None) |
| AllocateHit | (型名, target) | VagabondStrike と同じ target 列挙 |
| VagabondItemChoice | (型名, kind, exhausted, damaged, on_track) | 8×2×2×2=64(不能組合せは死にインデックス) |

概算 size ≈ 1万弱(march 950 + decree move 3040 + aid ~1800 + 残り)。死にインデックス
(実現不能なキー)は許容する — マスクが常に False になるだけで学習に無害。

### 12.3 観測エンコーダ(rl/encoder.py)

- `ObservationSpec(factions: tuple)` がレイアウトを確定し、
  `encode(state, perspective: FactionId) -> np.float32[obs_dim]` を提供する。
- **完全情報**(6c の初期方針): 相手の手札もエンコードする。山札の並び・放浪部族の
  遺跡アイテム内訳は入れない(枚数のみ)。
- perspective はブロックの並べ替えではなく **onehot で示す**(レイアウト固定。
  self-play で両側を同一ネットにするため)。
- ブロック構成(実装者は state.py を読んでフィールドを確定してよい。必須要件は
  「レイアウトが factions から決定的」「全特徴を概ね [0,1] に正規化」
  「`spec.describe() -> {ブロック名: slice}` を提供」の3点):
  - global: phase onehot / turn 正規化 / 手番 onehot / perspective onehot /
    山札・捨て札枚数 / pending 先頭 Decision 型 onehot(actions.py の Decision 全型)+
    actor onehot + remaining/hits 正規化
  - clearing×12: suit onehot / ruin / slots / 派閥別兵士数 / 建物種別数 / トークン種別数 /
    controller onehot
  - faction×参加派閥: vp/30 / 手札の base_id 別カウント / soldiers_supply /
    派閥固有(猫: 木材・残建物・workshop_used、鷲巣: 勅令 column×suit カウント・君主 onehot・
    忠臣・止まり木残、連合: 支援者 suit 別カウント・officers・拠点・支持残、
    部族: ItemTile kind×(表裏/損傷/枠)カウント・relationships onehot・クエスト公開/解決・
    コマ位置 onehot(広場12+樹林7)・キャラ onehot)

### 12.4 環境(rl/env.py)

- `RootEnv(factions, max_turns=300, auto_single=True, seed=None)`。AEC 互換:
  `reset(seed)` / `agent_selection`(= FactionId.value)/ `observe(agent)` →
  `{"observation": np.float32[obs_dim], "action_mask": np.bool_[catalog.size]}` /
  `step(action_index)` / `last()` / `agents` / `rewards` / `terminations` /
  `truncations` / `infos`。
- `auto_single=True`: 合法手が1つだけの間は自動適用して次の意思決定点まで進める
  (エピソード長の短縮。run_game のターン数と一致しなくなる点は仕様)。
- 報酬: 終局時に勝者 +1・他 -1、タイムアウト(max_turns 超過)は全員 0。途中報酬 0。
  `vp_shaping: float = 0.0`(>0 なら自派閥 VP 増分×係数を毎 step 加算、6c で使うかは未定)。
- 乱数: reset で `random.Random(seed)` を1つ作り new_game / apply に注入
  (決定性 10.2 に従い、同一 seed+同一行動列で軌跡完全一致)。
- `infos[agent]` に winner / turns / 最終 vp。

### 12.5 検証(tests/test_rl.py。numpy 未導入環境では skip マーク)

1. カタログ決定性: size 固定、index↔key 全単射、PYTHONHASHSEED を変えた subprocess で
   size と先頭/末尾キーが一致
2. 整合性: 4派閥ランダム対戦 20 試合の全意思決定点で、(a) 全合法手が action_key で
   インデックス化できる (b) mask の True 数 ≧ 1 (c) `action_for(state, i)` が
   合法手に含まれる(mask=True の全 i)
3. env 決定性: 同一 seed・マスク上のランダムサンプリング(独立 rng)で2回走らせ、
   obs/reward/終局が完全一致。obs は全ステップ有限値
4. episode 完走: 4派閥で terminated or truncated まで到達、勝者 reward=+1/-1 の整合

### 12.6 完了条件(subagent の報告に含めること)

1. `python3 -m pytest tests/ -q` 全パス(既存 54+1 にリグレッションなし)
2. catalog.size と obs_dim(4派閥時)の実測値
3. 12.5 の各テスト結果とエピソード長(auto_single 前後の平均 step 数、10 試合程度)
4. 性能: env のランダム rollout 10 試合の所要時間(6c の学習スループット見積りに使う)
5. レビュー注目点(ファイル:行)

## 13. フェーズ6c(前半): PPO self-play 学習コード(Fable 2026-07-11。実装者はこの設計に従うこと)

Mac(CPU/MPS)で**学習ループが正しく回ること**までを本セッションのスコープとする。
本格スケール(10⁷ステップ〜)は 6b の Windows 機(RTX 4080 Super)で同じコードを回す。

### 13.1 スコープと依存

- 新規モジュール: `rl/net.py`(ネットワーク)、`rl/ppo.py`(PPO本体)、
  `rl/nn_policy.py`(bots Policy アダプタ)、`rl/train.py`(CLI エントリ)。
- torch はこれらのモジュールのみに閉じる(catalog/encoder/env は numpy のまま)。
  Mac には `.venv/`(gitignore 済み)に torch 2.8.0 + numpy 2.0.2 導入済み:
  `.venv/bin/python -m rl.train ...` で実行する。
- 対象マッチアップ: **2人戦固定(既定: marquise vs eyrie)**・完全情報(12.3)。
  CLI の `--factions` で任意の組に変更可能な作りにはしておく。

### 13.2 ネットワーク(rl/net.py)

- 共有胴体 MLP: `obs_dim → 512 → 512`(ReLU / 直交初期化 gain=√2)+2ヘッド:
  - policy: `512 → catalog.size(7860)` 線形(gain=0.01)
  - value: `512 → 1`(gain=1.0)
- **両席とも同一ネット**(self-play)。視点は観測の perspective onehot が担う(12.3)。
- マスク適用: `logits.masked_fill(~mask, -1e9)` → Categorical。
  entropy・log_prob もマスク後の分布で計算する。

### 13.3 学習ループ(rl/ppo.py + rl/train.py)

- **収集**: E 個(既定8)の `RootEnv(auto_single=True)` を並べ、agent の区別なく
  「意思決定点=1ステップ」として遷移 `(obs, mask, action, logp, value, actor)` を
  バッファへ。1イテレーション T ステップ(既定 2048、全 env 合算)。
  NN 推論は env 間でバッチする(1推論/意思決定点にしない)。
- **報酬とGAE**: 報酬は終局時 ±1(タイムアウト0)のみ(12.4)。GAE は
  **agent 別のトラジェクトリ列**(同一 env 内で自分の意思決定点だけを繋いだ列)に
  対して計算する(γ=1.0, λ=0.95 を既定: エピソード短く割引不要、勝敗がそのまま
  リターン)。エピソード途中でイテレーションが切れた場合は value でブートストラップ。
- **PPO 更新**: clip=0.2、epochs=4、minibatch=256、lr=2.5e-4(Adam)、
  value 損失係数 0.5(clip 付き)、entropy 係数 0.01、grad clip 0.5。
- **対戦相手**: 純 self-play(両席同一の最新ネット)。過去世代リーグは本格スケール時
  (6c 後半)の課題とし、今回は実装しない。
- **チェックポイント**: `rl_runs/<run名>/ckpt_<update>.pt`(model+optimizer+設定+
  総ステップ数)。`--resume` で再開可。`rl_runs/` は gitignore に追加。
- **ログ**: CSV(`rl_runs/<run名>/log.csv`: update, steps, 平均エピソード長,
  勝率(席別), policy_loss, value_loss, entropy, approx_kl, 秒/更新)。
  TensorBoard は入れない(6b で W&B/TB を判断)。

### 13.4 評価(rl/nn_policy.py)— 既存基盤の再利用

- `NNPolicy(net, spec, catalog, device, greedy=True)` を bots の `Policy` プロトコル
  (`choose(state, legal_actions, rng) -> Action`)として実装:
  encode → mask → argmax(または sample)→ `action_for` で Action に解決。
  これにより**既存の `run_game` / HeuristicBot / RandomBot がそのまま評価対戦相手になる**。
- `rl/train.py --eval-every N`(既定10更新ごと): 学習席=先手・後手それぞれで
  vs RandomBot / vs HeuristicBot を各32試合(`run_game`、seed 固定列)し勝率を CSV へ。
- 学習を回さない単独評価コマンド `python -m rl.eval --ckpt ... --games ...` も用意する。

### 13.5 検証と完了条件(subagent の報告に含めること)

1. `python3 -m pytest tests/ -q`(システム python=torch なし)が全パス
   (torch 必要テストは skipif で自動 skip)。`tests/test_ppo.py` を追加:
   (a) マスク分布: mask=False の行動の確率が 0 (b) GAE の手計算一致(小さな固定列)
   (c) NNPolicy が合法手のみ返す(ランダム初期化ネットで10手)— いずれも torch 必須なので skipif
2. スモーク学習(marquise vs eyrie): `.venv/bin/python -m rl.train --total-steps 20000`
   程度を実走し、(a) クラッシュしない (b) entropy が初期値から低下 (c) approx_kl が
   発散しない(<0.1 目安) (d) ckpt 保存と resume が動く、を確認して数値を報告
3. スループット(steps/秒、CPU と MPS 両方。MPS が遅ければ CPU 既定で可)
4. スモーク後の ckpt で vs RandomBot 32試合の勝率(学習が短すぎて勝てなくてよい。
   評価パイプラインが動くことの確認が目的)
5. レビュー注目点(ファイル:行)

### 13.6 6b への引き継ぎ事項(このセッションでは実装しない)

- Dockerfile(CUDA 版 torch)+ `pip install -e .[rl]` + `python -m rl.train` が
  そのまま動くこと(コードは OS 非依存に書く。パス結合は os.path)
- device 自動選択: `--device auto` = cuda > mps > cpu

## 14. ルール完全性A: 圧倒カード(3.3)+共闘軍(9.2.8)(Fable 2026-07-11。実装者はこの設計に従うこと)

ルールの正: `rules/common.md` 3.3(および 2.1.3)、`rules/vagabond.md` 9.2.8 / 9.2.9.III.d。
3〜4人戦の勝利条件を完全化する(2人戦は圧倒4枚を山札から除外済み=5.1.3、変更なし)。

### 14.1 状態モデル

- `FactionState` に共通フィールド **`dominance_card: Optional[str] = None`** を追加
  (発動して公開中の圧倒カードのインスタンスID。3.3.2: 置換不可なので None→非None の一方向)。
- `GameState` に **`dominance_aside: Tuple[str, ...] = ()`** を追加
  (3.3.3 でコスト消費されゲーム盤の横に置かれた圧倒カード)。
- `VagabondState` に **`coalition_with: Optional[FactionId] = None`** を追加(9.2.8)。
- **カード保存則(state.validate)の拡張**: 54枚の勘定に
  `各fsのdominance_card` と `dominance_aside` の2ゾーンを加える。

### 14.2 VP凍結の中央集約(発動の帰結)

3.3.1「以後VPを獲得することもできない」を一点で強制するため、
**`engine/mechanics.py` に `award_vp(state, faction, delta) -> GameState`** を新設し、
既存の直接 `vp=fs.vp+n` 書き込み(battle._award_vp / apply._apply_build系 /
crafting / eyrie(止まり木VP・内乱のVP喪失) / alliance(支持拡大) /
vagabond(悪名・探索・援助・クエスト・クラフト)の**全11箇所**)をこれ経由に置換する:

- `fs.dominance_card is not None` → no-op(VP凍結)
- 放浪部族で `coalition_with is not None` → no-op(9.2.8 の凍結)
- それ以外 → `vp = max(0, vp + delta)`(VP非負クランプを共通化。鷲巣の恥辱 7.7.1 の
  クランプは既存挙動と同一になることを確認する)

### 14.3 捨て山リダイレクト(3.3.3 一般化)

公式法典(英語版 Law)3.3.3 は「圧倒カードが**捨て山に置かれるとき**は常に盤の横へ」
(日本語抽出はコスト消費のみ言及だが一般則を採用。`rules/data-verification.md` に記録)。

- `engine/mechanics.py` に **`to_discard(state, card_id) -> GameState`** を新設:
  圧倒カード(`cards.get(cid).is_dominance`)なら `dominance_aside` へ、他は捨て山へ。
- 既存の `state.discard + (...)` 直書き(mechanics.discard_card / eyrie内乱のパージ /
  alliance の支援者支払い・支出・調整 / vagabond の日常業務(逆方向=取得なので対象外)等、
  **「捨て山へ入れる」約8箇所**)をこれ経由に置換する。
  山札切れの再シャッフル(discard→deck)は対象外(そのまま)。

### 14.4 新アクション(actions.py / legal.py / apply.py)

昼光の共通自由アクションとして **legal.py に共通フック**を置く(派閥ロジック側には
足さない。pending が空・phase==DAYLIGHT・手番派閥のときに通常合法手へ追加):

| Action | 合法条件 | 効果 |
|---|---|---|
| `ActivateDominance(card_id)` | 手番派閥のVP≧10 / 手札に圧倒カード / `fs.dominance_card is None` / **放浪部族は不可**(9.2.8) | 手札→`fs.dominance_card`。以後VP凍結(14.2) |
| `TakeDominance(spend_card_id, dominance_id)` | `dominance_aside` に対象があり、手札に**同じ動物種**のカード(鳥圧倒は鳥カードのみ、3.3.4) | 支払カードは捨て山(14.3経由)、圧倒カードを手札へ |
| `VagabondCoalition(card_id, partner)` | 放浪部族 / **4人以上戦** / 手札に圧倒カード / `coalition_with is None` / partner=「圧倒未発動かつ共闘未結成の他派閥のうち最低VP」(同点は複数候補を列挙=部族が選択) | カードは公開扱いで`fs.dominance_card`に保持(保存則の勘定用)。`coalition_with=partner`。以後VP凍結。partnerが**敵対なら無関心(0)へ**(9.2.9.III.d) |

### 14.5 勝利判定

- **圧倒勝利(3.3.1.I/II)**: `game.py` のターン開始処理で、**手番派閥の鳥歌フェイズ
  開始時**(begin_phase の前)に判定する(3.8 で予約済みのフック点):
  - 一般(fox/rabbit/mouse): その動物種の広場を**3ヶ所以上支配**(`state.controller`)
  - 鳥: **対角の隅広場2ヶ所**を支配(map の corner が NW+SE または NE+SW)
  - 成立なら `winner=手番派閥, finished=True`
- **共闘勝利(9.2.8)**: 勝者確定箇所(30VP到達・圧倒勝利)で、
  `winner` が部族の `coalition_with` と一致するなら部族も勝者。
  `GameState.winners: Tuple[FactionId, ...]`(プロパティ)を追加し、
  `run_game` の Result に `winners` を追加する。**simulation の games テーブルは
  winner(主勝者)のまま変更しない**(共闘の共同勝利は当面 DB に記録しない=既知の割り切り)。
- 30VP勝利の判定対象から `dominance_card` 発動済み派閥を除外(VP凍結により実質不変だが明示)。

### 14.6 bot への影響(最小対応)

- RandomBot: 対応不要(新アクションが選択肢に混ざるだけ)。
- HeuristicBot: `bots/heuristic/evaluate.py` の共通項に**圧倒進捗項**を追加:
  `fs.dominance_card` 発動中なら `-20 + 50 × (条件充足広場数 / 必要数)`
  (必要数: 一般=3、鳥=2。無意味な発動を抑止しつつ、達成間際なら発動を促す)。
  共闘軍は評価項なし(凍結後は共通項のVPが動かなくなるだけ)。
- 1-ply では圧倒勝利の多ターン維持は見えない(既知の限界。RLに委ねる)。

### 14.7 RL への影響(別タスクで実施)

- `rl/catalog.py` に新キー: `ActivateDominance`=(型名, base_id[圧倒4種のみに限定してよい])
  / `TakeDominance`=(型名, spend_base_id, dominance_base_id) / `VagabondCoalition`=(型名, base_id, partner)。
  **catalog.size が変わる=既存 ckpt(mac-500k)と非互換**(2人戦学習には無関係だが
  policy ヘッド幅が変わる)。`rl/catalog.py` に `CATALOG_VERSION` 定数を導入し ckpt に保存、
  resume 時に不一致なら明示エラーにする。
- `rl/encoder.py`: global ブロックに `dominance_aside` の4フラグ、
  faction ブロックに「発動中の圧倒 suit onehot(4)+共闘相手 onehot(部族のみ、n_fac)」を追加。

### 14.8 検証(selftest 追加+pytest)

1. 発動: VP9 で非合法・VP10 で合法。発動後は手札から消え、`award_vp` が no-op になる
2. 一般圧倒勝利: 一致動物種3広場支配で自鳥歌開始時に勝利(2広場では勝利しない)
3. 鳥圧倒勝利: NW+SE 支配で勝利、NW+NE では勝利しない
4. コスト消費→盤脇→3.3.4 で回収(同動物種カード消費。鳥圧倒に非鳥カードは非合法)
5. 夕闇の手札調整で圧倒カードを捨てると盤脇へ行く(捨て山に入らない)
6. 共闘軍: 3人戦では非合法 / 4人戦で最低VP対象(同点は選択肢が複数出る)/
   敵対派閥と結成→無関心へ / 相手30VP勝利で winners に部族が入る / 結成後VP凍結
7. カード保存則54枚が dominance_card / dominance_aside 込みで成立(validate)
8. 既存 pytest 58+1 にリグレッションなし(2人戦=圧倒除外の挙動不変)

### 14.9 完了条件(subagent の報告に含めること)

selftest 新シナリオの結果 / pytest 全件 / 4派閥 smoke 100試合 --validate クラッシュゼロ
/ 4派閥ランダムbot対戦で圧倒勝利・共闘勝利が実際に発生した回数(発生ゼロなら要調査)
/ レビュー注目点(ファイル:行)

## 15. ルール完全性B: 猫の簡略化バッチ(Fable 2026-07-11。実装者はこの設計に従うこと)

ルールの正: `rules/cat.md` 6.2.2 / 6.2.3 / 6.5.2、`rules/common.md` 4.3.1.II / 2.1.1。
4項目を一括で解消する。既存の decision パターン(3.2)を踏襲し、新規ファイルは作らない。

### 15.1 城砦の配置禁止(6.2.2)

- `GameState` にヘルパ **`placement_blocked(faction, cid) -> bool`** を追加:
  「faction が猫以外」かつ「cid に猫の城砦トークン(T_KEEP)がある」とき True。
- **配置(placement)のみ禁止。移動は合法**(6.2.2 明文)。適用箇所は候補生成のみ:
  - 鷲巣: `EyriePlaceRoost`(7.4.3)と `EyrieDecreeBuild`(7.5.2.IV)の対象広場
  - 連合: `AllianceSpreadSympathy`(8.4.2、戒厳令分岐含む)と `AllianceRevolt`(8.4.1、
    支持が置けない以上実質発生しないが防御的に)
  - 鷲巣の募兵・連合の作戦募兵は止まり木/拠点の存在が前提で、それら自体が
    置けなくなるため対応不要(理由をコメントに残す)
- **既存 xfail テスト(tests/test_marquise.py)はルール誤読**(移動を違法と主張して
  いるが 6.2.2 は「そこへ移動させることは可能」)。xfail を外して**削除し**、正しい
  2テストに差し替える: (a) 城砦広場への `AllianceSpreadSympathy` が非合法
  (b) 城砦広場への移動(AllianceOpMove)は合法

### 15.2 行軍=2移動まで(6.5.2)

- 新 Decision **`MarquiseMarchDecision(actor=猫)`**(任意の2移動目)+
  新 Action **`MarquiseSkipMove`**(パラメータなし=2移動目を行わない)。
- `apply(MarquiseMarch)` を分岐:
  - pending 先頭が `MarquiseMarchDecision` → pop して移動のみ実行(アクション消費なし)
  - 通常(1移動目)→ アクション1消費 → **先に** `MarquiseMarchDecision` を push →
    移動を実行(移動が蜂起 8.2.6 の OutrageDecision を積む場合、それがスタック上に
    載り先に解決される。push順が重要)
- `legal.py` の decision 分岐: `MarquiseMarchDecision` → 既存の行軍候補生成
  (marquise._march_actions)+ `MarquiseSkipMove`。候補ゼロでも skip があるので詰まない。
- `MarquiseSkipMove` の適用 = pop のみ。

### 15.3 野戦病院(6.2.3)

トリガーは「猫兵士が1つの広場から除去された」**イベント単位**(1枚のカードで
そのイベントの除去兵士全てを城砦広場へ)。エンジンは1個ずつ除去するため、
イベント境界で集計して1回だけ決定を出す:

- `AllocateHitsDecision` にフィールド追加: `ctx: BattleCtx=None` / `roll_after: bool=False`
  / `removed_soldiers: int=0`(このデシジョン処理中に除去した猫兵士数)。
- `battle.allocate_hit`: victim=猫 かつ兵士除去なら removed_soldiers を+1して積み直す。
  デシジョンが尽きたら(残ヒット0 or 配置物なし)**`_finish_allocation(state, dec, rng)`**:
  1. victim=猫 かつ removed_soldiers>0 → `maybe_field_hospital(...)`(下記)が
     デシジョンを積んだら ctx/roll_after を引き継いで return
  2. `roll_after=True` かつ戦場に攻撃側兵士が残っている → `roll_battle(ctx)`
     (全滅なら戦闘終了=4.3.1.II)
- 新 Decision **`FieldHospitalDecision(actor=猫, clearing, count, ctx=None, roll_after=False)`**
  + 新 Action **`MarquiseFieldHospital(card_id: Optional[str])`**(None=使わない。
  AmbushChoice と同パターン)。
- `marquise.maybe_field_hospital(state, clearing, count, ctx=None, roll_after=False)`:
  城砦がマップ上にあり、手札に一致カード(広場の動物種 or 鳥=ワイルド 2.1.1)が
  あるときだけ FieldHospitalDecision を push(なければ no-op を返し、呼び元が
  roll_after を処理)。選択肢 = 一致カード(base_id で dedup)+ None。
- 適用: カードあり → discard_card(3.3.3経由)+ サプライから count 個を城砦広場へ
  配置(remove_piece で既にサプライへ戻っている分を取り出す)。None → 何もしない。
  いずれも後処理として 15.3-2 と同じ roll_after 判定を行う。
- **戦闘以外のイベント**にも適用(6.2.3 は除去全般):
  - 連合の反乱(alliance._remove_all_enemies): ループで除去した猫兵士数を集計し、
    最後に maybe_field_hospital(clearing, count)
  - 部族の狙撃(vagabond.apply_strike): 猫兵士1除去なら maybe_field_hospital(count=1)

### 15.4 奇襲2ヒットの除去対象選択(4.3.1.II)

- `_apply_ambush_hits` の非放浪部族分岐を `_auto_remove`(兵士優先の自動選択)から
  **`AllocateHitsDecision(actor=攻撃側, victim=攻撃側, hits=2, source=防御側,
  clearing, ctx=ctx, roll_after=True)`** の push に変更(4.3.4 の兵士優先制約は
  allocate_options が既に強制する)。
- 解決後の継続は 15.3 の `_finish_allocation` に統合: 攻撃側兵士が戦場に残っていれば
  ロールへ、全滅なら戦闘終了。猫が攻撃側なら野戦病院(15.3)が間に挟まり、
  病院で城砦へ戻した兵士は戦場にいないため全滅判定はそのまま正しい。
- 放浪部族攻撃側の既存分岐(ItemDamageDecision + roll_after)は変更しない。

### 15.5 RL追随(別タスク。フェーズRメモの手順=5247e50 が手本)

- catalog: `MarquiseSkipMove`=(型名,) / `MarquiseFieldHospital`=(型名, base_id or None)。
  `CATALOG_VERSION = 3`。
- encoder: `_DECISION_TYPES` に `MarquiseMarchDecision` / `FieldHospitalDecision` を追加。

### 15.6 検証(selftest 追加+pytest 差し替え)

1. 行軍: 1回の MarquiseMarch でアクション1消費 → 2移動目の選択肢(+skip)が出る →
   2移動目はアクション消費なし / skip で通常進行
2. 野戦病院: 戦闘で猫兵士2除去 → 一致カード支払いで城砦広場に2個出現・カードは捨て山 /
   None 選択でサプライのまま
3. 野戦病院の前提: 城砦除去済み or 一致カードなしではデシジョン自体が出ない
4. 奇襲: 受け手(攻撃側)が2ヒットの対象を選択(兵士優先)→ 生存ならロール継続、
   全滅なら戦闘終了
5. 城砦: 支持拡大・止まり木配置(EyriePlaceRoost/EyrieDecreeBuild)が城砦広場で
   候補から消える / 移動は合法(15.1 の差し替えテスト)
6. 既存 pytest 全パス(xfail は差し替えで消える)+ 4派閥 smoke 100試合 --validate +
   並列/直列の決定性一致

### 15.7 完了条件(subagent の報告に含めること)

selftest 新シナリオ結果 / pytest 全件(xfail 0 になること) / smoke 100試合 /
決定性検証 / ランダム4派閥での野戦病院発動回数・行軍2移動使用率(参考値) /
レビュー注目点(ファイル:行)

---

## 16. フェーズ6c(後半): リーグ戦=過去世代対戦相手プール(Fable 2026-07-11。実装者はこの設計に従うこと)

**目的**: 純self-playの非定常性(忘却・循環)対策と、片席全敗時の学習信号消失対策
(mac-500k で鷲巣席の報酬がほぼ全て -1 になり advantage が潰れた)。
エピソードの一部で片席を凍結した過去世代 ckpt に差し替え、多様な強さの相手との
対戦を混ぜる。ROOT は同一派閥のミラー戦が存在しないが、リーグ戦は
「学習ネット席 vs 凍結ネット席」の異派閥対戦なので制約にならない。

### 16.1 スコープ

- 新規: `rl/league.py`(`OpponentPool`)+ `tests/test_league.py`。
- 変更: `rl/ppo.py`(collect の対戦相手差し替え)、`rl/train.py`(CLI・snapshot・
  ログ列・resume)。net/encoder/catalog/env は**変更しない**。

### 16.2 OpponentPool(rl/league.py)

- スナップショット = 凍結した `ActorCritic`(eval モード、`requires_grad_(False)`)。
  作成時に `run_dir/league/snap_<update>.pt`(model state_dict のみ)へ保存し、
  メモリ上にもネットを保持(pool-max 20 × ~30MB は許容)。
- API:
  - `add(net, update)` — 現ネットの deepcopy を凍結して追加。上限超過時は
    **ランダムに1つ間引く**(FIFO でなく、履歴全体をほぼ一様にカバーするため)。
    間引いたスナップショットは**ディスクのファイルも削除**する(長期 run での蓄積防止。
    過去 ckpt の league_meta が参照していても resume の warn+skip で吸収される)。
  - `sample(rng) -> (snapshot_id, net)` — 一様サンプル。空なら None。
  - `save_meta() / load(run_dir, meta, device)` — resume 用
    (メタ= `[(update, ファイル名), ...]` を ckpt に含める)。
- サンプリング重み付け(PFSP)は導入しない。効果不足が観測されたら将来検討。

### 16.3 collect の変更(rl/ppo.py)

- `_Worker` に対戦相手割当を追加: `opponent: Optional[(agent名, net)]`。
  **エピソード開始時(reset 直後)** に league 用 rng
  (`np.random.Generator`, seed=`cfg.seed`由来で torch と分離)で抽選:
  確率 `league_prob` かつプール非空なら、席(0/1)を一様に選び凍結ネットを割当。
  それ以外は純 self-play(従来どおり)。
- 推論バッチ: 各ステップで actor が学習ネット担当の env と、凍結ネット担当の env を
  分け、**学習ネット分は従来どおり1バッチ**、凍結ネット分は snapshot_id ごとに
  まとめて `torch.no_grad()` で推論(**sample で行動**。greedy にしない=多様性維持)。
- **凍結ネット側の遷移はバッファに入れない**(traj に add しない)。
  `steps`(rollout_steps のカウンタ)は**学習ネットの意思決定点のみ**進める。
  凍結側の意思決定点は `_Worker.ep_steps` にだけ数える(エピソード長統計は従来定義)。
- `_flush_episode` / `_bootstrap_open`: 凍結側 agent の traj は常に空なので
  既存の `len(tr)==0: continue` がそのまま効く。勝敗統計は分離する(16.4)。
- GAE・PPO 更新は無変更(league 由来の遷移も同じバッチに混ぜて正規化してよい)。

### 16.4 統計とログ

- `RolloutStats` を拡張: self-play エピソードは従来の `seat_wins` に、league
  エピソードは `league_episodes / league_wins(学習ネット視点) / league_draws` に計上。
  既存の `winrate_seat0/1` は **self-play エピソードのみ**から算出(意味を変えない)。
- `log.csv` に列追加: `league_episodes, league_winrate`。
  既存 run の log.csv と列が変わるため、**新規 run で使う前提**(追記互換は不要)。

### 16.5 CLI と snapshot(rl/train.py)

- 追加フラグ: `--league-prob`(既定 **0.5**。0 で無効=従来挙動)/
  `--league-pool-max`(既定 20)/ `--league-snapshot-every`(既定 20 更新。
  save-every とは独立)。
- snapshot タイミング: `update % league_snapshot_every == 0` の更新後に `pool.add`。
  プールが空の序盤は自動的に純 self-play になる(それで正しい)。
- ckpt に `league_meta`(16.2)を追加。resume 時は `run_dir/league/` から再構築
  (ファイル欠損は警告してスキップ)。league rng の状態は保存しない
  (resume 後の抽選列が変わるのは許容。既存の np.random シャッフルと同水準)。

### 16.6 検証と完了条件(subagent の報告に含めること)

1. `tests/test_league.py`(torch 必須なので skipif):
   (a) pool の add/上限間引き/sample の決定性(rng 固定)
   (b) league エピソードで凍結側 agent の遷移がバッファに入らないこと
       (collect 後の batch サイズ=学習側意思決定点数と一致)
   (c) `--league-prob 0` が従来の純 self-play と同一挙動(同 seed で batch 一致)
2. `python3 -m pytest tests/ -q` 全パス(torch なし環境では league テストが skip)
3. スモーク: `.venv/bin/python -m rl.train --total-steps 30000 --league-prob 0.5
   --league-snapshot-every 3` 程度で (a) クラッシュしない (b) snapshot 生成と
   league_episodes>0 を log.csv で確認 (c) ckpt 保存 → resume でプール再構築が動く
4. スループット低下の実測(league_prob=0.5 で steps/s がどの程度落ちるか)
5. レビュー注目点(ファイル:行)
