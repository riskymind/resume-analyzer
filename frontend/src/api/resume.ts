import type { AnalysisListItem, AnalysisRecord, ResumeDetail, ResumeDocument, ResumeSummary } from '../types/api'
import { apiRequest, apiUpload, type UploadProgress } from './client'

const id = encodeURIComponent

/**
 * Quick review (legacy `POST /api/analyze`): a resume file plus a job description (pasted text OR a file).
 * Exactly one of jdText/jdFile should be provided.
 */
export async function analyzeResume({
  resumeFile,
  jdText,
  jdFile,
}: {
  resumeFile: File
  jdText?: string
  jdFile?: File
}): Promise<AnalysisRecord> {
  const formData = new FormData()
  formData.append('resume', resumeFile)
  if (jdFile) formData.append('jd_file', jdFile)
  else formData.append('jd_text', jdText ?? '')
  return apiRequest<AnalysisRecord>('/analyze', { method: 'POST', body: formData })
}

/** The signed-in user's past quick reviews, most recent first. */
export const fetchAnalyses = () => apiRequest<AnalysisListItem[]>('/analyses')

/** One past quick review, without re-calling the AI. */
export const fetchAnalysis = (analysisId: string | number) =>
  apiRequest<AnalysisRecord>(`/analyses/${id(String(analysisId))}`)

/** A stored resume with its verified structure and latest quality report. */
export const fetchResume = (resumeId: string) => apiRequest<ResumeDetail>(`/v1/resumes/${id(resumeId)}`)

/** The signed-in user's saved resumes (newest first) with their quality scores. */
export const fetchResumes = () => apiRequest<ResumeSummary[]>('/v1/resumes')

/** Uploads a resume (.pdf/.docx/.md); the server extracts, verifies and scores it. */
export function uploadResume(
  file: File,
  options: { onProgress?: (progress: UploadProgress) => void; signal?: AbortSignal } = {},
): Promise<ResumeDetail> {
  const formData = new FormData()
  formData.append('file', file)
  return apiUpload<ResumeDetail>('/v1/resumes', formData, options)
}

/** Deletes a resume and everything derived from it (analyses, matches and rewrites). */
export const deleteResume = (resumeId: string) => apiRequest<null>(`/v1/resumes/${id(resumeId)}`, { method: 'DELETE' })

/** The verified resume as an editable document with stable item ids (used to pick bullets to rewrite). */
export const fetchResumeDocument = (resumeId: string) =>
  apiRequest<ResumeDocument>(`/v1/resumes/${id(resumeId)}/document`)
