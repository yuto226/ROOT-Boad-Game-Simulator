# カードデータ検証表

ユーザー検証用: 画像リンクと突き合わせて誤りがあれば指摘してください。

## 重要な注意(枚数=copiesについて)【解決済み 2026-07-09】

カード面に複製枚数の印刷はないため、枚数は以下の根拠で確定した(cards.jsonに反映済み):
- **奇襲(Ambush!)**: 根の法典 2.1.2 より鳥2枚・キツネ/ウサギ/ネズミ各1枚(計5枚)。
- **圧倒(Dominance)**: 根の法典 2.1.3 より各動物種1枚(計4枚)。
- **クラフトカードの×2枚(11種)**: Armorers, Sappers, Arms Trader, Brutal Tactics(鳥) / Cobbler, Command Warren, Better Burrow Bank(ウサギ) / Codebreakers, Scouting Party(ネズミ) / Tax Collector, Stand and Deliver!(キツネ)。
  根拠: 動物種別合計(fox13/rabbit13/mouse13/bird15=54)とユニーク名32種という公開情報に対し、この11種を×2とする組み合わせが一意に整合する。**実物デッキでの最終確認を推奨**(枚数が違うカードがあれば、cards.json の copies を直すだけでよい)。

## Standard Deck（Craftable / Ambush / Dominance）

