// 表示用の定数群。ui/viewer.html の同名定数(17.3)をそのまま移植。

// suit で広場の枠色(fox=赤茶, rabbit=黄, mouse=橙灰)
export const SUIT_COLORS: Record<string, string> = {
  fox: '#a0522d',
  rabbit: '#d9a521',
  mouse: '#9c8f7c',
  bird: '#4a4a4a',
}

// 派閥色
export const FACTION_COLORS: Record<string, string> = {
  marquise: '#d2691e',
  eyrie: '#1e5aa8',
  alliance: '#2e7d32',
  vagabond: '#616161',
  dummy: '#999999',
}

export const FACTION_LABELS: Record<string, string> = {
  marquise: '猫',
  eyrie: '鷲巣',
  alliance: '連合',
  vagabond: '放浪',
  dummy: 'ダミー',
}

// 建物・トークンの1〜2文字ラベル
export const KIND_LABELS: Record<string, string> = {
  sawmill: '製',
  workshop: '工',
  recruiter: '募',
  roost: '巣',
  base: '拠',
  keep: '城',
  wood: '木',
  sympathy: '支',
}

// 秋の地図(12広場)の固定座標(手動配置)。map.clearings の隣接から辺を描く。
export const CLEARING_COORDS: Record<number, [number, number]> = {
  0: [120, 90],
  1: [350, 70],
  2: [630, 100],
  3: [150, 300],
  4: [350, 230],
  5: [540, 380],
  6: [720, 260],
  7: [350, 400],
  8: [140, 560],
  9: [350, 560],
  10: [540, 560],
  11: [720, 480],
}

export const CLEARING_W = 140
export const CLEARING_H = 100

export function factionLabel(fid: string): string {
  return FACTION_LABELS[fid] ?? fid
}

export function factionColor(fid: string): string {
  return FACTION_COLORS[fid] ?? '#333'
}
