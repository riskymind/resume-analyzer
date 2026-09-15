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
    <div style={{ fontFamily: 'sans-serif', padding: '2rem', maxWidth: 720, margin: '0 auto' }}>
      <h1>Resume Analyzer</h1>

      <nav style={{ marginBottom: '1.5rem' }}>
        <button onClick={() => selectTab('new')} disabled={tab === 'new'}>
          New Analysis
        </button>{' '}
        <button onClick={() => selectTab('history')} disabled={tab === 'history'}>
          History
        </button>
      </nav>

      {tab === 'new' && <ResumeReview />}

      {tab === 'history' &&
        (historyRecord ? (
          <div>
            <AnalysisReport record={historyRecord} />
            <button onClick={() => setHistoryRecord(null)}>Back to history</button>
          </div>
        ) : (
          <HistoryList onSelect={setHistoryRecord} />
        ))}
    </div>
  )
}
