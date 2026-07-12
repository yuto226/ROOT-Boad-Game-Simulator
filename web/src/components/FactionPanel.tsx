// サイド情報パネル群(ui/viewer.html の #vp-body/#turn-info/#hands-wrap/
// #extras-wrap/#draw-discard/#meta-line を移植)。
import type { GameMeta, GameState } from '../types'
import { factionColor, factionLabel } from '../constants'
import { formatExtraValue } from '../utils'

interface Props {
  meta: GameMeta
  state: GameState
}

function Swatch({ fid }: { fid: string }) {
  return <span className="swatch" style={{ background: factionColor(fid) }} />
}

export function FactionPanel({ meta, state }: Props) {
  const factionsOrder = meta.factions
  const winnerStr = meta.winner ? factionLabel(meta.winner) : '引き分け(timeout)'
  const metaLine = factionsOrder
    .map((f, idx) => `${factionLabel(f)}(${meta.policies[idx] ?? '?'})`)
    .join(' vs ')

  return (
    <>
      <div className="panel">
        <h2>対局情報</h2>
        <div>{metaLine}</div>
        <div>
          seed={meta.seed} / turns={meta.turns} / 勝者={winnerStr}
        </div>
      </div>

      <div className="panel">
        <h2>VP</h2>
        <table className="vp-table">
          <tbody>
            {factionsOrder.map((fid) => (
              <tr key={fid}>
                <td>
                  <Swatch fid={fid} />
                  {factionLabel(fid)}
                </td>
                <td>{state.vps[fid] ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>状況</h2>
        <div id="turn-info">
          ターン {state.turn_count} / {meta.max_turns}
          {state.finished ? '(終了)' : ''}
        </div>
        <div id="to-act">手番: {factionLabel(state.to_act)}</div>
        <div id="pending-info">
          {state.pending.length ? `保留: ${state.pending.join(' > ')}` : '保留なし'}
        </div>
      </div>

      <div className="panel">
        <h2>手札(タイトルでホバー一覧)</h2>
        <div id="hands-wrap">
          {factionsOrder.map((fid) => {
            const cards = state.hands[fid] ?? []
            return (
              <div key={fid} className="hand-row" title={cards.length ? cards.join(', ') : '(なし)'}>
                <Swatch fid={fid} />
                {factionLabel(fid)}: {cards.length}枚
              </div>
            )
          })}
        </div>
        <div id="draw-discard">
          山札 {state.draw_size}枚 / 捨て札上: {state.discard_top ?? '(なし)'}
        </div>
      </div>

      <div className="panel">
        <h2>派閥固有状態</h2>
        <div id="extras-wrap">
          {factionsOrder.map((fid) => {
            const extras = state.faction_extras[fid] ?? {}
            const keys = Object.keys(extras)
            return (
              <div key={fid} className="extras-block">
                <strong>{factionLabel(fid)}</strong>
                <br />
                {keys.length === 0
                  ? 'なし'
                  : keys.map((k, idx) => (
                      <span key={k}>
                        {idx > 0 && <br />}
                        {k}: {formatExtraValue(extras[k])}
                      </span>
                    ))}
              </div>
            )
          })}
        </div>
      </div>
    </>
  )
}
