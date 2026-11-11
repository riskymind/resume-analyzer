import type { JobDetail, JobSummary, MatchDetail, MatchSummary } from '../types/api'
import { apiRequest } from './client'

const id = encodeURIComponent

/** Submits a job description as pasted text OR a .pdf/.docx/.md file; returns the verified extraction. */
export async function submitJob({ text, file }: { text?: string; file?: File | null }): Promise<JobDetail> {
  const formData = new FormData()
  if (file) formData.append('file', file)
  else formData.append('text', text ?? '')
  return apiRequest<JobDetail>('/v1/jobs', { method: 'POST', body: formData })
}

export const fetchJobs = () => apiRequest<JobSummary[]>('/v1/jobs')

export const fetchJob = (jobId: string) => apiRequest<JobDetail>(`/v1/jobs/${id(jobId)}`)

export const deleteJob = (jobId: string) => apiRequest<null>(`/v1/jobs/${id(jobId)}`, { method: 'DELETE' })

/** Runs the deterministic match of a saved resume against a saved job description. */
export const createMatch = ({ resumeId, jobId }: { resumeId: string; jobId: string }) =>
  apiRequest<MatchDetail>('/v1/matches', { method: 'POST', json: { resume_id: resumeId, job_id: jobId } })

export async function fetchMatches({ jobId, resumeId }: { jobId?: string; resumeId?: string } = {}) {
  const params = new URLSearchParams()
  if (jobId) params.set('job_id', jobId)
  if (resumeId) params.set('resume_id', resumeId)
  const query = params.toString()
  return apiRequest<MatchSummary[]>(`/v1/matches${query ? `?${query}` : ''}`)
}

export const fetchMatch = (matchId: string) => apiRequest<MatchDetail>(`/v1/matches/${id(matchId)}`)

export const deleteMatch = (matchId: string) => apiRequest<null>(`/v1/matches/${id(matchId)}`, { method: 'DELETE' })
