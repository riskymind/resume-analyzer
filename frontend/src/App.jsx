import { useState } from 'react'
import ResumeReview from './pages/ResumeReview'
import HistoryList from './components/HistoryList'
import AnalysisReport from './components/AnalysisReport'

export default function App() {
  const [tab, setTab] = useState('new') // 'new' | 'history'
  const [historyRecord, setHistoryRecord] = useState(null)

  function selectTab(next) {
    setTab(next)
    setHistoryRecord(null)
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-wordmark">Resume Analyzer</span>
        <nav className="app-nav">
          <button
            className={tab === 'new' ? 'is-active' : ''}
            onClick={() => selectTab('new')}
          >
            New review
          </button>
          <button
            className={tab === 'history' ? 'is-active' : ''}
            onClick={() => selectTab('history')}
          >
            History
          </button>
        </nav>
      </header>

      {tab === 'new' && <ResumeReview />}

      {tab === 'history' &&
        (historyRecord ? (
          <div>
            <button className="btn-quiet report-back" onClick={() => setHistoryRecord(null)}>
              ← Back to history
            </button>
            <AnalysisReport record={historyRecord} />
          </div>
        ) : (
          <HistoryList onSelect={setHistoryRecord} />
        ))}
    </div>
  )
}
