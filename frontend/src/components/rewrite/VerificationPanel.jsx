import { IssueList } from './SuggestionCard'

const STATUS = {
  verified: {
    title: 'Every change is supported by your original resume',
    tone: 'is-ok',
  },
  needs_review: {
    title: 'Some changes need your review',
    tone: 'is-review',
  },
  unsupported: {
    title: 'The resume contains claims your original resume does not support',
    tone: 'is-unsupported',
  },
}

/** Factual verification of the saved content, plus guidance from the AI that never becomes resume text. */
export default function VerificationPanel({ verification, generation }) {
  const status = STATUS[verification.status]
  const visible = verification.issues.filter((issue) => issue.severity !== 'info' || issue.origin === 'user')
  return (
    <section
      className={`rewrite-panel verification ${status.tone}`}
      aria-labelledby="verification-title"
      aria-live="polite"
    >
      <h2 id="verification-title">{status.title}</h2>
      <p className="report-meta">
        {verification.blocking} unsupported · {verification.warnings} to check · {verification.pending_review}{' '}
        suggestion(s) awaiting review · {verification.rejected_suggestions} rejected automatically
      </p>
      {verification.status === 'unsupported' && (
        <p className="quality-note">
          Unsupported items come from your own edits. They are not marked as verified. You can still export after
          confirming them in the download section, so make sure every claim is true.
        </p>
      )}
      <IssueList issues={visible} />
      <details className="checks">
        <summary>What we check</summary>
        <ul>
          {verification.checks.map((check) => (
            <li key={check}>{check}</li>
          ))}
        </ul>
      </details>

      {generation.gaps.length > 0 && (
        <>
          <p className="sub-head">Gaps: job requirements your resume doesn't show</p>
          <ul className="gap-list">
            {generation.gaps.map((gap) => (
              <li key={gap.requirement_id}>
                <span className={`req-badge ${gap.classification === 'required' ? 'is-required' : 'is-preferred'}`}>
                  {gap.classification}
                </span>{' '}
                {gap.message}
              </li>
            ))}
          </ul>
        </>
      )}

      {generation.metric_prompts.length > 0 && (
        <>
          <p className="sub-head">Add a figure if you have one</p>
          <ul className="gap-list">
            {generation.metric_prompts.map((prompt) => (
              <li key={prompt.item_id}>
                <strong>{prompt.question}</strong>
                <br />
                <small>{prompt.bullet}</small>
              </li>
            ))}
          </ul>
          <p className="report-meta">We never invent numbers. Edit the bullet to add a real figure.</p>
        </>
      )}

      {generation.alignment_notes.length > 0 && (
        <>
          <p className="sub-head">How the rewrite targets the job (AI explanation)</p>
          <ul className="gap-list">
            {generation.alignment_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </>
      )}

      {generation.warnings.map((warning) => (
        <p key={warning} className="quality-note">
          {warning}
        </p>
      ))}
    </section>
  )
}
