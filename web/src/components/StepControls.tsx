// ステップ再生コントロール(ui/viewer.html footer + #action-info の移植)。
// 自動再生は「1ステップ進めるたびに次のタイマーを張り直す」自己再帰的な
// setTimeout で実装する(600ms / speed 間隔)。
import { useEffect, useState } from 'react'
import type { GameStep } from '../types'
import { factionLabel } from '../constants'

interface Props {
  steps: GameStep[]
  stepIndex: number
  onStepChange: (i: number) => void
}

const SPEEDS = [0.5, 1, 2, 4]

export function StepControls({ steps, stepIndex, onStepChange }: Props) {
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)

  const lastIndex = steps.length - 1
  const step = steps[stepIndex]

  // 自動再生の実体: stepIndex が変わるたびに「再生中なら次へ進める」タイマーを張り直す
  useEffect(() => {
    if (!playing) return
    if (stepIndex >= lastIndex) {
      setPlaying(false)
      return
    }
    const id = window.setTimeout(() => {
      onStepChange(stepIndex + 1)
    }, 600 / speed)
    return () => window.clearTimeout(id)
  }, [playing, stepIndex, speed, lastIndex, onStepChange])

  function togglePlay() {
    if (stepIndex >= lastIndex) onStepChange(0)
    setPlaying((p) => !p)
  }

  function prev() {
    setPlaying(false)
    onStepChange(Math.max(0, stepIndex - 1))
  }

  function next() {
    setPlaying(false)
    onStepChange(Math.min(lastIndex, stepIndex + 1))
  }

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'ArrowLeft') prev()
      else if (e.key === 'ArrowRight') next()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepIndex, lastIndex])

  const actionText =
    step.action === null || step.action === undefined
      ? '(初期状態)'
      : `${step.actor ? `${factionLabel(step.actor)}: ` : ''}${step.action}`

  return (
    <>
      <div className="panel">
        <h2>直前アクション</h2>
        <div id="action-info">{actionText}</div>
      </div>
      <footer>
        <button title="前へ(←)" onClick={prev}>
          ◀
        </button>
        <button title="自動再生" onClick={togglePlay}>
          {playing ? '⏸' : '▶'}
        </button>
        <button title="次へ(→)" onClick={next}>
          ▶
        </button>
        <input
          id="step-slider"
          type="range"
          min={0}
          max={Math.max(0, lastIndex)}
          step={1}
          value={stepIndex}
          disabled={lastIndex <= 0}
          onChange={(e) => {
            setPlaying(false)
            onStepChange(Number(e.target.value))
          }}
        />
        <span id="step-label">
          {stepIndex} / {lastIndex}
        </span>
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s}x
            </option>
          ))}
        </select>
      </footer>
    </>
  )
}
