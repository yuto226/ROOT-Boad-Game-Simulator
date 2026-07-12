// 盤面SVG(ui/viewer.html buildBoardBase/renderBoard の移植)。
// 静的レイヤ(辺+広場の枠)と動的レイヤ(駒/建物)を1回のレンダーで描く
// (viewer.html は素のDOM操作で分離していたが、Reactでは差分描画が効くので
// 素直に1コンポーネントにまとめて問題ない)。
import type { ClearingState, GameState, MapData } from '../types'
import {
  CLEARING_COORDS,
  CLEARING_H,
  CLEARING_W,
  FACTION_COLORS,
  KIND_LABELS,
  SUIT_COLORS,
} from '../constants'

interface Props {
  map: MapData
  state: GameState
}

function ClearingLayer({ cs }: { cs: ClearingState }) {
  const factionIds = Object.keys(cs.soldiers)
  const soldierStartX = -((factionIds.length - 1) * 26) / 2

  const items = [...cs.buildings, ...cs.tokens]
  const perRow = 5

  return (
    <g>
      {factionIds.map((fid, idx) => {
        const cx = soldierStartX + idx * 26
        return (
          <g key={`s-${fid}`}>
            <circle cx={cx} cy={-16} r={12} fill={FACTION_COLORS[fid] ?? '#333'} />
            <text x={cx} y={-12} textAnchor="middle" fontSize={11} fontWeight="bold" fill="#fff">
              {cs.soldiers[fid]}
            </text>
          </g>
        )
      })}
      {items.map((it, idx) => {
        const row = Math.floor(idx / perRow)
        const col = idx % perRow
        const rowStart = row * perRow
        const rowCount = Math.min(perRow, items.length - rowStart)
        const bx = -((rowCount - 1) * 22) / 2 + col * 22
        const by = 16 + row * 22
        return (
          <g key={`b-${idx}`}>
            <rect
              x={bx - 9}
              y={by - 10}
              width={18}
              height={18}
              rx={3}
              fill={FACTION_COLORS[it.faction] ?? '#555'}
            />
            <text x={bx} y={by + 4} textAnchor="middle" fontSize={10} fill="#fff">
              {KIND_LABELS[it.kind] ?? it.kind.slice(0, 1)}
            </text>
          </g>
        )
      })}
    </g>
  )
}

export function Board({ map, state }: Props) {
  const byCid = new Map(state.clearings.map((cs) => [cs.cid, cs]))

  const edges: Array<[number, number]> = []
  const seen = new Set<string>()
  for (const c of map.clearings) {
    for (const adj of c.adjacent) {
      const key = `${Math.min(c.id, adj)}-${Math.max(c.id, adj)}`
      if (seen.has(key)) continue
      seen.add(key)
      edges.push([c.id, adj])
    }
  }

  return (
    <svg id="board-svg" viewBox="0 0 820 650" xmlns="http://www.w3.org/2000/svg">
      {edges.map(([a, b]) => {
        const p1 = CLEARING_COORDS[a]
        const p2 = CLEARING_COORDS[b]
        if (!p1 || !p2) return null
        return (
          <line
            key={`${a}-${b}`}
            x1={p1[0]}
            y1={p1[1]}
            x2={p2[0]}
            y2={p2[1]}
            stroke="#b8a97e"
            strokeWidth={3}
          />
        )
      })}
      {map.clearings.map((c) => {
        const pos = CLEARING_COORDS[c.id]
        if (!pos) return null
        const cs = byCid.get(c.id)
        return (
          <g key={c.id} transform={`translate(${pos[0]},${pos[1]})`}>
            <rect
              x={-CLEARING_W / 2}
              y={-CLEARING_H / 2}
              width={CLEARING_W}
              height={CLEARING_H}
              rx={12}
              fill="#fffaf0"
              stroke={SUIT_COLORS[c.suit] ?? '#888'}
              strokeWidth={5}
            />
            <text x={-CLEARING_W / 2 + 8} y={-CLEARING_H / 2 + 15} fontSize={11} fill="#6b5f47">
              {`#${c.id}${c.ruin ? ' 遺' : ''}${c.corner ? ' ' + c.corner : ''}`}
            </text>
            {cs && <ClearingLayer cs={cs} />}
          </g>
        )
      })}
    </svg>
  )
}
