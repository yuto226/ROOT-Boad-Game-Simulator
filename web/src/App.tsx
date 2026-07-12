// Root 観戦ビューア(フェーズ7)。
// 左ペイン=対局生成フォーム+生成済み一覧、右ペイン=盤面+ステップ再生。
import { useEffect, useState } from 'react'
import './App.css'
import { fetchGame, fetchGames } from './api'
import { Board } from './components/Board'
import { FactionPanel } from './components/FactionPanel'
import { GameList } from './components/GameList'
import { GenerateForm } from './components/GenerateForm'
import { StepControls } from './components/StepControls'
import type { CreateGameResponse, GameRecord, GameSummary } from './types'

function App() {
  const [games, setGames] = useState<GameSummary[]>([])
  const [activeGameId, setActiveGameId] = useState<string | null>(null)
  const [activeRecord, setActiveRecord] = useState<GameRecord | null>(null)
  const [stepIndex, setStepIndex] = useState(0)

  function refreshGames() {
    fetchGames()
      .then(setGames)
      .catch(() => {
        // 一覧取得の失敗は致命的ではない(空一覧のまま表示)
      })
  }

  useEffect(refreshGames, [])

  function handleCreated(result: CreateGameResponse) {
    setActiveGameId(result.game_id)
    setActiveRecord(result.record)
    setStepIndex(0)
    refreshGames()
  }

  function handleSelect(gameId: string) {
    fetchGame(gameId)
      .then((record) => {
        setActiveGameId(gameId)
        setActiveRecord(record)
        setStepIndex(0)
      })
      .catch(() => {
        // 選択した対局が既にサーバ側から破棄されている等。一覧を再取得しておく。
        refreshGames()
      })
  }

  const currentStep = activeRecord?.steps[stepIndex] ?? null

  return (
    <div className="app">
      <header className="app-header">
        <h1>Root 観戦ビューア</h1>
      </header>

      <div className="app-body">
        <aside className="left-pane">
          <div className="panel">
            <h2>対局生成</h2>
            <GenerateForm onCreated={handleCreated} />
          </div>
          <div className="panel">
            <h2>生成済み対局</h2>
            <GameList games={games} activeGameId={activeGameId} onSelect={handleSelect} />
          </div>
        </aside>

        <main className="right-pane">
          {activeRecord && currentStep ? (
            <>
              <div className="right-pane-main">
                <div className="board-wrap">
                  <Board map={activeRecord.map} state={currentStep.state} />
                </div>
                <div className="side-panels">
                  <FactionPanel meta={activeRecord.meta} state={currentStep.state} />
                </div>
              </div>
              <StepControls
                steps={activeRecord.steps}
                stepIndex={stepIndex}
                onStepChange={setStepIndex}
              />
            </>
          ) : (
            <div className="viewer-empty">
              <p>
                左の「対局生成」から対局を生成するか、「生成済み対局」から選択すると
                ここに盤面が表示されます。
              </p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

export default App
