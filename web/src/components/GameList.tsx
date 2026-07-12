// 生成済み対局の一覧(GET /api/games)。クリックで右ペインに読み込む。
import { factionLabel } from '../constants'
import type { GameSummary } from '../types'

interface Props {
  games: GameSummary[]
  activeGameId: string | null
  onSelect: (gameId: string) => void
}

export function GameList({ games, activeGameId, onSelect }: Props) {
  if (games.length === 0) {
    return <p className="muted">まだ対局がありません。上のフォームから生成してください。</p>
  }

  return (
    <ul className="game-list">
      {games.map(({ game_id, meta }) => {
        const winner = meta.winner ? factionLabel(meta.winner) : '引き分け'
        const label = meta.factions.map((f) => factionLabel(f)).join(' vs ')
        return (
          <li key={game_id}>
            <button
              className={game_id === activeGameId ? 'game-item active' : 'game-item'}
              onClick={() => onSelect(game_id)}
            >
              <span className="game-item-title">{label}</span>
              <span className="game-item-meta">
                seed={meta.seed} / turns={meta.turns} / 勝者={winner}
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
