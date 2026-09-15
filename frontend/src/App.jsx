import PingGeminiButton from './components/PingGeminiButton'

export default function App() {
  return (
    <div style={{ fontFamily: 'sans-serif', padding: '2rem' }}>
      <h1>Resume Analyzer</h1>
      <p>Full-stack smoke test: frontend → backend → Gemini.</p>
      <PingGeminiButton />
    </div>
  )
}