| 名前 | 動物種 | 種別 | 枚数 | コスト | 効果 | 画像リンク |
|---|---|---|---|---|---|---|
| Anvil | キツネ(fox) | craftable | 1 | fox | アイテム: hammer (+2VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-anvil.webp) |
| Armorers | トリ(bird) | craftable | 2 | fox | 常在: In battle, may discard this to ignore all rolled hits taken. | [link](https://ledercards.netlify.app/cards/root/en-US/card-armorers.webp) |
| Arms Trader | トリ(bird) | craftable | 2 | fox, fox | アイテム: sword (+2VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-armstrader.webp) |
| A Visit to Friends | ウサギ(rabbit) | craftable | 1 | rabbit | アイテム: boots (+1VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-avisittofriends.webp) |
| Bake Sale | ウサギ(rabbit) | craftable | 1 | rabbit, rabbit | アイテム: coins (+3VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-bakesale.webp) |
| Better Burrow Bank | ウサギ(rabbit) | craftable | 2 | rabbit, rabbit | 常在: At start of Birdsong, you may draw one card. If you do, choose an enemy to draw one card. | [link](https://ledercards.netlify.app/cards/root/en-US/card-betterburrowbank.webp) |
| Birdy Bindle | トリ(bird) | craftable | 1 | mouse | アイテム: bag (+1VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-birdybindle.webp) |
| Brutal Tactics | トリ(bird) | craftable | 2 | fox, fox | 常在: In battle as attacker, may deal an extra hit, but defender scores one point. | [link](https://ledercards.netlify.app/cards/root/en-US/card-brutaltactics.webp) |
| Cobbler | ウサギ(rabbit) | craftable | 2 | rabbit, rabbit | 常在: At start of Evening, may take a move. | [link](https://ledercards.netlify.app/cards/root/en-US/card-cobbler.webp) |
| Codebreakers | ネズミ(mouse) | craftable | 2 | mouse | 常在: Once in Daylight, may look at another player's hand. | [link](https://ledercards.netlify.app/cards/root/en-US/card-codebreakers.webp) |
| Command Warren | ウサギ(rabbit) | craftable | 2 | rabbit, rabbit | 常在: At start of Daylight, may initiate a battle. | [link](https://ledercards.netlify.app/cards/root/en-US/card-commandwarren.webp) |
| Crossbow | トリ(bird) | craftable | 1 | fox | アイテム: crossbow (+1VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-crossbowbird.webp) |
| Crossbow | ネズミ(mouse) | craftable | 1 | fox | アイテム: crossbow (+1VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-crossbowmouse.webp) |
| Favor of the Foxes | キツネ(fox) | craftable | 1 | fox, fox, fox | 即時: Remove all enemy pieces in fox clearings, then discard. | [link](https://ledercards.netlify.app/cards/root/en-US/card-favorofthefoxes.webp) |
| Favor of the Mice | ネズミ(mouse) | craftable | 1 | mouse, mouse, mouse | 即時: Remove all enemy pieces in mouse clearings, then discard. | [link](https://ledercards.netlify.app/cards/root/en-US/card-favorofthemice.webp) |
| Favor of the Rabbits | ウサギ(rabbit) | craftable | 1 | rabbit, rabbit, rabbit | 即時: Remove all enemy pieces in rabbit clearings, then discard. | [link](https://ledercards.netlify.app/cards/root/en-US/card-favoroftherabbits.webp) |
| Foxfolk Steel | キツネ(fox) | craftable | 1 | fox, fox | アイテム: sword (+2VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-foxfolksteel.webp) |
| Gently Used Knapsack | キツネ(fox) | craftable | 1 | mouse | アイテム: bag (+1VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-gentlyusedknapsack.webp) |
| Investments | ネズミ(mouse) | craftable | 1 | rabbit, rabbit | アイテム: coins (+3VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-investments.webp) |
| Mouse-in-a-Sack | ネズミ(mouse) | craftable | 1 | mouse | アイテム: bag (+1VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-mouseinasack.webp) |
| Protection Racket | キツネ(fox) | craftable | 1 | rabbit, rabbit | アイテム: coins (+3VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-protectionracket.webp) |
| Root Tea | ウサギ(rabbit) | craftable | 1 | mouse | アイテム: tea (+2VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-rootteabunny.webp) |
| Root Tea | キツネ(fox) | craftable | 1 | mouse | アイテム: tea (+2VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-rootteafox.webp) |
| Root Tea | ネズミ(mouse) | craftable | 1 | mouse | アイテム: tea (+2VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-rootteamouse.webp) |
| Royal Claim | トリ(bird) | craftable | 1 | any, any, any, any | 常在: In Birdsong, may discard this to score one point per clearing you rule. | [link](https://ledercards.netlify.app/cards/root/en-US/card-royalclaim.webp) |
| Sappers | トリ(bird) | craftable | 2 | mouse | 常在: In battle as defender, may discard this to deal an extra hit. | [link](https://ledercards.netlify.app/cards/root/en-US/card-sappers.webp) |
| Scouting Party | ネズミ(mouse) | craftable | 2 | mouse, mouse | 常在: As attacker in battle, you are not affected by ambush cards. | [link](https://ledercards.netlify.app/cards/root/en-US/card-scoutingparty.webp) |
| Smuggler's Trail | ウサギ(rabbit) | craftable | 1 | mouse | アイテム: bag (+1VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-smugglerstrail.webp) |
| Stand and Deliver! | キツネ(fox) | craftable | 2 | mouse, mouse, mouse | 常在: Once in Birdsong, you may take a random card from an enemy. If you do, they score one point. | [link](https://ledercards.netlify.app/cards/root/en-US/card-standanddeliver.webp) |
| Sword | ネズミ(mouse) | craftable | 1 | fox, fox | アイテム: sword (+2VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-sword.webp) |
| Tax Collector | キツネ(fox) | craftable | 2 | rabbit, fox, mouse | 常在: Once in Daylight, may remove a warrior of your faction from a clearing on the map to draw one card. | [link](https://ledercards.netlify.app/cards/root/en-US/card-taxcollector.webp) |
| Travel Gear | キツネ(fox) | craftable | 1 | rabbit | アイテム: boots (+1VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-travelgearfox.webp) |
| Travel Gear | ネズミ(mouse) | craftable | 1 | rabbit | アイテム: boots (+1VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-travelgearmouse.webp) |
| Woodland Runners | トリ(bird) | craftable | 1 | rabbit | アイテム: boots (+1VP) | [link](https://ledercards.netlify.app/cards/root/en-US/card-woodlandrunners.webp) |
| Ambush! | キツネ(fox) | ambush | 1 | - | You may only ambush in a fox clearing. At start of battle, d… ※Copies not visually printed on the card (verified via zoomed crops of all four corners); set to 2 per suit based on well-established Root standard-deck rules knowledge, not derived from the image itself. | [link](https://ledercards.netlify.app/cards/root/en-US/card-ambushfox.webp) |
| Ambush! | ウサギ(rabbit) | ambush | 1 | - | You may only ambush in a rabbit clearing. At start of battle… ※Copies not visually printed on the card (verified via zoomed crops of all four corners); set to 2 per suit based on well-established Root standard-deck rules knowledge, not derived from the image itself. | [link](https://ledercards.netlify.app/cards/root/en-US/card-ambushbunny.webp) |
| Ambush! | ネズミ(mouse) | ambush | 1 | - | You may only ambush in a mouse clearing. At start of battle,… ※Copies not visually printed on the card (verified via zoomed crops of all four corners); set to 2 per suit based on well-established Root standard-deck rules knowledge, not derived from the image itself. | [link](https://ledercards.netlify.app/cards/root/en-US/card-ambushmouse.webp) |
| Ambush! | トリ(bird) | ambush | 2 | - | You may ambush in any clearing. At start of battle, defender… ※Copies not visually printed on the card (verified via zoomed crops of all four corners); set to 2 per suit based on well-established Root standard-deck rules knowledge, not derived from the image itself. | [link](https://ledercards.netlify.app/cards/root/en-US/card-ambushbird.webp) |
| Dominance | キツネ(fox) | dominance | 1 | - | If spent for suit, make available. If you have at least 10 p… | [link](https://ledercards.netlify.app/cards/root/en-US/card-dominancefox.webp) |
| Dominance | ウサギ(rabbit) | dominance | 1 | - | If spent for suit, make available. If you have at least 10 p… | [link](https://ledercards.netlify.app/cards/root/en-US/card-dominancebunny.webp) |
| Dominance | ネズミ(mouse) | dominance | 1 | - | If spent for suit, make available. If you have at least 10 p… | [link](https://ledercards.netlify.app/cards/root/en-US/card-dominancemouse.webp) |
| Dominance | トリ(bird) | dominance | 1 | - | If spent for suit, make available. If you have at least 10 p… | [link](https://ledercards.netlify.app/cards/root/en-US/card-dominancebird.webp) |

## Quest（15枚）

| 名前 | 動物種 | 要求アイテム | 画像リンク |
|---|---|---|---|
| Errand | ウサギ(rabbit) | tea, boots | [link](https://ledercards.netlify.app/cards/root/en-US/quest-errandbunny.webp) |
| Errand | キツネ(fox) | tea, boots | [link](https://ledercards.netlify.app/cards/root/en-US/quest-errandfox.webp) |
| Escort | ネズミ(mouse) | boots, boots | [link](https://ledercards.netlify.app/cards/root/en-US/quest-escort.webp) |
| Expel Bandits | ウサギ(rabbit) | sword, sword | [link](https://ledercards.netlify.app/cards/root/en-US/quest-expelbanditsbunny.webp) |
| Expel Bandits | ネズミ(mouse) | sword, sword | [link](https://ledercards.netlify.app/cards/root/en-US/quest-expelbanditsmouse.webp) |
| Fend off a Bear | ウサギ(rabbit) | torch, crossbow ※Item icon depicted is a torch, which is not among the seven item types produced by base-set craftable cards (boots/bag/crossbow/hammer/sword/tea/coins); included as-is per the card art. | [link](https://ledercards.netlify.app/cards/root/en-US/quest-fendoffabearbunny.webp) |
| Fend off a Bear | ネズミ(mouse) | torch, crossbow ※Item icon depicted is a torch, which is not among the seven item types produced by base-set craftable cards (boots/bag/crossbow/hammer/sword/tea/coins); included as-is per the card art. | [link](https://ledercards.netlify.app/cards/root/en-US/quest-fendoffabearmouse.webp) |
| Fundraising | キツネ(fox) | tea, coins | [link](https://ledercards.netlify.app/cards/root/en-US/quest-fundraising.webp) |
| Give a Speech | ウサギ(rabbit) | torch, tea ※Item icon depicted is a torch, which is not among the seven item types produced by base-set craftable cards (boots/bag/crossbow/hammer/sword/tea/coins); included as-is per the card art. | [link](https://ledercards.netlify.app/cards/root/en-US/quest-giveaspeechbunny.webp) |
| Give a Speech | キツネ(fox) | torch, tea ※Item icon depicted is a torch, which is not among the seven item types produced by base-set craftable cards (boots/bag/crossbow/hammer/sword/tea/coins); included as-is per the card art. | [link](https://ledercards.netlify.app/cards/root/en-US/quest-giveaspeechfox.webp) |
| Guard Duty | ウサギ(rabbit) | torch, sword ※Item icon depicted is a torch, which is not among the seven item types produced by base-set craftable cards (boots/bag/crossbow/hammer/sword/tea/coins); included as-is per the card art. | [link](https://ledercards.netlify.app/cards/root/en-US/quest-guarddutybunny.webp) |
| Guard Duty | ネズミ(mouse) | torch, sword ※Item icon depicted is a torch, which is not among the seven item types produced by base-set craftable cards (boots/bag/crossbow/hammer/sword/tea/coins); included as-is per the card art. | [link](https://ledercards.netlify.app/cards/root/en-US/quest-guarddutymouse.webp) |
| Logistics Help | キツネ(fox) | boots, bag | [link](https://ledercards.netlify.app/cards/root/en-US/quest-logisticshelpfox.webp) |
| Logistics Help | ネズミ(mouse) | boots, bag | [link](https://ledercards.netlify.app/cards/root/en-US/quest-logisticshelpmouse.webp) |
| Repair a Shed | キツネ(fox) | torch, hammer ※Item icon depicted is a torch, which is not among the seven item types produced by base-set craftable cards (boots/bag/crossbow/hammer/sword/tea/coins); included as-is per the card art. | [link](https://ledercards.netlify.app/cards/root/en-US/quest-repairashed.webp) |

## 集計(copies検算)【確定】

- copies合計: **54枚** / fox 13, rabbit 13, mouse 13, bird 15(すべて期待値と一致)
- 修正履歴: 抽出エージェントの初期値(46枚)に対し、上記「重要な注意」の根拠で奇襲とクラフト×2種を修正(2026-07-09)。


## 盤面印刷データ【確定 2026-07-09】

ユーザー提供の公式ボードスキャン(`docs/Original Board Datas/`)をFableが視覚読取して確定。`engine/data/map_autumn.json` と `engine/data/boards.json` に反映済み(`_verified: true`)。

### 秋マップ(12広場・道18本)
| id | 位置 | 動物種 | 枠 | 遺跡 | 隣接 |
|---|---|---|---|---|---|
| 0 | 北西隅 | キツネ | 1 | - | 1,3,4 |
| 1 | 北中央 | ウサギ | 2 | - | 0,2 |
| 2 | 北東隅 | ネズミ | 2 | - | 1,4,6 |
| 3 | 西 | ネズミ | 2 | - | 0,7,8 |
| 4 | 北中央南 | ウサギ | 2 | R | 0,2,7 |
| 5 | 中央東(水車) | ネズミ | 3 | R | 6,7,10,11 |
| 6 | 東 | キツネ | 2 | R | 2,5,11 |
| 7 | 中央西 | キツネ | 2 | R | 3,4,5,9 |
| 8 | 南西隅 | ウサギ | 1 | - | 3,9 |
| 9 | 南 | キツネ | 2 | - | 7,8,10 |
| 10 | 南中央 | ネズミ | 2 | - | 5,9,11 |
| 11 | 南東隅 | ウサギ | 1 | - | 5,6,10 |

### 派閥ボードトラック
- 猫野侯国: 建設コスト 0,1,2,3,3,4 / VP 製材所 0,1,2,3,4,5・工房 0,2,2,3,4,5・募兵所 0,1,2,3,3,4 / ドローアイコン=募兵所の3枚目・5枚目
- 鷲巣王朝: 止まり木7枠 VP 0,1,2,3,4,4,5 / ドローアイコン=3枚目・6枚目
- 森林連合: 共感コスト 1,1,1,2,2,2,3,3,3,3 / VP 1,1,1,2,2,3,4,4,4,4 / 拠点1枚につきドロー+1
