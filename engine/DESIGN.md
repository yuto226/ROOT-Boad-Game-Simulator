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
| VagabondAid(faction, card_id, take_item) | 任意1 | 9.5.4。現在広場一致の手札(鳥可)を相手の手札へ。相手の作成アイテム(fs.items)から1枚取得可(任意、Noneで取らない)。関係処理は 8.5 |
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
