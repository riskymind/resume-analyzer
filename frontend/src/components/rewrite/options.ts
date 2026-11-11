import type { RewriteMode, RewriteScope } from '../../types/api'

export interface ScopeOption {
  key: RewriteScope
  label: string
  hint?: string
  needsJob?: boolean
}

export interface ModeOption {
  key: RewriteMode
  label: string
  needsJob?: boolean
}

export const SCOPES: ScopeOption[] = [
  { key: 'full', label: 'Full resume', hint: 'Summary, experience, skills, projects and section order.' },
  { key: 'summary', label: 'Professional summary only' },
  { key: 'experience', label: 'Work experience only' },
  { key: 'bullets', label: 'Selected experience bullets' },
  { key: 'skills', label: 'Skills section', hint: 'Reorders your existing skills; never adds new ones.' },
  { key: 'projects', label: 'Projects section' },
  {
    key: 'education',
    label: 'Education and certifications',
    hint: 'Order and presentation only; content is never changed.',
  },
  {
    key: 'keywords',
    label: 'Targeted keyword optimisation',
    hint: 'Small edits using job keywords your resume already supports.',
    needsJob: true,
  },
]

export const MODES: ModeOption[] = [
  { key: 'job_targeted', label: 'Job-specific', needsJob: true },
  { key: 'ats', label: 'ATS optimisation' },
  { key: 'professional', label: 'Professional rewrite' },
  { key: 'executive', label: 'Executive' },
]

export const MODE_LABELS = Object.fromEntries(MODES.map((mode) => [mode.key, mode.label])) as Record<
  RewriteMode,
  string
>
