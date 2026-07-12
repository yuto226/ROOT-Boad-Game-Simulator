// faction_extras の値を人間が読める文字列に整形する(ui/viewer.html の
// formatExtraValue を移植)。値の形は派閥ごとに違う素朴な JSON なので、
// 配列/オブジェクト/真偽値/その他をそれぞれ緩く扱う。
export function formatExtraValue(v: unknown): string {
  if (v === null || v === undefined) return 'なし'
  if (Array.isArray(v)) {
    if (v.length === 0) return 'なし'
    return v
      .map((x) => (x !== null && typeof x === 'object' ? JSON.stringify(x) : String(x)))
      .join(', ')
  }
  if (typeof v === 'object') {
    const parts = Object.entries(v as Record<string, unknown>).map(([k, val]) => `${k}=${String(val)}`)
    return parts.length ? parts.join(', ') : 'なし'
  }
  if (typeof v === 'boolean') return v ? 'あり' : 'なし'
  return String(v)
}
