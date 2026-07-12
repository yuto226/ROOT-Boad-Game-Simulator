// バックエンド(server/app.py)のレスポンス型。
// スキーマは tools/record_game.py の snapshot/build_output が正。
// engine/DESIGN.md 17.2 に定義がある({meta, map, steps})。

export type FactionId = 'marquise' | 'eyrie' | 'alliance' | 'vagabond' | 'dummy'

// ------------------------------------------------------------
// GET /api/models
// ------------------------------------------------------------
export interface ModelEntry {
  run: string
  update: number
  path: string
  mtime: string
  size_bytes: number
}

// ------------------------------------------------------------
// GET/POST /api/games
// ------------------------------------------------------------
export interface GameMeta {
  factions: string[]
  policies: string[]
  seed: number
  max_turns: number
  winner: string | null
  winners: string[]
  vps: Record<string, number>
  turns: number
  timeout: boolean
  recorded_at: string
}

export interface GameSummary {
  game_id: string
  meta: GameMeta
}

export interface ClearingCorner {
  faction: string
  kind: string
}

export interface MapClearing {
  id: number
  suit: string
  slots: number
  ruin: boolean
  corner: string | null
  adjacent: number[]
}

export interface MapData {
  clearings: MapClearing[]
}

export interface ClearingState {
  cid: number
  soldiers: Record<string, number>
  buildings: ClearingCorner[]
  tokens: ClearingCorner[]
  ruin: boolean
}

// faction_extras の内容は派閥ごとに形が違う(record_game.py:_faction_extras)。
// 共通の dominance_card に加え、派閥別のフィールドが載る。表示側は
// キー名をそのまま列挙するので厳密な型付けはせず、値だけ緩く受ける。
export type FactionExtras = Record<string, unknown>

export interface GameState {
  turn_count: number
  to_act: string
  finished: boolean
  pending: string[]
  vps: Record<string, number>
  clearings: ClearingState[]
  hands: Record<string, string[]>
  draw_size: number
  discard_top: string | null
  faction_extras: Record<string, FactionExtras>
}

export interface GameStep {
  i: number
  actor: string | null
  action: string | null
  state: GameState
}

export interface GameRecord {
  meta: GameMeta
  map: MapData
  steps: GameStep[]
}

export interface CreateGameResponse {
  game_id: string
  record: GameRecord
}

export interface CreateGameRequest {
  factions: string[]
  policies: string[]
  seed: number
  max_turns: number
}
