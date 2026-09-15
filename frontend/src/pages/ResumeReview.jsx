import { useState } from 'react'
import ResumeUploadForm from '../components/ResumeUploadForm'
import AnalysisReport from '../components/AnalysisReport'

/** The "new analysis" flow: upload form, then the resulting report. */
export default function ResumeReview() {
  const [record, setRecord] = useState(null)

  if (record) {
    return (
      <div>
        <AnalysisReport record={record} />
        <button onClick={() => setRecord(null)}>Analyze another resume</button>
      </div>
    )
  }

  return <ResumeUploadForm onAnalyzed={setRecord} />
}
