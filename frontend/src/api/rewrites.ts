import type {
  ExportFormat,
  PreviewResponse,
  RewriteDetail,
  RewriteMode,
  RewriteScope,
  RewriteSummary,
  RewriteUpdateChanges,
  TemplateInfo,
  TemplateKey,
} from '../types/api'
import { apiDownload, apiRequest } from './client'

const BASE = '/v1/rewrites'
const id = encodeURIComponent

export const fetchTemplates = () => apiRequest<TemplateInfo[]>(`${BASE}/templates`)

export const fetchRewrites = () => apiRequest<RewriteSummary[]>(BASE)

export interface CreateRewriteInput {
  resumeId: string
  jobId?: string | null
  scope: RewriteScope
  mode?: RewriteMode | null
  bulletIds?: string[]
  name?: string | null
}

/** Starts an AI rewrite. */
export function createRewrite({ resumeId, jobId, scope, mode, bulletIds = [], name }: CreateRewriteInput) {
  return apiRequest<RewriteDetail>(BASE, {
    method: 'POST',
    json: {
      resume_id: resumeId,
      job_id: jobId || null,
      scope,
      mode: mode || null,
      bullet_ids: scope === 'bullets' ? bulletIds : [],
      name: name || null,
    },
  })
}

/** The current version, or a specific older one (read-only view). */
export const fetchRewrite = (rewriteId: string, version?: number | null) =>
  apiRequest<RewriteDetail>(`${BASE}/${id(rewriteId)}${version ? `?version=${encodeURIComponent(version)}` : ''}`)

/**
 * Saves one change against the version the user is looking at (baseVersion):
 * { name } / { template } / { decisions: {suggestionId: 'accepted'|'rejected'} } / { content } / { restore_version }.
 * The server answers 409 `conflict` when another tab saved first.
 */
export const updateRewrite = (rewriteId: string, baseVersion: number, changes: RewriteUpdateChanges) =>
  apiRequest<RewriteDetail>(`${BASE}/${id(rewriteId)}`, {
    method: 'PATCH',
    json: { base_version: baseVersion, ...changes },
  })

export const regenerateRewrite = (
  rewriteId: string,
  baseVersion: number,
  { scope, bulletIds = [], mode }: { scope: RewriteScope; bulletIds?: string[]; mode?: RewriteMode | null },
) =>
  apiRequest<RewriteDetail>(`${BASE}/${id(rewriteId)}/regenerate`, {
    method: 'POST',
    json: { base_version: baseVersion, scope, bullet_ids: bulletIds, mode: mode || null },
  })

export const deleteRewrite = (rewriteId: string) => apiRequest<null>(`${BASE}/${id(rewriteId)}`, { method: 'DELETE' })

export function fetchPreview(
  rewriteId: string,
  { template, version }: { template?: TemplateKey | null; version?: number | null } = {},
) {
  const params = new URLSearchParams()
  if (template) params.set('template', template)
  if (version) params.set('version', String(version))
  return apiRequest<PreviewResponse>(`${BASE}/${id(rewriteId)}/preview?${params}`)
}

export interface ExportInput {
  format: ExportFormat
  template: TemplateKey
  version?: number | null
  /** Required by the server (409 `acknowledgement_required`) when the version has unverified claims. */
  acknowledgeUnverified?: boolean
}

/** Generates the PDF/DOCX on the server and saves it through the browser. */
export async function downloadExport(
  rewriteId: string,
  { format, template, version, acknowledgeUnverified = false }: ExportInput,
): Promise<string> {
  const { blob, filename } = await apiDownload(`${BASE}/${id(rewriteId)}/export`, {
    json: { format, template, version: version || null, acknowledge_unverified: acknowledgeUnverified },
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return filename
}
