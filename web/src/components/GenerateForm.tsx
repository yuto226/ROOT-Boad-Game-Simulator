// 対局生成フォーム。派閥2〜4行、各行=派閥select+policy select(random/
// heuristic/ckpt)+sampleチェック。POST /api/games で対局を1本生成する。
import { useEffect, useState } from 'react'
import { ApiError, createGame, fetchModels } from '../api'
import { factionLabel } from '../constants'
import type { CreateGameResponse, ModelEntry } from '../types'

const ALL_FACTIONS = ['marquise', 'eyrie', 'alliance', 'vagabond']
const MAX_TURNS = 300

interface FactionRow {
  faction: string
  // 'random' | 'heuristic' | <ckptパス>
  policyValue: string
  sample: boolean
}

function defaultRows(): FactionRow[] {
  return [
    { faction: 'marquise', policyValue: 'random', sample: false },
    { faction: 'eyrie', policyValue: 'random', sample: false },
  ]
}

interface Props {
  onCreated: (result: CreateGameResponse) => void
}

export function GenerateForm({ onCreated }: Props) {
  const [rows, setRows] = useState<FactionRow[]>(defaultRows)
  const [seed, setSeed] = useState(0)
  const [models, setModels] = useState<ModelEntry[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchModels()
      .then(setModels)
      .catch(() => {
        // モデル一覧の取得失敗は致命的ではない(random/heuristicのみ選択可能にする)
        setModels([])
      })
  }, [])

  function updateRow(idx: number, patch: Partial<FactionRow>) {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  function addRow() {
    if (rows.length >= 4) return
    const used = new Set(rows.map((r) => r.faction))
    const nextFaction = ALL_FACTIONS.find((f) => !used.has(f)) ?? ALL_FACTIONS[0]
    setRows((prev) => [...prev, { faction: nextFaction, policyValue: 'random', sample: false }])
  }

  function removeRow(idx: number) {
    if (rows.length <= 2) return
    setRows((prev) => prev.filter((_, i) => i !== idx))
  }

  function availableFactions(idx: number): string[] {
    const usedByOthers = new Set(rows.filter((_, i) => i !== idx).map((r) => r.faction))
    return ALL_FACTIONS.filter((f) => f === rows[idx].faction || !usedByOthers.has(f))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const policies = rows.map((r) => {
        if (r.policyValue === 'random' || r.policyValue === 'heuristic') return r.policyValue
        return `nn:${r.policyValue}${r.sample ? ':sample' : ''}`
      })
      const result = await createGame({
        factions: rows.map((r) => r.faction),
        policies,
        seed,
        max_turns: MAX_TURNS,
      })
      onCreated(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="generate-form" onSubmit={handleSubmit}>
      {rows.map((row, idx) => (
        <div className="faction-row" key={idx}>
          <select
            value={row.faction}
            onChange={(e) => updateRow(idx, { faction: e.target.value })}
          >
            {availableFactions(idx).map((f) => (
              <option key={f} value={f}>
                {factionLabel(f)}
              </option>
            ))}
          </select>
          <select
            value={row.policyValue}
            onChange={(e) => updateRow(idx, { policyValue: e.target.value })}
          >
            <option value="random">random</option>
            <option value="heuristic">heuristic</option>
            {models.map((m) => (
              <option key={m.path} value={m.path}>
                {m.run} #{m.update}
              </option>
            ))}
          </select>
          <label className="sample-check">
            <input
              type="checkbox"
              checked={row.sample}
              disabled={row.policyValue === 'random' || row.policyValue === 'heuristic'}
              onChange={(e) => updateRow(idx, { sample: e.target.checked })}
            />
            sample
          </label>
          <button
            type="button"
            className="row-remove"
            title="この行を削除"
            disabled={rows.length <= 2}
            onClick={() => removeRow(idx)}
          >
            ×
          </button>
        </div>
      ))}

      <button type="button" onClick={addRow} disabled={rows.length >= 4}>
        + 派閥を追加
      </button>

      <div className="seed-row">
        <label>
          seed
          <input
            type="number"
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value))}
          />
        </label>
      </div>

      <button type="submit" disabled={submitting} className="generate-btn">
        {submitting ? '生成中…' : '▶ 生成'}
      </button>
      {error && <p className="error-text">{error}</p>}
    </form>
  )
}
