"""アクション(純データ, 3.3)とデシジョン(保留スタック要素, 3.2)。

Action はプレイヤーIDと必要パラメータのみを持つ。適用ロジックは
:mod:`engine.apply` にある。docstring に原文番号を併記する。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .types import FactionId, Suit


# ============================================================
#  Action(手番/デシジョンに対する選択)
# ============================================================
@dataclass(frozen=True)
class Action:
    """全アクションの基底。"""

    player: FactionId


@dataclass(frozen=True)
class EndPhase(Action):
    """現フェイズを終了し次フェイズ(or 次プレイヤー)へ(1.4.1)。"""


@dataclass(frozen=True)
class CraftCard(Action):
    """クラフトアクション(4.1)。"""

    card_id: str


@dataclass(frozen=True)
class DeclareBattle(Action):
    """戦闘を宣言(4.3)。"""

    clearing: int
    defender: FactionId


# --- 圧倒カード / 共闘軍(共通, 3.3 / 9.2.8) ---
@dataclass(frozen=True)
class ActivateDominance(Action):
    """圧倒カードの発動(3.3.1)。手札→公開。以後VP凍結。放浪部族は不可(9.2.8)。"""

    card_id: str


@dataclass(frozen=True)
class TakeDominance(Action):
    """盤脇の圧倒カードの回収(3.3.4)。一致動物種のカード1枚を消費する。"""

    spend_card_id: str
    dominance_id: str


@dataclass(frozen=True)
class VagabondCoalition(Action):
    """共闘軍の結成(9.2.8, 4人以上戦)。圧倒カードを公開し最低VPの派閥と共闘。"""

    card_id: str
    partner: FactionId


# --- immediate/persistent クラフト効果(18.3 / 18.4) ---
@dataclass(frozen=True)
class UseCraftedEffect(Action):
    """継続効果カードの使用(18.3 フェイズ効果 / 18.4 戦闘効果)。

    ``card_key`` は base_id。フェイズ効果(royal-claim / stand-and-deliver /
    better-burrow-bank / tax-collector / command-warren / cobbler)は
    target_faction/target_clearing のうち該当するものを使う。戦闘効果
    (armorers / sappers / brutal-tactics)はどちらも使わない。
    """

    card_key: str = ""
    target_faction: Optional[FactionId] = None
    target_clearing: Optional[int] = None


@dataclass(frozen=True)
class SkipBattleEffects(Action):
    """戦闘効果使用ステージ(18.4, 4.3.3)でのパス。"""


# --- 猫野侯国固有(第6章) ---
@dataclass(frozen=True)
class MarquiseBuild(Action):
    """建設アクション(6.5.4)。"""

    clearing: int
    kind: str  # sawmill|workshop|recruiter


@dataclass(frozen=True)
class MarquiseRecruit(Action):
    """募兵アクション(6.5.3)。1ターン1回。"""


@dataclass(frozen=True)
class MarquiseMarch(Action):
    """行軍アクションの1移動(6.5.2, 4.2)。

    行軍は最大2移動(6.5.2)。1移動目はアクションを消費し
    ``MarquiseMarchDecision`` を積む。2移動目は同アクションの応答として
    実行され、アクションは消費しない(apply 側で pending 先頭型で判別)。
    """

    src: int
    dst: int
    count: int


@dataclass(frozen=True)
class MarquiseSkipMove(Action):
    """行軍の2移動目を行わない(6.5.2)。``MarquiseMarchDecision`` の応答。"""


@dataclass(frozen=True)
class MarquiseFieldHospital(Action):
    """野戦病院(6.2.3)。card_id=None は使わない(AmbushChoice と同パターン)。

    一致カード(除去元広場の動物種 or 鳥=ワイルド 2.1.1)を消費すると、
    直前に除去された猫兵士を城砦広場へ配置する。
    """

    card_id: Optional[str] = None


@dataclass(frozen=True)
class MarquiseLabor(Action):
    """労働アクション(6.5.5)。製材所広場と一致するカードを消費し木材1配置。"""

    clearing: int
    card_id: str


@dataclass(frozen=True)
class MarquisePlayBirdCard(Action):
    """鳥カード消費による追加アクション権の獲得(6.5)。"""

    card_id: str


@dataclass(frozen=True)
class MarquiseChooseWood(Action):
    """建設の木材支払い1個の広場選択(6.5.4.II, 19.1)。

    ``WoodPaymentDecision`` の応答。候補=建設広場から連結の支配下広場の
    うち木材が1個以上ある広場。
    """

    clearing: int


# --- デシジョン応答アクション ---
@dataclass(frozen=True)
class AmbushChoice(Action):
    """奇襲する/しない、または妨害する/しない(4.3.1)。card_id=None で「しない」。"""

    card_id: Optional[str] = None


@dataclass(frozen=True)
class AllocateHit(Action):
    """ヒット1つの割り振り(4.3.4)。

    target: ("soldier",) / ("building", kind) / ("token", kind)
    """

    target: Tuple


@dataclass(frozen=True)
class DiscardCard(Action):
    """手札上限超過分の破棄(6.6)。"""

    card_id: str


@dataclass(frozen=True)
class SetupChooseKeep(Action):
    """城砦の隅選択(6.3.2)。"""

    corner: str


# --- 鷲巣王朝固有(第7章) ---
@dataclass(frozen=True)
class EyrieChooseCorner(Action):
    """開始時広場の隅選択(7.3.2)。"""

    corner: str


@dataclass(frozen=True)
class EyrieChooseLeader(Action):
    """君主カードの選択(7.3.3 セットアップ / 7.7.3 失脚)。"""

    leader: str


@dataclass(frozen=True)
class EyrieAddToDecree(Action):
    """勅令追加(7.4.2)。column: 0=募兵 1=移動 2=戦闘 3=建設。"""

    card_id: str
    column: int


@dataclass(frozen=True)
class EyrieSkipDecree(Action):
    """勅令追加の2枚目を追加しない(7.4.2, 1枚目は強制)。"""


@dataclass(frozen=True)
class EyriePlaceRoost(Action):
    """止まり木確保(7.4.3): 止まり木1+兵士3の配置先。"""

    clearing: int


@dataclass(frozen=True)
class EyrieRecruit(Action):
    """勅令の募兵(7.5.2.I)。カリスマは兵士2個(7.8.2)。"""

    card_id: str
    clearing: int


@dataclass(frozen=True)
class EyrieDecreeMove(Action):
    """勅令の移動(7.5.2.II, 4.2)。"""

    card_id: str
    src: int
    dst: int
    count: int


@dataclass(frozen=True)
class EyrieDecreeBattle(Action):
    """勅令の戦闘(7.5.2.III, 4.3)。"""

    card_id: str
    clearing: int
    defender: FactionId


@dataclass(frozen=True)
class EyrieDecreeBuild(Action):
    """勅令の建設(7.5.2.IV): 止まり木タイル1枚を配置。"""

    card_id: str
    clearing: int


@dataclass(frozen=True)
class EyrieTurmoil(Action):
    """内乱(7.7)。実行不能な勅令の発生時の強制アクション。"""


# --- 森林連合固有(第8章) ---
@dataclass(frozen=True)
class AllianceRevolt(Action):
    """反乱(8.4.1)。支持広場に拠点を設立する。"""

    clearing: int


@dataclass(frozen=True)
class AllianceSpreadSympathy(Action):
    """支持拡大(8.4.2)。非支持広場へ支持トークンを配置する。"""

    clearing: int


@dataclass(frozen=True)
class AllianceMobilize(Action):
    """動員(8.5.2)。手札1枚を支援者ボックスへ。"""

    card_id: str


@dataclass(frozen=True)
class AllianceTrain(Action):
    """訓練(8.5.3)。拠点動物種と一致する手札1枚を捨て、指揮官1個を得る。"""

    card_id: str


@dataclass(frozen=True)
class AllianceOpMove(Action):
    """作戦行動・移動(8.6.1.I, 4.2)。"""

    src: int
    dst: int
    count: int


@dataclass(frozen=True)
class AllianceOpBattle(Action):
    """作戦行動・戦闘(8.6.1.II, 4.3)。"""

    clearing: int
    defender: FactionId


@dataclass(frozen=True)
class AllianceOpRecruit(Action):
    """作戦行動・募兵(8.6.1.III)。拠点のある広場に兵士1個を配置。"""

    clearing: int


@dataclass(frozen=True)
class AllianceOpOrganize(Action):
    """作戦行動・組織(8.6.1.IV)。非支持広場の自兵士1個を除去し支持トークン配置。"""

    clearing: int


@dataclass(frozen=True)
class AllianceEndOps(Action):
    """作戦行動を終え手札調整(8.6.2)へ進む宣言。"""


@dataclass(frozen=True)
class OutragePay(Action):
    """蜂起の支払い(8.2.6)。card_id=None は一致カードなしで山札トップ補充。"""

    card_id: Optional[str] = None


@dataclass(frozen=True)
class AllianceDiscardSupporter(Action):
    """全拠点喪失時の支援者5枚調整(8.2.4)での1枚破棄。"""

    card_id: str


@dataclass(frozen=True)
class AllianceSpendSupporter(Action):
    """支援者1枚の支払い(8.4.1 / 8.4.2, 19.2)。``SupporterPaymentDecision`` の応答。

    ``suit`` は実際に払うカードの suit(一致suit or BIRD)。同 suit 内の
    どのカードを払うかは決定的(supporters タプルの先頭一致)=自動のまま。
    """

    suit: Suit


# --- 放浪部族固有(第9章) ---
@dataclass(frozen=True)
class VagabondChooseCharacter(Action):
    """キャラクター選択(9.3.1)。"""

    character: str  # thief|tinker|ranger


@dataclass(frozen=True)
class VagabondChooseForest(Action):
    """放浪者コマの開始樹林選択(9.3.2)。"""

    forest: int


@dataclass(frozen=True)
class VagabondSlip(Action):
    """潜入(9.4.2)。無償・任意の移動。dst_forest=True なら樹林へ。"""

    dst: int
    dst_forest: bool = False


@dataclass(frozen=True)
class VagabondMove(Action):
    """移動アクション(9.5.1)。M1(+敵対兵士のいる広場へは追加M1)。

    移動先は隣接広場のみ(樹林へは移動不可, 9.5.1)。
    """

    dst: int


@dataclass(frozen=True)
class VagabondBattle(Action):
    """戦闘アクション(9.5.2)。S1。現在広場で戦闘。"""

    defender: FactionId


@dataclass(frozen=True)
class VagabondExplore(Action):
    """探索アクション(9.5.3)。F1。現在広場の遺跡アイテム獲得+1VP。"""


@dataclass(frozen=True)
class VagabondAid(Action):
    """援助アクション(9.5.4)。任意アイテム1。手札1枚を相手へ、相手の作成
    アイテムを1枚取得可(take_item=ItemKind値 or None)。"""

    faction: FactionId
    card_id: str
    take_item: Optional[str] = None


@dataclass(frozen=True)
class VagabondQuest(Action):
    """クエストアクション(9.5.5)。クエスト記載の2アイテム消費。
    reward="vp"(同種解決数ぶん) or "cards"(2ドロー)。"""

    quest_id: str
    reward: str


@dataclass(frozen=True)
class VagabondStrike(Action):
    """狙撃アクション(9.5.6)。C1。現在広場の兵士1個、または兵士のいない
    プレイヤーの建物/トークン1個を除去。"""

    faction: FactionId
    target: Tuple  # ("soldier",) / ("building", kind) / ("token", kind)


@dataclass(frozen=True)
class VagabondRepair(Action):
    """修理アクション(9.5.7)。H1。損傷1枚をかばんへ(裏表維持)。"""

    kind: str


@dataclass(frozen=True)
class VagabondSpecial(Action):
    """特別アクション(9.5.9)。F1。キャラクターに応じて:
    盗み(target=対象派閥) / 日常業務(card_id=捨て山の一致カード) / 隠れ家(引数なし)。
    """

    target: Optional[FactionId] = None
    card_id: Optional[str] = None


@dataclass(frozen=True)
class VagabondExhaustItem(Action):
    """援助(9.5.4)の「任意のアイテム1枚を使用」の種類選択(19.3)。

    ``VagabondPayItemDecision`` の応答。kind=ItemKind 8種。候補=未使用・
    非損傷のアイテム種。同 kind 内はかばんエリア優先で自動(配置枠の T/X/B は
    使うとかばんへ移動し回復ボーナス 9.4.1 等を失うため、かばん優先が弱支配)。
    """

    kind: str


@dataclass(frozen=True)
class VagabondRepairItem(Action):
    """隠れ家(D.3.2)の「3枚まで修理」の1枚選択(19.3)。

    ``VagabondRepairDecision`` の応答。kind=ItemKind 8種。同 kind 内は
    表向き優先で自動(修理は裏表を変えないため、表向きを直す方が弱支配)。
    """

    kind: str


@dataclass(frozen=True)
class VagabondItemChoice(Action):
    """回復(9.4.1)/損傷(9.2.7)/上限除外(9.6.4)のアイテム選択。

    key はアイテムタイルの正規化シグネチャ (kind, exhausted, damaged, on_track)。
    どのデシジョンへの応答かは pending 先頭で判別する(AmbushChoice と同方式)。
    """

    key: Tuple = ()


# ============================================================
#  Decision(保留スタック要素, 3.2)。各 Decision は actor を持つ。
# ============================================================
@dataclass(frozen=True)
class BattleCtx:
    """戦闘コンテキスト(不変, 3.6)。"""

    attacker: FactionId
    defender: FactionId
    clearing: int
    ambush_used: bool = False
    #: 戦闘効果(4.3.3, 18.4)による追加ヒットの累計。ロール由来ヒット(armorers が
    #: 軽減できる対象)とは別勘定にし、armorers 使用後も減らない。
    #: atk_extra_hits=攻撃側が与える追加(brutal-tactics)、
    #: def_extra_hits=防御側が与える追加(sappers)。
    atk_extra_hits: int = 0
    def_extra_hits: int = 0


@dataclass(frozen=True)
class Decision:
    """全デシジョンの基底。actor が選択の担当プレイヤー。"""

    actor: FactionId


@dataclass(frozen=True)
class SetupKeepDecision(Decision):
    """城砦の隅を選ぶ(6.3.2)。"""


@dataclass(frozen=True)
class AmbushDefenderDecision(Decision):
    """防御側の奇襲(4.3.1 第1ステップ)。"""

    ctx: BattleCtx = None


@dataclass(frozen=True)
class AmbushAttackerDecision(Decision):
    """攻撃側の奇襲妨害(4.3.1.I)。"""

    ctx: BattleCtx = None


@dataclass(frozen=True)
class AllocateHitsDecision(Decision):
    """ヒットの割り振り(4.3.4)。actor=victim が自コマを除去する。

    ``ctx``/``roll_after`` は奇襲2ヒット(4.3.1.II)の後にロールへ継続する
    ための情報(4.3.4 の兵士優先は allocate_options が強制する)。
    ``removed_soldiers`` はこのデシジョン処理中に除去した猫兵士数で、
    イベント境界で野戦病院(6.2.3)を1回だけ発動するための集計に使う。
    """

    victim: FactionId = None
    hits: int = 0
    source: FactionId = None    # ヒットを与えた側(建物/トークン除去VPの受け手)
    clearing: int = 0
    ctx: BattleCtx = None
    roll_after: bool = False
    removed_soldiers: int = 0


@dataclass(frozen=True)
class BattleEffectsDecision(Decision):
    """戦闘効果使用ステージ(4.3.3, 18.4)。actor=その側(攻撃側→防御側の固定順)。

    ``roll_att``/``roll_def`` はロール由来ヒット(4.3.2、出目上限キャップ済み)。
    armorers はこの値を0にできる。無防備/司令官のボーナスおよび
    sappers/brutal-tactics の追加ヒットは軽減対象外で、``ctx.atk_extra_hits``/
    ``def_extra_hits`` と finalize 時の再計算(_finalize_battle_effects)で扱う。
    """

    ctx: BattleCtx = None
    roll_att: int = 0
    roll_def: int = 0


@dataclass(frozen=True)
class CommandWarrenDecision(Decision):
    """command-warren(18.3): 無消費の戦闘宣言機会。actor=カード所有派閥。
    合法手=通常の DeclareBattle 候補(候補が必ず1つ以上ある前提, キャンセル肢なし)。
    """


@dataclass(frozen=True)
class CobblerMoveDecision(Decision):
    """cobbler(18.3): 無消費の移動機会。actor=カード所有派閥。
    合法手=通常の移動候補(候補が必ず1つ以上ある前提, キャンセル肢なし)。
    """


@dataclass(frozen=True)
class MarquiseMarchDecision(Decision):
    """行軍の2移動目の機会(6.5.2)。actor=猫。応答は MarquiseMarch か
    MarquiseSkipMove。移動しても追加のアクションは消費しない。"""


@dataclass(frozen=True)
class WoodPaymentDecision(Decision):
    """建設の木材支払い(6.5.4.II, 19.1)。actor=猫。

    remaining(=残コスト)個の木材を1個ずつ ``MarquiseChooseWood`` で選ぶ。
    remaining==0 になったら建設を完了する(build_clearing / build_kind は
    完了処理への接続用)。支配は兵士+建物で決まり木材(トークン)除去では
    変わらないため、支払い途中で候補広場の連結・支配条件は変化しない。
    """

    remaining: int = 0
    build_clearing: int = 0
    build_kind: str = ""


@dataclass(frozen=True)
class FieldHospitalDecision(Decision):
    """野戦病院(6.2.3)。actor=猫。除去された猫兵士 count 個を城砦広場へ
    戻すか(一致カード消費)否かを選ぶ。

    ``ctx``/``roll_after`` は奇襲2ヒット(4.3.1.II)後のロール継続を
    病院解決後に引き継ぐための情報。
    """

    clearing: int = 0
    count: int = 0
    ctx: BattleCtx = None
    roll_after: bool = False


@dataclass(frozen=True)
class DiscardDecision(Decision):
    """手札を5枚に減らす(6.6)。"""


@dataclass(frozen=True)
class EyrieSetupCornerDecision(Decision):
    """開始時広場の隅を選ぶ(7.3.2)。"""


@dataclass(frozen=True)
class EyrieLeaderDecision(Decision):
    """君主カードを選ぶ(7.3.3 セットアップ / 7.7.3 失脚)。

    turmoil=True なら選択後に休止(7.7.4)で夕闇フェイズへ直行する。
    """

    turmoil: bool = False


@dataclass(frozen=True)
class EyrieDecreeDecision(Decision):
    """勅令への追加(7.4.2)。first=True は1枚目(追加は強制)。

    bird_added: 1枚目に鳥カードを追加済みか(鳥2枚同時は不可)。
    """

    first: bool = True
    bird_added: bool = False


@dataclass(frozen=True)
class EyrieRoostDecision(Decision):
    """止まり木確保(7.4.3)の配置先選択。"""


@dataclass(frozen=True)
class OutrageDecision(Decision):
    """蜂起の支払い先選択(8.2.6)。actor=支払う他派閥。

    clearing の動物種と一致する手札カード(鳥含む)から1枚を支援者ボックスへ。
    一致カードがなければ山札トップ1枚が自動で支援者ボックスへ入る。
    """

    clearing: int = 0


@dataclass(frozen=True)
class SupportersLimitDecision(Decision):
    """全拠点喪失時の支援者ボックス5枚調整(8.2.4)。actor=森林連合。"""


@dataclass(frozen=True)
class SupporterPaymentDecision(Decision):
    """支援者支払いの選択(8.4.1 / 8.4.2, 19.2)。actor=森林連合。

    支援者ボックスに一致 suit と鳥の両方があるときだけ積まれる(片方のみ
    なら自動支払い)。応答は ``AllianceSpendSupporter``。支払い1枚ごとに
    再push する。purpose / clearing は支払い完了後の処理(反乱の解決 or
    支持トークン配置)への接続用。
    """

    suit: Suit = None
    remaining: int = 0
    purpose: str = ""   # "revolt" | "spread"
    clearing: int = 0


# --- 放浪部族(第9章) ---
@dataclass(frozen=True)
class VagabondSetupCharacterDecision(Decision):
    """キャラクター選択(9.3.1)。"""


@dataclass(frozen=True)
class VagabondSetupForestDecision(Decision):
    """開始樹林の選択(9.3.2)。"""


@dataclass(frozen=True)
class RefreshDecision(Decision):
    """鳥歌の回復(9.4.1)。remaining 枚まで裏向きタイルを表に返す。"""

    remaining: int = 0


@dataclass(frozen=True)
class ItemDamageDecision(Decision):
    """受けヒット(9.2.7)・放浪者コマ全除去(9.2.2.I)のアイテム損傷。

    ``ctx``/``roll_after`` は奇襲2ヒット(4.3.1.II)の後にロールへ継続するための
    情報(9.2.6 の読み替え。放浪者コマは除去されないため戦闘は継続する)。
    """

    remaining: int = 0
    ctx: "BattleCtx" = None
    roll_after: bool = False


@dataclass(frozen=True)
class ItemLimitDecision(Decision):
    """夕闇のアイテム上限調整(9.6.4)。上限超過の間1枚ずつゲームから除外。"""


@dataclass(frozen=True)
class VagabondPayItemDecision(Decision):
    """援助(9.5.4)の「任意のアイテム1枚を使用」の選択(19.3)。actor=部族。

    支払える種類が複数あるときだけ積まれる(1種のみなら自動)。応答は
    ``VagabondExhaustItem``。remaining は常に1(観測用, 19.4)。
    aid_faction / aid_card_id / aid_take_item は支払い後に援助本体
    (カード譲渡・アイテム取得・関係処理)を続行するための接続用。
    支払いは取得より先(9.5.4)なので、取得アイテムは支払い候補に入らない。
    """

    remaining: int = 1
    aid_faction: FactionId = None
    aid_card_id: str = ""
    aid_take_item: Optional[str] = None


@dataclass(frozen=True)
class VagabondRepairDecision(Decision):
    """隠れ家(D.3.2)の「3枚まで修理」の選択(19.3)。actor=部族。

    損傷アイテムが4枚以上のときだけ積まれる(3枚以下なら全修理=自動)。
    応答は ``VagabondRepairItem``。1枚ごとに再push し、損傷が尽きるか
    remaining==0 で終了して隠れ家の後続処理(夕闇直行)へ進む。
    """

    remaining: int = 0
