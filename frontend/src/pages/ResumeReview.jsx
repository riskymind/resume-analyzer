import { useState } from 'react'
import ResumeUploadForm from '../components/ResumeUploadForm'
import AnalysisReport from '../components/AnalysisReport'

/** The "new analysis" flow: upload form, then the resulting report. */
export default function ResumeReview() {
  const [record, setRecord] = useState(null)

  if (record) {
    return (
      <div>
        <button className="btn-quiet report-back" onClick={() => setRecord(null)}>
          ← Review another resume
        </button>
        <AnalysisReport record={record} />
      </div>
    )
  }

  return <ResumeUploadForm onAnalyzed={setRecord} />
}
