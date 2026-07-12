// バックエンド(server/app.py)への fetch ラッパ。
// dev サーバの proxy(vite.config.ts)により相対パス /api/... で叩ける。

import type {
  CreateGameRequest,
  CreateGameResponse,
  GameRecord,
  GameSummary,
  ModelEntry,
} from './types'

// FastAPI の HTTPException は {"detail": "..."} を返す(4xx/5xx共通)。
class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // JSON でないボディは無視して statusText を使う
    }
    throw new ApiError(detail)
  }
  return res.json() as Promise<T>
}

export function fetchModels(): Promise<ModelEntry[]> {
  return request('/api/models')
}

export function fetchGames(): Promise<GameSummary[]> {
  return request('/api/games')
}

export function fetchGame(gameId: string): Promise<GameRecord> {
  return request(`/api/games/${encodeURIComponent(gameId)}`)
}

export function createGame(req: CreateGameRequest): Promise<CreateGameResponse> {
  return request('/api/games', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
}

export { ApiError }
